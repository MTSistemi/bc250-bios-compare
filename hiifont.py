# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""The setup font, taken out of the firmware image itself.

The BIOS does not draw its menu with a font from your machine: it carries its
own, as an HII Simple Font package - a bitmap glyph per character, 8 pixels
wide and 19 tall. Reading those glyphs is the difference between a screen that
resembles the setup and one that is drawn with the very same letters.

There are two font packages in the stock BC-250 image: 242 narrow glyphs in one
driver, 148 plus 2 wide ones in another. We take the richest one and fall back
to the other for anything it does not carry.

THE FORMAT (UEFI spec, EFI_HII_SIMPLE_FONT_PACKAGE_HDR)
    header      4 bytes   length in the low 24 bits, type 0x07 in the high 8
    narrow      2 bytes   how many narrow glyphs
    wide        2 bytes   how many wide glyphs
    then, for every narrow glyph, 22 bytes:
        UnicodeWeight  2 bytes   the character it stands for
        Attributes     1 byte
        GlyphCol1     19 bytes   one byte per row, bit 7 is the leftmost pixel

WARNING: the rows are bytes read most significant bit first. Reading them the
other way round produces glyphs that are mirror images - and mirrored text on a
screen full of frame characters looks like a rendering bug somewhere else
entirely.
"""
from __future__ import unicode_literals

import struct

PACKAGE_SIMPLE_FONT = 0x07
GLYPH_WIDTH = 8
GLYPH_HEIGHT = 19
NARROW_GLYPH_SIZE = 22


class Font(object):
    """The glyphs of one font package, by character."""

    def __init__(self, glyphs, source=""):
        self.glyphs = glyphs            # codepoint -> list of 19 ints (bit rows)
        self.source = source

    def __len__(self):
        return len(self.glyphs)

    def rows(self, character):
        """The 19 rows of a character, or the ones of a space when unknown."""
        code = ord(character)
        rows = self.glyphs.get(code)
        if rows is not None:
            return rows
        # Frame characters are the ones most often missing: the firmware draws
        # its boxes with them, but a font that lacks them must not make the
        # whole screen collapse. A blank is a poor box; a traceback is worse.
        return self.glyphs.get(0x20, [0] * GLYPH_HEIGHT)

    def merged_with(self, other):
        """This font, completed with whatever the other one has and we lack."""
        glyphs = dict(other.glyphs)
        glyphs.update(self.glyphs)
        return Font(glyphs, self.source)


def _read_package(data, start):
    """Read one simple font package. Returns a Font or None."""
    length = struct.unpack_from("<I", data, start)[0] & 0xFFFFFF
    narrow, wide = struct.unpack_from("<HH", data, start + 4)
    expected = 8 + narrow * NARROW_GLYPH_SIZE + wide * NARROW_GLYPH_SIZE * 2
    if not narrow or abs(expected - length) > 8 or start + length > len(data):
        return None
    glyphs = {}
    position = start + 8
    for _ in range(narrow):
        if position + NARROW_GLYPH_SIZE > len(data):
            break
        code = struct.unpack_from("<H", data, position)[0]
        rows = list(data[position + 3:position + 3 + GLYPH_HEIGHT])
        glyphs[code] = rows
        position += NARROW_GLYPH_SIZE
    return Font(glyphs) if glyphs else None


def find_fonts(image):
    """Every simple font package in the image, richest first."""
    import hii
    fonts = []
    for file_guid, _section, data in hii._blocks_to_scan(image):
        limit = len(data) - 8
        position = 0
        while position < limit:
            if data[position + 3] != PACKAGE_SIMPLE_FONT:
                position += 1
                continue
            font = _read_package(data, position)
            if font is None:
                position += 1
                continue
            font.source = file_guid
            fonts.append(font)
            position += struct.unpack_from("<I", data, position)[0] & 0xFFFFFF
    fonts.sort(key=len, reverse=True)
    return fonts


def load(image):
    """The font to draw the setup with: the richest package, filled in from the
    others. Returns None when the image carries no font at all - in that case
    the caller falls back to a monospaced screen font."""
    fonts = find_fonts(image)
    if not fonts:
        return None
    font = fonts[0]
    for other in fonts[1:]:
        font = font.merged_with(other)
    return font


def as_text(font, character):
    """One glyph as rows of hashes and dots. For checking with the eye."""
    lines = []
    for row in font.rows(character):
        lines.append("".join("#" if row & (0x80 >> column) else "."
                             for column in range(GLYPH_WIDTH)))
    return "\n".join(lines)
