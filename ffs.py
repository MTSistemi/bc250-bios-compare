# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening a UEFI volume: files, sections, decompression, nested volumes.

A volume is a sequence of FILES (FFS); every file is a sequence of SECTIONS;
some sections are compressed and hold further sections inside; one of those
sections can be a whole new volume. The menus we are after sit at the end of
that chain, and reaching them means walking all of it.

We do this part ourselves - uefi-firmware-parser could do it - for a practical
reason: the emulator has to run on Windows and on Linux without asking anyone
to install anything, and we need the EXACT POSITION of everything inside the
image, not a pile of files in a directory. Without the positions a modified
image cannot be put back together.

WARNING: the LZMA in here is not an .xz and not GNU's .lzma: it is the "alone"
format (5 property bytes + 8 length bytes + stream). Python reads it with
lzma.FORMAT_ALONE; with FORMAT_AUTO it answers that the data is not valid, and
a perfectly good image looks corrupt.
"""
from __future__ import unicode_literals

import lzma
import struct

from volumes import guid_string

# --- FFS file types --------------------------------------------------------
FILE_TYPES = {
    0x01: "raw",
    0x02: "freeform",
    0x03: "security core",
    0x04: "PEI core",
    0x05: "DXE core",
    0x06: "PEIM",
    0x07: "driver",
    0x08: "combined PEIM driver",
    0x09: "application",
    0x0A: "SMM",
    0x0B: "nested volume",
    0x0C: "combined SMM DXE",
    0x0D: "SMM core",
    0xF0: "padding",
}

# --- section types ---------------------------------------------------------
SECTION_COMPRESSED = 0x01
SECTION_GUIDED = 0x02
SECTION_PE32 = 0x10
SECTION_PIC = 0x11
SECTION_TE = 0x12
SECTION_DEPEX_DXE = 0x13
SECTION_VERSION = 0x14
SECTION_NAME = 0x15
SECTION_VOLUME = 0x17
SECTION_RAW = 0x19
SECTION_DEPEX_PEI = 0x1B
SECTION_DEPEX_SMM = 0x1C

SECTION_TYPES = {
    SECTION_COMPRESSED: "compressed",
    SECTION_GUIDED: "guided",
    0x03: "disposable",
    SECTION_PE32: "PE32",
    SECTION_PIC: "PIC",
    SECTION_TE: "TE",
    SECTION_DEPEX_DXE: "DXE dependencies",
    SECTION_VERSION: "version",
    SECTION_NAME: "name",
    0x16: "16-bit compatibility",
    SECTION_VOLUME: "volume",
    0x18: "freeform subtype",
    SECTION_RAW: "raw",
    SECTION_DEPEX_PEI: "PEI dependencies",
    SECTION_DEPEX_SMM: "SMM dependencies",
}

# --- guided sections we know how to open -----------------------------------
GUID_LZMA = "EE4E5898-3914-4259-9D6E-DC7BD79403CF"
GUID_LZMA_X86 = "D42AE6BD-1352-4BFB-909A-CA72A6EAE889"
GUID_CRC32 = "FC1BCDB0-7D31-49AA-936A-A4600D9DD083"
GUID_TIANO = "A31280AD-481E-41B6-95E8-127F4C984779"


class FormatError(Exception):
    """Something in the firmware does not follow the specification.

    The message must say WHERE and WHAT, not just "error": whoever reads it
    almost certainly has a different BIOS image from ours and needs to work out
    whether their image is odd or our reader is incomplete.
    """


class Section(object):
    def __init__(self, kind, data, offset, guid=None):
        self.kind = kind
        self.data = data                # payload, header excluded
        self.offset = offset            # absolute position in the image
        self.guid = guid                # guided sections only
        self.children = []              # sections held inside, if a container
        self.volume = None              # nested volume, when kind == volume
        self.opened = True              # False when we cannot decompress it
        self.reason = ""                # why it was not opened

    @property
    def type_name(self):
        return SECTION_TYPES.get(self.kind, "type 0x%02X" % self.kind)

    def __repr__(self):
        return "<Section %s %d bytes>" % (self.type_name, len(self.data))


class FfsFile(object):
    def __init__(self, guid, kind, offset, size, data):
        self.guid = guid
        self.kind = kind
        self.offset = offset
        self.size = size
        self.data = data                # body, header excluded
        self.sections = []

    @property
    def type_name(self):
        return FILE_TYPES.get(self.kind, "type 0x%02X" % self.kind)

    def __repr__(self):
        return "<FfsFile %s %s %d bytes>" % (self.guid, self.type_name, self.size)


# ------------------------------------------------------------- decompression

def _decompress_lzma(data, x86_filter=False):
    """LZMA "alone": 5 property bytes, 8 length bytes, then the stream.

    In firmware the length field is sometimes 0xFFFF... (unknown) and sometimes
    right: we do not trust it, we decompress and look at what comes out.
    """
    if len(data) < 13:
        raise FormatError("LZMA stream too short: %d bytes" % len(data))
    if not x86_filter:
        decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        return decompressor.decompress(data)

    # The "x86" variant applies the BCJ filter first. FORMAT_ALONE does not
    # take a filter chain, so the properties are read by hand and the stream is
    # handed to FORMAT_RAW.
    properties = data[0]
    dictionary = struct.unpack_from("<I", data, 1)[0]
    pb, rest = divmod(properties, 45)
    lp, lc = divmod(rest, 9)
    chain = [
        {"id": lzma.FILTER_X86},
        {"id": lzma.FILTER_LZMA1, "dict_size": dictionary,
         "lc": lc, "lp": lp, "pb": pb},
    ]
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=chain)
    return decompressor.decompress(data[13:])


# ------------------------------------------------------------------ sections

def read_sections(data, base_offset=0):
    """The sections held in `data`, opening the compressed ones as well."""
    sections = []
    position = 0
    while position + 4 <= len(data):
        size = data[position] | (data[position + 1] << 8) | (data[position + 2] << 16)
        kind = data[position + 3]
        header = 4
        if size == 0xFFFFFF:
            # Large section: the real size is in the next 4 bytes.
            if position + 8 > len(data):
                break
            size = struct.unpack_from("<I", data, position + 4)[0]
            header = 8
        if size < header or position + size > len(data):
            break

        body = data[position + header:position + size]
        section = Section(kind, body, base_offset + position)

        if kind == SECTION_COMPRESSED and len(body) >= 5:
            _open_compressed(section, body)
        elif kind == SECTION_GUIDED and len(body) >= 20:
            _open_guided(section, body, base_offset + position + header)

        sections.append(section)

        # Sections are aligned to 4 bytes inside the file.
        position += size
        position = (position + 3) & ~3
    return sections


def _open_compressed(section, body):
    """A COMPRESSION section: 4 bytes of length + 1 byte of algorithm."""
    algorithm = body[4]
    inside = body[5:]
    if algorithm == 0:
        section.children = read_sections(inside, section.offset)
        return
    if algorithm == 2:                      # "customized", in practice LZMA
        try:
            section.children = read_sections(_decompress_lzma(inside), 0)
            return
        except Exception as error:          # noqa: BLE001
            section.opened = False
            section.reason = "LZMA cannot be decompressed: %s" % error
            return
    # Algorithm 1 is EFI/Tiano. We have not met it in these images; if it turns
    # up, the decompressor has to be written (Python does not have one).
    section.opened = False
    section.reason = ("EFI/Tiano compression (algorithm %d) not implemented"
                      % algorithm)


def _open_guided(section, body, body_offset):
    """A GUID_DEFINED section: the GUID says how the rest is treated."""
    section.guid = guid_string(body[:16])
    data_start, _attributes = struct.unpack_from("<HH", body, 16)
    if data_start < 20 or data_start > len(body) + 4:
        section.opened = False
        section.reason = "data offset outside the section (%d)" % data_start
        return
    # `data_start` counts from the start of the section, common header
    # included; `body` starts after those 4 header bytes, hence the -4.
    inside = body[max(0, data_start - 4):]

    if section.guid == GUID_LZMA:
        try:
            section.children = read_sections(_decompress_lzma(inside), 0)
        except Exception as error:          # noqa: BLE001
            section.opened = False
            section.reason = "LZMA cannot be decompressed: %s" % error
    elif section.guid == GUID_LZMA_X86:
        try:
            section.children = read_sections(
                _decompress_lzma(inside, x86_filter=True), 0)
        except Exception as error:          # noqa: BLE001
            section.opened = False
            section.reason = "LZMA+x86 cannot be decompressed: %s" % error
    elif section.guid == GUID_CRC32:
        # Not compression: just a CRC in front of the real data.
        section.children = read_sections(inside, body_offset)
    elif section.guid == GUID_TIANO:
        section.opened = False
        section.reason = "Tiano compression not implemented"
    else:
        # Many guided sections are digital signatures: a normal section sits
        # inside anyway, and trying costs nothing.
        children = read_sections(inside, body_offset)
        if children:
            section.children = children
        else:
            section.opened = False
            section.reason = "unknown guided section: %s" % section.guid


# --------------------------------------------------------------------- files

def read_files(volume):
    """The FFS files of the volume, in order, with their sections opened."""
    data = volume.data
    empty = 0xFF if volume.erase_polarity else 0x00
    position = volume.header_length

    # When an extended header is present, files start after it.
    if volume.ext_header_offset:
        ext_start = volume.ext_header_offset
        if ext_start + 20 <= len(data):
            ext_length = struct.unpack_from("<I", data, ext_start + 16)[0]
            position = max(position, ext_start + ext_length)
            position = (position + 7) & ~7

    files = []
    while position + 24 <= len(data):
        header = data[position:position + 24]
        if all(byte == empty for byte in header):
            break                                  # erased from here on

        size = header[20] | (header[21] << 8) | (header[22] << 16)
        attributes = header[19]
        header_length = 24
        if attributes & 0x01 and size == 0:        # large file (FFS3 only)
            if position + 32 > len(data):
                break
            size = struct.unpack_from("<Q", data, position + 24)[0]
            header_length = 32
        if size < header_length or position + size > len(data):
            break

        kind = header[18]
        body = data[position + header_length:position + size]
        entry = FfsFile(
            guid=guid_string(header[:16]),
            kind=kind,
            offset=volume.offset + position,
            size=size,
            data=body,
        )
        # Raw files and padding have no sections: they are bytes and nothing else.
        if kind not in (0x01, 0xF0):
            entry.sections = read_sections(body, entry.offset + header_length)
        files.append(entry)

        position += size
        position = (position + 7) & ~7             # files are aligned to 8
    return files


# ------------------------------------------------------------------ walking

def all_sections(sections):
    """Every section, including those inside compressed ones, depth first."""
    for section in sections:
        yield section
        for inner in all_sections(section.children):
            yield inner


def nested_volumes(sections):
    """The UEFI volumes held inside sections of type "volume"."""
    import volumes
    found = []
    for section in all_sections(sections):
        if section.kind == SECTION_VOLUME:
            for volume in volumes.find_volumes(section.data):
                found.append(volume)
    return found
