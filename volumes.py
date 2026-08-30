# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the UEFI volumes inside a raw BIOS image.

A BC-250 image is 16 MiB of mixed content: PSP directory, SMU firmware, ABL,
the APCB memory configuration block, and - in only three places - the UEFI
volumes that hold the menus. No general tool recognises the whole image
(uefi-firmware-parser answers "could not detect firmware type"), so the volumes
have to be cut out first.

WARNING: the cut is NOT made with hand-written offsets. We have already watched
them change between two versions of the modified BIOS (v2.1 ended at 0xC23000,
v3 reaches 0xC2BDAB), and a stale offset silently cuts a volume in half. Here
the volumes are searched for every time, by signature.

The '_FVH' signature sits 40 bytes into the volume header, so the header starts
40 bytes BEFORE where the signature is found.
"""
from __future__ import unicode_literals

import struct

SIGNATURE = b"_FVH"
SIGNATURE_OFFSET = 40          # where the signature sits inside the header

# The file systems we may meet. The description is only there to make it
# readable for a human: what matters is telling FFS3 - which allows large
# files, with a 64-bit size - apart from the others.
FILE_SYSTEMS = {
    "7A9354D9-0468-444A-81CE-0BF617D890DF": ("ffs1", "UEFI FFS v1 file system"),
    "8C8CE578-8A3D-4F1C-9935-896185C32DD3": ("ffs2", "UEFI FFS v2 file system"),
    "5473C07A-3DCB-4DCA-BD6F-1E9689E7349A": ("ffs3", "UEFI FFS v3 file system"),
    "FFF12B8D-7696-4C8B-A985-2747075B4F50": ("nvram", "UEFI variables (NVRAM)"),
}


def guid_string(data):
    """The 16 bytes of a GUID in the form documentation uses.

    WARNING: the first three fields are little-endian and the last two are not:
    that is Microsoft's format, not a transcription mistake. Getting it wrong
    means searching the internet for a GUID that does not exist.
    """
    first, second, third = struct.unpack_from("<IHH", data, 0)
    return "%08X-%04X-%04X-%s-%s" % (
        first, second, third,
        data[8:10].hex().upper(),
        data[10:16].hex().upper(),
    )


class Volume(object):
    """A UEFI volume found inside the image.

    `data` is the exact slice of the volume: it is handed to ffs.py as is.
    """

    def __init__(self, offset, data, file_system_guid, attributes,
                 header_length, ext_header_offset, revision, blocks):
        self.offset = offset
        self.data = data
        self.file_system_guid = file_system_guid
        self.attributes = attributes
        self.header_length = header_length
        self.ext_header_offset = ext_header_offset
        self.revision = revision
        self.blocks = blocks

    @property
    def size(self):
        return len(self.data)

    @property
    def kind(self):
        return FILE_SYSTEMS.get(self.file_system_guid, ("unknown", ""))[0]

    @property
    def description(self):
        known = FILE_SYSTEMS.get(self.file_system_guid)
        return known[1] if known else "unrecognised file system"

    @property
    def erase_polarity(self):
        """1 when erased flash reads as 0xFF (the EFI_FVB2_ERASE_POLARITY bit).

        It is needed to read the state byte of each file: with polarity 1 the
        state bits are inverted, and a valid file looks erased if that is not
        taken into account.
        """
        return 1 if (self.attributes & 0x800) else 0

    def __repr__(self):
        return "<Volume 0x%08X %d bytes %s>" % (self.offset, self.size, self.kind)


def _read_header(image, start):
    """Read and validate a volume header. Returns None when it does not add up."""
    if start + 56 > len(image):
        return None
    length = struct.unpack_from("<Q", image, start + 32)[0]
    header_length, checksum, ext_offset = struct.unpack_from("<HHH", image, start + 48)
    revision = image[start + 55]

    # A volume longer than what is left of the image, or of length zero, is a
    # signature that turned up by chance inside arbitrary data.
    if length == 0 or start + length > len(image):
        return None
    if header_length < 56 or header_length > length:
        return None

    # The header checksum is the 16-bit sum of the whole header and must come
    # out zero. It is the check that tells a real volume from a coincidence.
    words = struct.unpack_from("<%dH" % (header_length // 2), image, start)
    if (sum(words) & 0xFFFF) != 0:
        return None

    blocks = []
    position = start + 56
    while position + 8 <= start + header_length:
        count, size = struct.unpack_from("<II", image, position)
        position += 8
        if count == 0 and size == 0:
            break
        blocks.append((count, size))

    return Volume(
        offset=start,
        data=image[start:start + length],
        file_system_guid=guid_string(image[start + 16:start + 32]),
        attributes=struct.unpack_from("<I", image, start + 44)[0],
        header_length=header_length,
        ext_header_offset=ext_offset,
        revision=revision,
        blocks=blocks,
    )


def find_volumes(image):
    """Every UEFI volume in the image, first to last.

    Nested volumes are not returned: when the signature falls inside a volume
    already found it is skipped, because that volume will be opened by ffs.py,
    which also knows how to decompress it. Only the top level matters here.
    """
    volumes = []
    end_of_last = 0
    position = 0
    while True:
        found = image.find(SIGNATURE, position)
        if found < 0:
            break
        position = found + 4
        start = found - SIGNATURE_OFFSET
        if start < 0 or start < end_of_last:
            continue
        volume = _read_header(image, start)
        if volume is None:
            continue
        volumes.append(volume)
        end_of_last = start + volume.size
    return volumes


def read_image(path):
    with open(path, "rb") as image_file:
        return image_file.read()
