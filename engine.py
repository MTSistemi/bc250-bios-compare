# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""The engine: evaluating menu conditions against a state of the variables.

This is the part that separates this tool from a text extractor. Pulling the
lines out is something ifrextractor already does; answering "with IOMMU set to
Enabled, which entry shows up and which one greys out?" is not. Answering it
means doing what the firmware does at boot: take the value of the variables,
evaluate every SuppressIf and every GrayOutIf, and see what is left standing.

HOW A CONDITION IS EVALUATED
IFR expressions are in reverse polish notation: "A, 3, ==" instead of "A == 3".
You walk them in order, operands are pushed, operators consume them. At the end
a single value must be left on the stack.

WARNING - THREE-VALUED LOGIC, AND IT IS A CHOICE, NOT A GAP
Some operands cannot be computed without the firmware running: the value of a
question living in another form set, a call into BIOS code, a rule defined
elsewhere. In those cases nothing is guessed here: the result is UNKNOWN, and
it propagates. "False AND unknown" stays false (one of the two is enough),
"true AND unknown" becomes unknown. An entry with an unknown condition is
reported as such rather than declared visible: saying "I do not know" is the
only honest answer, and the real board will show who was right.
"""
from __future__ import unicode_literals

import struct

import ifr


class Unknown(object):
    """A value that cannot be computed without the firmware running."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Unknown, cls).__new__(cls)
        return cls._instance

    def __repr__(self):
        return "UNKNOWN"

    def __bool__(self):
        raise TypeError("an unknown value cannot be treated as true or false")

    __nonzero__ = __bool__


UNKNOWN = Unknown()

FORMATS = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}

# The UEFI standard defaults. 0 = "Standard Defaults", 1 = "Manufacturing".
STANDARD_DEFAULT = 0


# =================================================================== the state

class State(object):
    """The values of the variables the menu is evaluated against.

    There are three different starting points, and the difference matters:
      - the DEFAULTS written in the firmware: what the menu looks like on a
        freshly cleared board;
      - a REAL VARIABLE read from the board (/sys/firmware/efi/efivars): what
        the menu looks like right now, on that particular board;
      - from scratch, changing entries by hand: what the menu looks like if we
        make a given choice.
    """

    def __init__(self, formset):
        self.formset = formset
        self.buffers = {}
        for identifier, store in formset.varstores.items():
            self.buffers[identifier] = bytearray(store.size or 0)
        self._by_id = {}
        for question in formset.questions:
            if question.identifier:
                self._by_id.setdefault(question.identifier, question)

    # --- filling it in -----------------------------------------------------

    def apply_defaults(self, default_id=STANDARD_DEFAULT):
        """Put the firmware's declared default into every entry.

        When an entry has no Default opcode we look for an option flagged as
        the default; when there is not one of those either, zero is left and
        the entry counts as "no default", which is something to show rather
        than to hide.
        """
        without = []
        for question in self.formset.questions:
            value = question.defaults.get(default_id)
            if value is None:
                flagged = [option for option in question.options if option.is_default]
                value = flagged[0].value if flagged else None
            if value is None:
                without.append(question)
                continue
            try:
                self.set_value(question, value)
            except ValueError:
                # Entries with no varstore (Ref, Action) or as wide as a whole
                # buffer: there is no value to put anywhere.
                without.append(question)
        return without

    def load_variable(self, varstore_id, data):
        """Load the raw content of a UEFI variable.

        WARNING: the file in /sys/firmware/efi/efivars starts with 4 ATTRIBUTE
        bytes that are not part of the variable. They have to go, otherwise
        every offset shifts by four and the values read belong to a different
        entry. Here they are dropped automatically when the length adds up.
        """
        store = self.formset.varstores.get(varstore_id)
        expected = store.size if store else None
        if expected and len(data) == expected + 4:
            data = data[4:]
        if expected and len(data) != expected:
            raise ValueError(
                "the variable is %d bytes, the firmware declares %d: either it "
                "belongs to another BIOS, or it was truncated"
                % (len(data), expected))
        self.buffers[varstore_id] = bytearray(data)

    # --- reading and writing ----------------------------------------------

    def read(self, question):
        """The value of an entry, or UNKNOWN when it is not in a readable varstore."""
        store = question.varstore
        if store is None or store.identifier not in self.buffers:
            return UNKNOWN
        offset = question.offset
        width = question.width
        if offset is None or width not in FORMATS:
            return UNKNOWN
        data = self.buffers[store.identifier]
        if offset + width > len(data):
            return UNKNOWN
        return struct.unpack_from(FORMATS[width], data, offset)[0]

    def set_value(self, question, value):
        store = question.varstore
        if store is None or store.identifier not in self.buffers:
            raise ValueError("entry %r has no writable varstore" % question.text_label)
        width = question.width
        if width not in FORMATS:
            raise ValueError("entry %r is %d bytes wide: it is not written that way"
                             % (question.text_label, width))
        offset = question.offset
        data = self.buffers[store.identifier]
        if offset + width > len(data):
            raise ValueError("entry %r falls outside the variable" % question.text_label)
        struct.pack_into(FORMATS[width], data, offset, value & ((1 << (8 * width)) - 1))

    def read_bytes(self, question):
        """The raw bytes of an entry, whatever its width.

        String and password entries are not 1, 2, 4 or 8 bytes wide - they are
        as wide as the text they hold - so read() cannot serve them and they
        need the slice itself.
        """
        store = question.varstore
        if store is None or store.identifier not in self.buffers:
            return None
        offset, width = question.offset, question.width
        if offset is None or not width:
            return None
        data = self.buffers[store.identifier]
        if offset + width > len(data):
            return None
        return bytes(data[offset:offset + width])

    def write_bytes(self, question, payload):
        """Write raw bytes into an entry, padding or truncating to its width."""
        store = question.varstore
        if store is None or store.identifier not in self.buffers:
            raise ValueError("entry %r has no writable varstore" % question.text_label)
        offset, width = question.offset, question.width
        if offset is None or not width:
            raise ValueError("entry %r has nowhere to be written" % question.text_label)
        data = self.buffers[store.identifier]
        if offset + width > len(data):
            raise ValueError("entry %r falls outside the variable" % question.text_label)
        payload = (payload + b"\x00" * width)[:width]
        data[offset:offset + width] = payload

    def value_of_id(self, identifier):
        """The value of a question looked up by identifier (the IFR needs this)."""
        question = self._by_id.get(identifier)
        if question is None:
            return UNKNOWN
        return self.read(question)

    def copy(self):
        clone = State(self.formset)
        clone.buffers = {key: bytearray(value) for key, value in self.buffers.items()}
        return clone


# ======================================================= evaluating the stack

def _binary(operation, left, right):
    if left is UNKNOWN or right is UNKNOWN:
        return UNKNOWN
    try:
        return operation(left, right)
    except (TypeError, ZeroDivisionError):
        return UNKNOWN


def _logical_and(left, right):
    # One false is enough: the other one does not matter. That is what makes
    # three-valued logic useful instead of giving up at the first unknown.
    if left is False or right is False:
        return False
    if left is UNKNOWN or right is UNKNOWN:
        return UNKNOWN
    return bool(left) and bool(right)


def _logical_or(left, right):
    if left is True or right is True:
        return True
    if left is UNKNOWN or right is UNKNOWN:
        return UNKNOWN
    return bool(left) or bool(right)


def evaluate(nodes, state):
    """Evaluate a sequence of expression opcodes. Returns a value or UNKNOWN."""
    stack = []

    def take(how_many):
        if len(stack) < how_many:
            return None
        values = stack[-how_many:]
        del stack[-how_many:]
        return values

    for node in nodes:
        code = node.opcode

        # --- constants -----------------------------------------------------
        if code in (0x42, 0x43, 0x44, 0x45):
            stack.append(node.fields.get("value", 0))
        elif code == 0x46:
            stack.append(True)
        elif code == 0x47:
            stack.append(False)
        elif code == 0x52:
            stack.append(0)
        elif code == 0x53:
            stack.append(1)
        elif code == 0x54:
            stack.append(0xFFFFFFFFFFFFFFFF)
        elif code == 0x55:
            stack.append(UNKNOWN)

        # --- references to questions ---------------------------------------
        elif code == 0x40:                                    # QuestionRef1
            stack.append(state.value_of_id(node.fields.get("id", 0)))
        elif code in (0x41, 0x51, 0x58):                      # Ref2/Ref3/This
            stack.append(UNKNOWN)

        # --- comparisons written as a single opcode ------------------------
        elif code == 0x12:                                    # EqIdVal
            value = state.value_of_id(node.fields.get("id", 0))
            stack.append(UNKNOWN if value is UNKNOWN
                         else value == node.fields.get("value"))
        elif code == 0x13:                                    # EqIdId
            one = state.value_of_id(node.fields.get("id", 0))
            two = state.value_of_id(node.fields.get("id2", 0))
            stack.append(UNKNOWN if UNKNOWN in (one, two) else one == two)
        elif code == 0x14:                                    # EqIdValList
            value = state.value_of_id(node.fields.get("id", 0))
            stack.append(UNKNOWN if value is UNKNOWN
                         else value in node.fields.get("values", []))

        # --- logic ---------------------------------------------------------
        elif code == 0x15:                                    # And
            values = take(2)
            stack.append(UNKNOWN if values is None
                         else _logical_and(values[0], values[1]))
        elif code == 0x16:                                    # Or
            values = take(2)
            stack.append(UNKNOWN if values is None
                         else _logical_or(values[0], values[1]))
        elif code == 0x17:                                    # Not
            values = take(1)
            if values is None or values[0] is UNKNOWN:
                stack.append(UNKNOWN)
            else:
                stack.append(not bool(values[0]))

        # --- comparisons and arithmetic ------------------------------------
        elif code in _OPERATORS:
            values = take(2)
            stack.append(UNKNOWN if values is None
                         else _binary(_OPERATORS[code], values[0], values[1]))
        elif code == 0x37:                                    # BitwiseNot
            values = take(1)
            stack.append(UNKNOWN if values is None or values[0] is UNKNOWN
                         else ~values[0] & 0xFFFFFFFFFFFFFFFF)
        elif code == 0x50:                                    # Conditional
            values = take(3)
            if values is None or values[0] is UNKNOWN:
                stack.append(UNKNOWN)
            else:
                stack.append(values[1] if values[0] else values[2])

        else:
            # Get, Match, Token, RuleRef, string conversions...: things that
            # cannot be computed without the firmware running. UNKNOWN goes on
            # the stack and we carry on: three-valued logic does the rest.
            stack.append(UNKNOWN)

    if not stack:
        return UNKNOWN
    return stack[-1]


_OPERATORS = {
    0x2F: lambda a, b: a == b,
    0x30: lambda a, b: a != b,
    0x31: lambda a, b: a > b,
    0x32: lambda a, b: a >= b,
    0x33: lambda a, b: a < b,
    0x34: lambda a, b: a <= b,
    0x35: lambda a, b: a & b,
    0x36: lambda a, b: a | b,
    0x38: lambda a, b: a << b,
    0x39: lambda a, b: a >> b,
    0x3A: lambda a, b: a + b,
    0x3B: lambda a, b: a - b,
    0x3C: lambda a, b: a * b,
    0x3D: lambda a, b: a // b,
    0x3E: lambda a, b: a % b,
}


# ================================================================ visibility

class Verdict(object):
    """What happens to an entry with a given state of the variables."""

    def __init__(self):
        self.hidden = False            # SuppressIf or DisableIf came out true
        self.greyed = False            # GrayOutIf true: visible, not touchable
        self.uncertain = False         # at least one condition is UNKNOWN
        self.why = []                  # (condition name, outcome)

    @property
    def visible(self):
        return not self.hidden

    def __repr__(self):
        if self.uncertain:
            state = "uncertain"
        elif self.hidden:
            state = "hidden"
        elif self.greyed:
            state = "greyed"
        else:
            state = "visible"
        return "<%s>" % state


def verdict(question, state):
    """Evaluate every condition governing an entry."""
    result = Verdict()
    for name, node in question.conditions:
        expression, _contents = ifr.split_expression(node.children)
        outcome = evaluate(expression, state)
        result.why.append((name, outcome))
        if outcome is UNKNOWN:
            result.uncertain = True
            continue
        if not outcome:
            continue
        if name in ("SuppressIf", "DisableIf"):
            result.hidden = True
        elif name == "GrayOutIf":
            result.greyed = True
    return result


def visible_questions(formset, state):
    """The entries that would actually be visible with this state."""
    return [question for question in formset.questions
            if verdict(question, state).visible]


def differences(formset, before, after):
    """What changes in the menu going from one state to the other.

    This is the function everything else was written for: "if I set IOMMU to
    Enabled, which entry appears and which one greys out?" Returns
    (appeared, disappeared, ungreyed, greyed).
    """
    appeared, disappeared, ungreyed, greyed = [], [], [], []
    for question in formset.questions:
        was = verdict(question, before)
        now = verdict(question, after)
        if was.hidden and not now.hidden:
            appeared.append(question)
        elif not was.hidden and now.hidden:
            disappeared.append(question)
        if was.greyed and not now.greyed:
            ungreyed.append(question)
        elif not was.greyed and now.greyed:
            greyed.append(question)
    return appeared, disappeared, ungreyed, greyed
