# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""The tabs the setup engine really shows, read out of AMITSE.

The IFR says which forms exist and how they link to each other. It does NOT say
which of them become the tabs across the top of the screen: that list lives in
the .data section of AMITSE, the AMI Text Setup Engine, as a table of
(form set GUID, form number) pairs.

WHY THIS MATTERS, and it is not a detail. On the stock BC-250 the table reads

    Main, Advanced, Security, Boot, Save & Exit

while the IFR has six forms hanging off the main one, Chipset among them. The
CHIPSETMENU mod changes ONE BYTE in that table - 10004 becomes 10003 - and the
third tab stops being Security and becomes Chipset. That is the whole trick:
the entry that leads to the chipset menu is still hidden by a suppressif TRUE
in the IFR, and it still would be, but the tab does not go through the IFR at
all.

So a view that builds its tab bar from the IFR shows a menu the board does not
have. This module reads the real list, and the difference between the two is
itself worth showing: it tells you what a modified firmware actually changed.

WARNING: this is a data table, not code, and it is read by pattern - the form
set GUID followed by a 16-bit form number, repeating every 32 bytes. That
matches every BC-250 image we have, stock and modified, but it is a shape we
inferred rather than a documented structure. When it does not match, the caller
falls back to the IFR and says so.
"""
from __future__ import unicode_literals

import struct

import ffs
import volumes

TSE_NAME = "AMITSE"
STRIDE = 32                 # the table advances 32 bytes per entry


def _tse_image(image):
    """The PE32 of the setup engine, found by its own module name."""
    for volume in volumes.find_volumes(image):
        if volume.kind == "nvram":
            continue
        top = ffs.read_files(volume)
        containers = [volume] + ffs.nested_volumes(
            [section for entry in top for section in entry.sections])
        for container in containers:
            for entry in ffs.read_files(container):
                name, code = None, None
                for section in ffs.all_sections(entry.sections):
                    if section.kind == 0x15:
                        name = section.data.decode("utf-16-le", "replace").split("\x00")[0]
                    elif section.kind == ffs.SECTION_PE32:
                        code = section.data
                if name == TSE_NAME and code:
                    return code
    return None


def tab_form_ids(image, formset_guid):
    """The form numbers AMITSE shows as tabs for that form set, in order.

    Returns an empty list when the table cannot be found: the caller then falls
    back to what the IFR links to, which is a reasonable guess but only that.
    """
    code = _tse_image(image)
    if not code:
        return []
    wanted = formset_guid.upper()
    found = []
    position = 0
    limit = len(code) - 18
    while position < limit:
        if volumes.guid_string(code[position:position + 16]) == wanted:
            number = struct.unpack_from("<H", code, position + 16)[0]
            found.append((position + 16, number))
            position += STRIDE
            continue
        position += 1
    # The last pair usually points at the form set's own main form, which is
    # not a tab but the page holding them: it is dropped by the caller if it
    # turns out to be the main form.
    return [number for _offset, number in found]


def tab_table(image, formset_guid):
    """The same list with the file offsets, for whoever wants to patch it.

    Knowing that the third tab of the BC-250 lives at offset 0x0452E0 of
    AMITSE, and that writing 10003 there puts Chipset where Security was, is
    the kind of thing that belongs in a note rather than in somebody's memory.
    """
    code = _tse_image(image)
    if not code:
        return []
    wanted = formset_guid.upper()
    found = []
    position = 0
    limit = len(code) - 18
    while position < limit:
        if volumes.guid_string(code[position:position + 16]) == wanted:
            number = struct.unpack_from("<H", code, position + 16)[0]
            found.append((position + 16, number))
            position += STRIDE
            continue
        position += 1
    return found
