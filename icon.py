# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the program icon without depending on any graphics library.

    python icon.py

Writes `emulator.ico`. The drawing follows the theme: the same slate frame as
the BIOS programmer - they are two programs of the same project - and inside it
three menu entries, the last one GREYED OUT, which is what this program does:
show the entries the firmware hides as well. It is redrawn at every size rather
than scaling a single image, so it stays legible at 16 px.

WARNING: Pillow is not needed: the ICO format is written by hand (BMP entries
for the small sizes, one PNG entry for 256, compressed with zlib from the
standard library).
"""
from __future__ import unicode_literals

import struct
import zlib

INK = (0x0B, 0x11, 0x19)
BORDER = (0x24, 0x32, 0x3F)
ACCENT = (0x2F, 0x9B, 0xE0)
ACCENT2 = (0x00, 0x70, 0xB0)
AMBER = (0xC9, 0xA2, 0x27)
HIDDEN = (0x4A, 0x5C, 0x6B)     # the grey of the entries the BIOS hides
DARK = (0x08, 0x13, 0x1C)

SIZES = (16, 32, 48, 64)
SUPERSAMPLE = 4          # oversampling, for edges that are not jagged


class Canvas(object):
    """A plain RGBA canvas: fills, rectangles and rounded corners."""

    def __init__(self, side):
        self.side = side
        self.pixels = [[(0, 0, 0, 0)] * side for _ in range(side)]

    def rectangle(self, x0, y0, x1, y1, colour, radius=0):
        red, green, blue = colour
        for y in range(max(0, int(y0)), min(self.side, int(y1) + 1)):
            for x in range(max(0, int(x0)), min(self.side, int(x1) + 1)):
                if radius:
                    # nothing is drawn outside the corner arcs
                    for cx, cy in ((x0 + radius, y0 + radius),
                                   (x1 - radius, y0 + radius),
                                   (x0 + radius, y1 - radius),
                                   (x1 - radius, y1 - radius)):
                        inside_x = (x < x0 + radius) if cx < (x0 + x1) / 2 \
                            else (x > x1 - radius)
                        inside_y = (y < y0 + radius) if cy < (y0 + y1) / 2 \
                            else (y > y1 - radius)
                        if inside_x and inside_y:
                            if (x - cx) ** 2 + (y - cy) ** 2 > radius ** 2:
                                break
                    else:
                        self.pixels[y][x] = (red, green, blue, 255)
                    continue
                self.pixels[y][x] = (red, green, blue, 255)

    def shrink(self, factor):
        """Average every factor x factor square: that is the antialiasing."""
        side = self.side // factor
        small = Canvas(side)
        for y in range(side):
            for x in range(side):
                red = green = blue = alpha = 0
                for dy in range(factor):
                    for dx in range(factor):
                        pr, pg, pb, pa = self.pixels[y * factor + dy][x * factor + dx]
                        red += pr * pa
                        green += pg * pa
                        blue += pb * pa
                        alpha += pa
                count = factor * factor
                if alpha:
                    small.pixels[y][x] = (red // alpha, green // alpha,
                                          blue // alpha, alpha // count)
                else:
                    small.pixels[y][x] = (0, 0, 0, 0)
        return small


def draw(side):
    """The mark, redrawn at the requested size."""
    big = Canvas(side * SUPERSAMPLE)
    length = side * SUPERSAMPLE
    unit = length / 64.0               # unit: the drawing is designed on 64

    big.rectangle(0, 0, length - 1, length - 1, INK, radius=int(10 * unit))
    big.rectangle(int(1 * unit), int(1 * unit), length - 1 - int(1 * unit),
                  length - 1 - int(1 * unit), BORDER, radius=int(9 * unit))
    big.rectangle(int(2 * unit), int(2 * unit), length - 1 - int(2 * unit),
                  length - 1 - int(2 * unit), INK, radius=int(8 * unit))

    # Three menu entries, of different lengths so that at 16 px it reads as a
    # list and not as three identical bars. The last one is grey: the hidden
    # entry.
    entries = ((18, 50, ACCENT), (30, 44, AMBER), (42, 34, HIDDEN))
    for y, end, colour in entries:
        big.rectangle(int(14 * unit), int(y * unit), int(end * unit),
                      int((y + 5) * unit), colour, radius=int(2 * unit))
    return big.shrink(SUPERSAMPLE)


# ------------------------------------------------------------------ formats

def _bmp_entry(canvas):
    """One ICO entry as a 32-bit BMP, rows bottom-up."""
    side = canvas.side
    header = struct.pack("<IiiHHIIiiII", 40, side, side * 2, 1, 32, 0,
                         side * side * 4, 0, 0, 0, 0)
    body = bytearray()
    for y in range(side - 1, -1, -1):
        for x in range(side):
            red, green, blue, alpha = canvas.pixels[y][x]
            body += bytes((blue, green, red, alpha))
    mask = bytearray()
    row = ((side + 31) // 32) * 4
    mask += bytes(row * side)
    return header + bytes(body) + bytes(mask)


def _png_entry(canvas):
    """One ICO entry as a PNG: allowed from Vista on, and for 256 it is the
    only sensible way."""
    side = canvas.side
    raw = bytearray()
    for y in range(side):
        raw.append(0)                  # filter "none"
        for x in range(side):
            red, green, blue, alpha = canvas.pixels[y][x]
            raw += bytes((red, green, blue, alpha))

    def chunk(name, data):
        block = name + data
        return struct.pack(">I", len(data)) + block + \
            struct.pack(">I", zlib.crc32(block) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def write(path="emulator.ico"):
    images = []
    for side in SIZES:
        images.append((side, _bmp_entry(draw(side))))
    images.append((256, _png_entry(draw(256))))

    head = struct.pack("<HHH", 0, 1, len(images))
    offset = len(head) + 16 * len(images)
    entries, bodies = b"", b""
    for side, data in images:
        entries += struct.pack("<BBBBHHII", side & 0xFF, side & 0xFF, 0, 0, 1, 32,
                               len(data), offset)
        bodies += data
        offset += len(data)
    with open(path, "wb") as icon_file:
        icon_file.write(head + entries + bodies)
    return path


if __name__ == "__main__":
    import os
    written = write(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "emulator.ico"))
    print("wrote %s (%d bytes)" % (written, os.path.getsize(written)))
