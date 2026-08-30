# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""IFR: the opcodes a UEFI BIOS menu is written in, read as a tree.

A UEFI BIOS menu is not code that draws windows: it is a data structure (IFR,
Internal Forms Representation) that the firmware interprets at run time. Every
entry, every "show this only if..." condition, every default value is an opcode
with fields.

Here the IFR becomes a TREE OF OBJECTS, not a list of text lines. That is the
difference between this emulator and ifrextractor: with lines you can read the
menu, with objects you can EVALUATE it (see engine.py) and put it back together
(see the forge, still to be written).

TWO THINGS TO KNOW BEFORE READING THE CODE

1. The tree is made out of one bit. The second byte of every opcode is the
   length in the low 7 bits plus the 0x80 "scope" bit: when it is set,
   everything that follows is a child until an END opcode (0x29). There are no
   pointers: you read in order and keep a stack.

2. Conditions are in reverse polish notation. Inside a SuppressIf there is no
   "A == 3", there is "A, 3, ==": operands are pushed and operators consume
   them. WARNING: and the expression is not delimited - it ends at the first
   opcode that is not an expression opcode. Getting that boundary wrong means
   taking the first menu entry that follows for part of the condition.
"""
from __future__ import unicode_literals

import struct

from volumes import guid_string

END_OP = 0x29                   # EFI_IFR_END_OP

# --- opcode names ----------------------------------------------------------
NAMES = {
    0x01: "Form", 0x02: "Subtitle", 0x03: "Text", 0x04: "Image",
    0x05: "OneOf", 0x06: "CheckBox", 0x07: "Numeric", 0x08: "Password",
    0x09: "OneOfOption", 0x0A: "SuppressIf", 0x0B: "Locked", 0x0C: "Action",
    0x0D: "ResetButton", 0x0E: "FormSet", 0x0F: "Ref", 0x10: "NoSubmitIf",
    0x11: "InconsistentIf", 0x12: "EqIdVal", 0x13: "EqIdId",
    0x14: "EqIdValList", 0x15: "And", 0x16: "Or", 0x17: "Not", 0x18: "Rule",
    0x19: "GrayOutIf", 0x1A: "Date", 0x1B: "Time", 0x1C: "String",
    0x1D: "Refresh", 0x1E: "DisableIf", 0x1F: "Animation", 0x20: "ToLower",
    0x21: "ToUpper", 0x22: "Map", 0x23: "OrderedList", 0x24: "VarStore",
    0x25: "VarStoreNameValue", 0x26: "VarStoreEfi", 0x27: "VarStoreDevice",
    0x28: "Version", 0x29: "End", 0x2A: "Match", 0x2B: "Get", 0x2C: "Set",
    0x2D: "Read", 0x2E: "Write", 0x2F: "Equal", 0x30: "NotEqual",
    0x31: "GreaterThan", 0x32: "GreaterEqual", 0x33: "LessThan",
    0x34: "LessEqual", 0x35: "BitwiseAnd", 0x36: "BitwiseOr",
    0x37: "BitwiseNot", 0x38: "ShiftLeft", 0x39: "ShiftRight", 0x3A: "Add",
    0x3B: "Subtract", 0x3C: "Multiply", 0x3D: "Divide", 0x3E: "Modulo",
    0x3F: "RuleRef", 0x40: "QuestionRef1", 0x41: "QuestionRef2",
    0x42: "Uint8", 0x43: "Uint16", 0x44: "Uint32", 0x45: "Uint64",
    0x46: "True", 0x47: "False", 0x48: "ToUint", 0x49: "ToString",
    0x4A: "ToBoolean", 0x4B: "Mid", 0x4C: "Find", 0x4D: "Token",
    0x4E: "StringRef1", 0x4F: "StringRef2", 0x50: "Conditional",
    0x51: "QuestionRef3", 0x52: "Zero", 0x53: "One", 0x54: "Ones",
    0x55: "Undefined", 0x56: "Length", 0x57: "Dup", 0x58: "This",
    0x59: "Span", 0x5A: "Value", 0x5B: "Default", 0x5C: "DefaultStore",
    0x5D: "FormMap", 0x5E: "Catenate", 0x5F: "Guid", 0x60: "Security",
    0x61: "ModalTag", 0x62: "RefreshId", 0x63: "WarningIf", 0x64: "Match2",
}

# The opcodes that are part of an expression. This is what tells us where the
# condition of a SuppressIf ends and what it hides begins.
# WARNING: Rule (0x18), Value (0x5A) and Default (0x5B) are NOT here: they are
# not expressions, they are containers that hold one.
EXPRESSION_OPS = frozenset(
    list(range(0x12, 0x18)) +      # EqIdVal..Not
    list(range(0x20, 0x23)) +      # ToLower, ToUpper, Map
    list(range(0x2A, 0x52)) +      # Match..QuestionRef3, operators, constants
    list(range(0x52, 0x5A)) +      # Zero..Span
    [0x5E, 0x64]                   # Catenate, Match2
)

# The conditions: scoped opcodes whose expression governs their children.
CONDITIONS = {0x0A: "SuppressIf", 0x19: "GrayOutIf", 0x1E: "DisableIf",
              0x10: "NoSubmitIf", 0x11: "InconsistentIf", 0x63: "WarningIf"}

# The entries a user can give a value to.
QUESTIONS = {0x05: "OneOf", 0x06: "CheckBox", 0x07: "Numeric", 0x08: "Password",
             0x1C: "String", 0x23: "OrderedList", 0x1A: "Date", 0x1B: "Time",
             0x0C: "Action", 0x0F: "Ref", 0x0D: "ResetButton"}

# The value types (EFI_IFR_TYPE_*), with how many bytes they take.
VALUE_TYPES = {0x00: ("uint8", 1), 0x01: ("uint16", 2), 0x02: ("uint32", 4),
               0x03: ("uint64", 8), 0x04: ("boolean", 1), 0x05: ("time", 3),
               0x06: ("date", 4), 0x07: ("string", 2), 0x08: ("other", 0),
               0x09: ("undefined", 0), 0x0A: ("action", 2), 0x0B: ("buffer", 0),
               0x0C: ("ref", 0)}

# The width of a question's data, from the low two bits of its flags.
WIDTHS = {0: 1, 1: 2, 2: 4, 3: 8}


class Node(object):
    """One opcode with its fields already read and its children attached."""

    def __init__(self, opcode, offset, length, scope, body):
        self.opcode = opcode
        self.offset = offset            # position inside the form package
        self.length = length            # header included
        self.scope = scope
        self.body = body                # bytes after the 2 header ones
        self.children = []
        self.parent = None
        self.fields = {}                # filled in by _read_fields

    @property
    def name(self):
        return NAMES.get(self.opcode, "Opcode0x%02X" % self.opcode)

    @property
    def is_question(self):
        return self.opcode in QUESTIONS

    @property
    def is_condition(self):
        return self.opcode in CONDITIONS

    def descendants(self):
        for child in self.children:
            yield child
            for inner in child.descendants():
                yield inner

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def __repr__(self):
        return "<%s @0x%X %d children>" % (self.name, self.offset, len(self.children))


# ------------------------------------------------------------ reading fields

def _ascii_string(body, start):
    end = body.find(b"\0", start)
    if end < 0:
        end = len(body)
    return body[start:end].decode("ascii", "replace")


def _typed_value(body, start, kind):
    """Read a typed value. Returns (value, bytes consumed)."""
    _name, width = VALUE_TYPES.get(kind, ("unknown", 0))
    if width == 0 or start + width > len(body):
        return None, 0
    if width == 1:
        return body[start], 1
    fmt = {2: "<H", 3: None, 4: "<I", 8: "<Q"}.get(width)
    if fmt is None:                           # time: hours, minutes, seconds
        return tuple(body[start:start + 3]), 3
    return struct.unpack_from(fmt, body, start)[0], width


def _question_header(node):
    """The fields every question shares: prompt, help, id, varstore, offset.

    EFI_IFR_QUESTION_HEADER is always the same and always comes first: 11
    bytes. `varstore_info` is the OFFSET inside the variable when the varstore
    is a buffer - exactly the number we need to reach the right byte inside
    AmdSetup.
    """
    body = node.body
    if len(body) < 11:
        return
    prompt, help_id, question_id, varstore, info = struct.unpack_from("<HHHHH", body, 0)
    node.fields.update({
        "prompt": prompt, "help": help_id, "id": question_id,
        "varstore": varstore, "varstore_info": info, "question_flags": body[10],
    })


def _read_fields(node):
    """Fill node.fields according to the kind of opcode."""
    body = node.body
    code = node.opcode

    if code == 0x0E:                                      # FormSet
        if len(body) >= 21:
            node.fields["guid"] = guid_string(body[:16])
            title, help_id = struct.unpack_from("<HH", body, 16)
            node.fields.update({"title": title, "help": help_id,
                                "flags": body[20]})
            class_guids = []
            how_many = body[20] & 0x03
            for index in range(how_many):
                start = 21 + index * 16
                if start + 16 <= len(body):
                    class_guids.append(guid_string(body[start:start + 16]))
            node.fields["class_guids"] = class_guids

    elif code == 0x01:                                    # Form
        if len(body) >= 4:
            form_id, title = struct.unpack_from("<HH", body, 0)
            node.fields.update({"id": form_id, "title": title})

    elif code == 0x5D:                                    # FormMap
        if len(body) >= 2:
            node.fields["id"] = struct.unpack_from("<H", body, 0)[0]
            node.fields["title"] = (struct.unpack_from("<H", body, 2)[0]
                                    if len(body) >= 4 else 0)

    elif code == 0x24:                                    # VarStore (buffer)
        if len(body) >= 20:
            node.fields["guid"] = guid_string(body[:16])
            store_id, size = struct.unpack_from("<HH", body, 16)
            node.fields.update({"id": store_id, "size": size,
                                "name": _ascii_string(body, 20)})

    elif code == 0x26:                                    # VarStoreEfi
        if len(body) >= 22:
            store_id = struct.unpack_from("<H", body, 0)[0]
            node.fields["id"] = store_id
            node.fields["guid"] = guid_string(body[2:18])
            node.fields["attributes"] = struct.unpack_from("<I", body, 18)[0]
            # The long form (UEFI 2.3.1+) also carries size and name.
            if len(body) >= 24:
                node.fields["size"] = struct.unpack_from("<H", body, 22)[0]
                node.fields["name"] = _ascii_string(body, 24)

    elif code == 0x25:                                    # VarStoreNameValue
        if len(body) >= 18:
            node.fields["id"] = struct.unpack_from("<H", body, 0)[0]
            node.fields["guid"] = guid_string(body[2:18])

    elif code in (0x05, 0x07):                            # OneOf, Numeric
        _question_header(node)
        if len(body) >= 12:
            flags = body[11]
            width = WIDTHS[flags & 0x03]
            node.fields.update({"flags": flags, "width": width})
            fmt = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}[width]
            if len(body) >= 12 + 3 * width:
                minimum = struct.unpack_from(fmt, body, 12)[0]
                maximum = struct.unpack_from(fmt, body, 12 + width)[0]
                step = struct.unpack_from(fmt, body, 12 + 2 * width)[0]
                node.fields.update({"minimum": minimum, "maximum": maximum,
                                    "step": step})

    elif code == 0x06:                                    # CheckBox
        _question_header(node)
        node.fields["width"] = 1
        if len(body) >= 12:
            node.fields["flags"] = body[11]

    elif code == 0x1C:                                    # String
        _question_header(node)
        if len(body) >= 14:
            node.fields.update({"minimum": body[11], "maximum": body[12],
                                "flags": body[13]})
            node.fields["width"] = body[12] * 2          # UCS-2 characters

    elif code == 0x08:                                    # Password
        _question_header(node)
        if len(body) >= 15:
            minimum, maximum = struct.unpack_from("<HH", body, 11)
            node.fields.update({"minimum": minimum, "maximum": maximum,
                                "width": maximum * 2})

    elif code == 0x23:                                    # OrderedList
        _question_header(node)
        if len(body) >= 13:
            node.fields.update({"maximum": body[11], "flags": body[12],
                                "width": body[11]})

    elif code in (0x1A, 0x1B):                            # Date, Time
        _question_header(node)
        node.fields["width"] = 4 if code == 0x1A else 3
        if len(body) >= 12:
            node.fields["flags"] = body[11]

    elif code == 0x0C:                                    # Action
        _question_header(node)
        if len(body) >= 13:
            node.fields["config"] = struct.unpack_from("<H", body, 11)[0]

    elif code == 0x0F:                                    # Ref (and variants)
        _question_header(node)
        if len(body) >= 13:
            node.fields["form"] = struct.unpack_from("<H", body, 11)[0]
        if len(body) >= 15:
            node.fields["question"] = struct.unpack_from("<H", body, 13)[0]
        # WARNING: a Ref of 33 bytes (EFI_IFR_REF3) carries the GUID of ANOTHER
        # form set, and that is how a menu links into a different one. Reading
        # only the form number makes such a link look like an ordinary jump
        # inside the same form set - which is exactly how the CHIPSETMENU mod
        # opens the door to AMD CBS, and exactly what we missed at first.
        if len(body) >= 31:
            node.fields["formset_guid"] = guid_string(body[15:31])

    elif code == 0x09:                                    # OneOfOption
        if len(body) >= 4:
            text = struct.unpack_from("<H", body, 0)[0]
            flags, kind = body[2], body[3]
            value, _ = _typed_value(body, 4, kind)
            node.fields.update({"text": text, "flags": flags, "kind": kind,
                                "value": value})

    elif code == 0x5B:                                    # Default
        if len(body) >= 3:
            default_id = struct.unpack_from("<H", body, 0)[0]
            kind = body[2]
            value, _ = _typed_value(body, 3, kind)
            node.fields.update({"default_id": default_id, "kind": kind,
                                "value": value})

    elif code == 0x5C:                                    # DefaultStore
        if len(body) >= 4:
            name, default_id = struct.unpack_from("<HH", body, 0)
            node.fields.update({"name": name, "default_id": default_id})

    elif code in (0x02, 0x03):                            # Subtitle, Text
        if len(body) >= 4:
            prompt, help_id = struct.unpack_from("<HH", body, 0)
            node.fields.update({"prompt": prompt, "help": help_id})
        if code == 0x03 and len(body) >= 6:
            node.fields["text_two"] = struct.unpack_from("<H", body, 4)[0]
        if code == 0x02 and len(body) >= 5:
            node.fields["flags"] = body[4]

    elif code == 0x5F:                                    # Guid (extensions)
        if len(body) >= 16:
            node.fields["guid"] = guid_string(body[:16])
            node.fields["data"] = body[16:]

    # --- expression opcodes that carry fields -------------------------------
    elif code == 0x12:                                    # EqIdVal
        if len(body) >= 4:
            question_id, value = struct.unpack_from("<HH", body, 0)
            node.fields.update({"id": question_id, "value": value})

    elif code == 0x13:                                    # EqIdId
        if len(body) >= 4:
            one, two = struct.unpack_from("<HH", body, 0)
            node.fields.update({"id": one, "id2": two})

    elif code == 0x14:                                    # EqIdValList
        if len(body) >= 4:
            question_id, how_many = struct.unpack_from("<HH", body, 0)
            values = []
            for index in range(how_many):
                start = 4 + index * 2
                if start + 2 <= len(body):
                    values.append(struct.unpack_from("<H", body, start)[0])
            node.fields.update({"id": question_id, "values": values})

    elif code in (0x40, 0x51):                            # QuestionRef1/3
        if len(body) >= 2:
            node.fields["id"] = struct.unpack_from("<H", body, 0)[0]

    elif code == 0x42:
        if body:
            node.fields["value"] = body[0]
    elif code == 0x43 and len(body) >= 2:
        node.fields["value"] = struct.unpack_from("<H", body, 0)[0]
    elif code == 0x44 and len(body) >= 4:
        node.fields["value"] = struct.unpack_from("<I", body, 0)[0]
    elif code == 0x45 and len(body) >= 8:
        node.fields["value"] = struct.unpack_from("<Q", body, 0)[0]
    elif code in (0x4E, 0x4F) and len(body) >= 2:         # StringRef1/2
        node.fields["text"] = struct.unpack_from("<H", body, 0)[0]
    elif code == 0x3F and len(body) >= 1:                 # RuleRef
        node.fields["rule"] = body[0]
    elif code == 0x18 and len(body) >= 1:                 # Rule
        node.fields["rule"] = body[0]


# --------------------------------------------------------------------- tree

def parse(data, start=0):
    """Read the opcodes of a form package and return the root nodes.

    `data` is the package WITHOUT its 4 header bytes. Node offsets are counted
    from there.
    """
    roots = []
    stack = []
    position = start
    while position + 2 <= len(data):
        opcode = data[position]
        second = data[position + 1]
        length = second & 0x7F
        scope = bool(second & 0x80)
        if length < 2 or position + length > len(data):
            break

        body = data[position + 2:position + length]
        node = Node(opcode, position, length, scope, body)
        _read_fields(node)

        if opcode == END_OP:
            # END closes the most recently opened scope. A stray END - it
            # happens in hand-written firmware - must not blow everything up.
            if stack:
                stack.pop()
            position += length
            continue

        if stack:
            node.parent = stack[-1]
            stack[-1].children.append(node)
        else:
            roots.append(node)

        if scope:
            stack.append(node)
        position += length

    return roots


def describe_expression(nodes):
    """An expression on one line, compact but complete.

    It is meant for COMPARING two firmware images, not for pleasant reading: it
    stays in reverse polish notation, as in the firmware. But it says
    everything - and the difference between "SuppressIf: True" (hidden for
    good, no variable will reveal it) and "SuppressIf: id677==1" (hidden while
    that entry is 1) is exactly what a comparison must show.
    """
    parts = []
    for node in nodes:
        code = node.opcode
        if code == 0x12:
            parts.append("id%s==%s" % (node.fields.get("id"), node.fields.get("value")))
        elif code == 0x13:
            parts.append("id%s==id%s" % (node.fields.get("id"), node.fields.get("id2")))
        elif code == 0x14:
            parts.append("id%s in %s" % (node.fields.get("id"), node.fields.get("values")))
        elif code in (0x40, 0x51):
            parts.append("id%s" % node.fields.get("id"))
        elif code in (0x42, 0x43, 0x44, 0x45):
            parts.append(str(node.fields.get("value")))
        elif code == 0x46:
            parts.append("True")
        elif code == 0x47:
            parts.append("False")
        elif code == 0x52:
            parts.append("0")
        elif code == 0x53:
            parts.append("1")
        else:
            parts.append(node.name)
    return " ".join(parts) if parts else "(empty)"


def split_expression(children):
    """Split the children of a condition into (expression, contents).

    WARNING: this is the delicate point. The expression is delimited by
    nothing; it ends where the first non-expression opcode begins. A mistake
    here shifts everything underneath by one entry.
    """
    cut = 0
    for node in children:
        if node.opcode in EXPRESSION_OPS:
            cut += 1
        else:
            break
    return children[:cut], children[cut:]
