# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""The explanation of a menu entry, built from two different sources.

WARNING - KEEPING THE TWO SOURCES APART IS THE POINT OF THIS MODULE, and they
must not be blurred together even to make the page look nicer:

  1. WHAT THE FIRMWARE SAYS. Where the value ends up, which options exist,
     which defaults, which conditions govern the entry, and - the part no other
     tool computes - WHICH OTHER ENTRIES change state if this one is changed.
     It is not opinion: it is read and computed from the image, and if it is
     wrong it is our bug to fix.

  2. WHAT WE KNOW. The hand-written cards in cards/<language>.json: what the
     parameter is for, what it does ON THE BC-250, what happened when we put
     our hands on it. They are few against 1134 entries, and where there is no
     card the program SAYS SO instead of filling the gap with a generic
     sentence. An invented explanation of a firmware parameter is not a
     service: it is a way of making someone else spend an afternoon working out
     why their board no longer boots.

Cards are matched by exact entry name, by name prefix, or by a fragment of the
name: the eight "GRA Group N" entries and the dozens of "... Clock Gating" ones
share a single explanation, and repeating it eight times would mean correcting
it in eight places.
"""
from __future__ import unicode_literals

import io
import json
import os
import sys

import engine
import ifr
import languages

# As in languages.py: inside the frozen executable the resources live in
# _MEIPASS, not next to the source file.
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
CARDS_DIR = os.path.join(HERE, "cards")

_cards = {}


def _load_cards(code):
    if code in _cards:
        return _cards[code]
    path = os.path.join(CARDS_DIR, "%s.json" % code)
    data = {"exact": {}, "families": []}
    try:
        with io.open(path, encoding="utf-8") as cards_file:
            loaded = json.load(cards_file)
        if isinstance(loaded, dict):
            data = {"exact": loaded.get("exact", {}) or {},
                    "families": loaded.get("families", []) or []}
    except Exception:                                      # noqa: BLE001
        pass
    _cards[code] = data
    return data


def card(entry_name, code=None):
    """Our hand-written card for this entry, and which language it came out in.

    Returns (text, language) or (None, None). The language lets the window say
    "this card is not translated yet": showing English without warning would
    make the translation look accidentally missing, and the reader would not
    know how much to trust it.
    """
    code = code or languages.current()
    # WARNING: entry names carry the menu's own indentation - AMI writes
    # "  IOHC CG Hysteresis", with two leading spaces, to show nesting. Without
    # stripping them a prefix family matches nothing and thirty-one entries
    # look as if we had never written a card for them.
    trimmed = entry_name.strip()
    name = trimmed.lower()
    for attempt in (code, "en"):
        data = _load_cards(attempt)
        text = data["exact"].get(entry_name) or data["exact"].get(trimmed)
        if text:
            return text, attempt
        for family in data["families"]:
            # "starts_with" matches a PREFIX, "contains" matches anywhere in
            # the name. The prefix is for numbered families - the GDDR6 mode
            # registers run from MR0 to MR8 and are sixty entries sharing one
            # explanation - where a loose fragment would also catch entries
            # that have nothing to do with them.
            prefix = family.get("starts_with", "")
            if prefix and name.startswith(prefix.lower()):
                return family.get("text", ""), attempt
            fragment = family.get("contains", "")
            if fragment and fragment.lower() in name:
                return family.get("text", ""), attempt
    return None, None


# --------------------------------------------------- what depends on what

_indexes = {}


def _condition_index(formset):
    """How many conditions mention each entry. Saves computing for nothing.

    Simulating a change costs one pass over all 1193 entries of the form set:
    doing that for an entry no condition names is wasted time, and on a window
    that has to answer a click it shows.
    """
    key = id(formset)
    if key in _indexes:
        return _indexes[key]
    mentioned = {}
    for question in formset.questions:
        for _name, node in question.conditions:
            expression, _ = ifr.split_expression(node.children)
            for opcode in expression:
                identifier = opcode.fields.get("id")
                if identifier is not None and opcode.opcode in (0x12, 0x13, 0x14,
                                                                0x40, 0x51):
                    mentioned[identifier] = mentioned.get(identifier, 0) + 1
                if opcode.opcode == 0x13:
                    other = opcode.fields.get("id2")
                    if other is not None:
                        mentioned[other] = mentioned.get(other, 0) + 1
    _indexes[key] = mentioned
    return mentioned


def controls(formset, question, state):
    """What happens to the other entries when this one is changed.

    Returns a list of (value, value text, appeared, disappeared, ungreyed,
    greyed), one row per possible option. An empty list when this entry appears
    in no condition: in that case it governs nothing, and that is a certain
    answer, not an "I do not know".
    """
    if not question.identifier:
        return []
    if not _condition_index(formset).get(question.identifier):
        return []
    if not question.options or question.varstore is None:
        return []

    results = []
    current = state.read(question)
    for option in question.options:
        if option.value == current:
            continue
        trial = state.copy()
        try:
            trial.set_value(question, option.value)
        except ValueError:
            continue
        appeared, disappeared, ungreyed, greyed = engine.differences(
            formset, state, trial)
        if appeared or disappeared or ungreyed or greyed:
            results.append((option.value, option.text,
                            appeared, disappeared, ungreyed, greyed))
    return results


# ------------------------------------------------------ conditions in words

def describe_condition(name, node, outcome):
    """One IFR condition put into a sentence, with the outcome right now.

    The case that matters is the first one: a condition that names no variable
    is a bricked-up door, not a locked one, and the reader has to understand
    the difference before going looking for which variable to write.
    """
    expression, _ = ifr.split_expression(node.children)
    text = ifr.describe_expression(expression)
    # WARNING: a constant condition is not always the True opcode. The VFR
    # compiler also writes Uint64(1), which is just as true. Above 4G Decoding
    # is bricked up exactly that way. Checking "outcome is True" instead of the
    # truth of the value let that case through as if it were an ordinary
    # condition - that is, a locked door instead of a walled-up one.
    only_constants = bool(expression) and all(
        opcode.opcode in (0x46, 0x47, 0x42, 0x43, 0x44, 0x45, 0x52, 0x53, 0x54)
        for opcode in expression)
    is_true = outcome is not engine.UNKNOWN and bool(outcome)
    return {
        "name": name,
        "expression": text,
        "constant": only_constants and is_true,
        "outcome": outcome,
    }


def conditions(question, state):
    out = []
    for name, node in question.conditions:
        expression, _ = ifr.split_expression(node.children)
        out.append(describe_condition(name, node, engine.evaluate(expression, state)))
    return out


# --------------------------------------------------------- ready-made commands

def read_command(question):
    store = question.varstore
    if store is None:
        return None
    return ('ssh root@board "base64 -w0 /sys/firmware/efi/efivars/%s"'
            ' | base64 -d > %s.bin' % (store.variable_name, store.name))


def write_command(question, value):
    """How that byte would be written, if we ever decided to try.

    WARNING: the WHOLE variable is written, not the byte: efivarfs wants the
    write in one go, attributes included. A dd on the single byte does not work
    and can leave the variable half written.
    """
    store = question.varstore
    if store is None or question.offset is None or not question.width:
        return None
    return (
        "# 1. read the whole variable, attributes included\n"
        "cp /sys/firmware/efi/efivars/%s /tmp/var.bin\n"
        "# 2. change the %d bytes at offset 0x%X (+4 for the attributes)\n"
        "python3 - <<'END'\n"
        "import struct\n"
        "d = bytearray(open('/tmp/var.bin','rb').read())\n"
        "struct.pack_into('<%s', d, 4 + 0x%X, %s)\n"
        "open('/tmp/var.bin','wb').write(d)\n"
        "END\n"
        "# 3. write it back in one go\n"
        "chattr -i /sys/firmware/efi/efivars/%s\n"
        "cp /tmp/var.bin /sys/firmware/efi/efivars/%s"
        % (store.variable_name, question.width, question.offset,
           {1: "B", 2: "H", 4: "I", 8: "Q"}.get(question.width, "B"),
           question.offset, value,
           store.variable_name, store.variable_name))
