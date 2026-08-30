# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""HII packages: the menu strings and the form sets, put back together.

The IFR (see ifr.py) holds only NUMBERS where text should be: every entry
carries a string identifier, and the text lives in a separate package. Here the
two packages are read and joined into a usable model: form sets, varstores,
forms, questions, options, defaults.

WHERE THEY LIVE IN THESE IMAGES (measured on the real BC-250 dump)
The packages are not in a section of their own: they sit INSIDE the driver's
PE32 section, that is, inside the executable, as resources. That is why we
scan: we look for a package header and validate it, instead of following an
index that does not exist here.

WARNING - A TRAP THAT COST US A WASTED ROUND: in the string package header the
language tag is not at offset 44 but at 46. The two bytes of `LanguageName` sit
in between. Validating at 44 finds no package at all and makes it look as if
the firmware had no strings - while it has 151 KB of them.
"""
from __future__ import unicode_literals

import struct

import ffs
import ifr
import volumes

PACKAGE_FORMS = 0x02
PACKAGE_STRINGS = 0x04
PACKAGE_END = 0xDF

# --- blocks inside a string package ----------------------------------------
BLOCK_END = 0x00
BLOCK_UCS2 = 0x14
BLOCK_UCS2_FONT = 0x15
BLOCK_UCS2_MULTI = 0x16
BLOCK_UCS2_MULTI_FONT = 0x17
BLOCK_DUPLICATE = 0x20
BLOCK_SKIP2 = 0x21
BLOCK_SKIP1 = 0x22
BLOCK_EXT1 = 0x30
BLOCK_EXT2 = 0x31
BLOCK_EXT4 = 0x32
BLOCK_FONT = 0x40


# ============================================================ string package

class Strings(object):
    """The identifier -> text table of one language."""

    def __init__(self, language, texts, offset):
        self.language = language
        self.texts = texts
        self.offset = offset

    def __len__(self):
        return len(self.texts)

    def __call__(self, identifier):
        """The text of an identifier; when it is missing, it shows.

        An empty string is never returned for a missing id: the reader must be
        able to tell "this entry has no text" from "our reader did not find the
        string".
        """
        if identifier == 0:
            return ""
        text = self.texts.get(identifier)
        return text if text is not None else "<string %d missing>" % identifier


def read_strings(data, start):
    """Read the string package that begins at `start`."""
    length = struct.unpack_from("<I", data, start)[0] & 0xFFFFFF
    header_size = struct.unpack_from("<I", data, start + 4)[0]
    language = data[start + 46:start + 62].split(b"\0")[0].decode("ascii", "replace")

    end = start + length
    position = start + header_size
    texts = {}
    identifier = 1

    def read_ucs2(where):
        """A zero-terminated UCS-2 string. Returns (text, bytes read)."""
        stop = where
        while stop + 1 < end:
            if data[stop] == 0 and data[stop + 1] == 0:
                break
            stop += 2
        raw = data[where:stop]
        return raw.decode("utf-16-le", "replace"), (stop - where) + 2

    while position < end:
        kind = data[position]
        block_start = position
        position += 1

        if kind == BLOCK_END:
            break
        elif kind == BLOCK_UCS2:
            text, read = read_ucs2(position)
            texts[identifier] = text
            identifier += 1
            position += read
        elif kind == BLOCK_UCS2_FONT:
            position += 1                                   # font identifier
            text, read = read_ucs2(position)
            texts[identifier] = text
            identifier += 1
            position += read
        elif kind in (BLOCK_UCS2_MULTI, BLOCK_UCS2_MULTI_FONT):
            if kind == BLOCK_UCS2_MULTI_FONT:
                position += 1
            how_many = struct.unpack_from("<H", data, position)[0]
            position += 2
            for _ in range(how_many):
                text, read = read_ucs2(position)
                texts[identifier] = text
                identifier += 1
                position += read
        elif kind == BLOCK_DUPLICATE:
            original = struct.unpack_from("<H", data, position)[0]
            texts[identifier] = texts.get(original, "")
            identifier += 1
            position += 2
        elif kind == BLOCK_SKIP2:
            identifier += struct.unpack_from("<H", data, position)[0]
            position += 2
        elif kind == BLOCK_SKIP1:
            identifier += data[position]
            position += 1
        elif kind == BLOCK_EXT1:
            position = block_start + data[position + 1]
        elif kind == BLOCK_EXT2:
            position = block_start + struct.unpack_from("<H", data, position + 1)[0]
        elif kind == BLOCK_EXT4:
            position = block_start + struct.unpack_from("<I", data, position + 1)[0]
        elif kind == BLOCK_FONT:
            position += 1 + 2 + 4                           # id, size, style
            _name, read = read_ucs2(position)
            position += read
        else:
            # A block we do not know: stop here instead of carrying on and
            # inventing identifiers, which would shift every string after it
            # and fill the menu with the wrong text.
            break

    return Strings(language, texts, start)


# =============================================================== HII scanning

def _looks_like_form_package(data, position, length):
    """A real form package always starts with a scoped FormSet."""
    if length < 8 or position + length > len(data):
        return False
    if data[position + 4] != 0x0E:
        return False
    header = data[position + 5]
    if not (header & 0x80):                       # the FormSet opens a scope
        return False
    return (header & 0x7F) >= 0x16


def _looks_like_string_package(data, position, length):
    if length < 64 or position + length > len(data):
        return False
    header_size, info_offset = struct.unpack_from("<II", data, position + 4)
    if header_size != info_offset or not (46 < header_size <= 0x400):
        return False
    language = data[position + 46:position + 62].split(b"\0")[0]
    if not language or len(language) > 12:
        return False
    return all(0x20 <= char < 0x7F for char in language)


def scan(data):
    """Find the HII packages inside any block of bytes.

    Returns (forms, strings): a list of offsets for the form packages and a
    list of Strings objects already read.
    """
    forms = []
    strings = []
    position = 0
    limit = len(data) - 8
    while position < limit:
        kind = data[position + 3]
        if kind not in (PACKAGE_FORMS, PACKAGE_STRINGS):
            position += 1
            continue
        length = struct.unpack_from("<I", data, position)[0] & 0xFFFFFF
        if kind == PACKAGE_FORMS and _looks_like_form_package(data, position, length):
            forms.append((position, length))
            position += length
            continue
        if kind == PACKAGE_STRINGS and _looks_like_string_package(data, position, length):
            try:
                strings.append(read_strings(data, position))
                position += length
                continue
            except Exception:            # noqa: BLE001 - not a package, move on
                pass
        position += 1
    return forms, strings


# ===================================================================== model

class VarStore(object):
    """Where the values end up: a UEFI variable with a name and a GUID."""

    def __init__(self, node):
        self.node = node
        self.identifier = node.fields.get("id", 0)
        self.name = node.fields.get("name", "")
        self.guid = node.fields.get("guid", "")
        self.size = node.fields.get("size", 0)
        self.efi = (node.opcode == 0x26)

    @property
    def variable_name(self):
        """What the file is called under /sys/firmware/efi/efivars, on Linux."""
        return "%s-%s" % (self.name, self.guid.lower())

    def __repr__(self):
        return "<VarStore %s %s 0x%X bytes>" % (self.name, self.guid, self.size)


class Option(object):
    def __init__(self, node, text):
        self.node = node
        self.text = text
        self.value = node.fields.get("value")
        self.flags = node.fields.get("flags", 0)

    @property
    def is_default(self):
        return bool(self.flags & 0x10)          # EFI_IFR_OPTION_DEFAULT

    def __repr__(self):
        return "<Option %r = %r>" % (self.text, self.value)


class Question(object):
    """A menu entry that can be given a value."""

    def __init__(self, formset, node, path, form=None):
        self.formset = formset
        self.node = node
        self.path = path                       # the forms walked through, as text
        self.form = form                       # the form that holds it
        self.options = []
        self.defaults = {}                     # default id -> value
        for child in node.children:
            if child.opcode == 0x09:
                self.options.append(
                    Option(child, formset.text(child.fields.get("text", 0))))
            elif child.opcode == 0x5B:
                self.defaults[child.fields.get("default_id", 0)] = child.fields.get("value")

    # --- identity ----------------------------------------------------------
    @property
    def kind(self):
        return self.node.name

    @property
    def text_label(self):
        return self.formset.text(self.node.fields.get("prompt", 0))

    @property
    def help_text(self):
        return self.formset.text(self.node.fields.get("help", 0))

    @property
    def identifier(self):
        return self.node.fields.get("id", 0)

    # --- where it is written ----------------------------------------------
    @property
    def varstore(self):
        return self.formset.varstores.get(self.node.fields.get("varstore", 0))

    @property
    def offset(self):
        """The offset inside the variable. This is the number needed to write it."""
        return self.node.fields.get("varstore_info")

    @property
    def width(self):
        return self.node.fields.get("width", 0)

    # --- conditions --------------------------------------------------------
    @property
    def conditions(self):
        """The conditions governing this entry, outermost first.

        Each item is (name, condition node). The engine evaluates them against
        a varstore to say whether the entry is visible, greyed out or disabled.
        """
        chain = []
        for ancestor in self.node.ancestors():
            if ancestor.is_condition:
                chain.append((ifr.CONDITIONS[ancestor.opcode], ancestor))
        chain.reverse()
        return chain

    @property
    def has_hiding_condition(self):
        """True when it sits behind a SuppressIf or a DisableIf.

        It does not mean "invisible for good": it means there is a condition,
        and that with the right values in the variable it might show up. What
        decides is the engine.
        """
        return any(name in ("SuppressIf", "DisableIf") for name, _ in self.conditions)

    def __repr__(self):
        return "<Question %s %r>" % (self.kind, self.text_label[:40])


class Form(object):
    """One menu form, with its subforms.

    WARNING: subforms are NOT nested in the IFR: inside a form set all forms
    are siblings, and what links them are the Ref entries. Whoever stops at how
    the data is nested sees seventy-one forms in a row and no hierarchy; the
    real hierarchy only comes out by following the Refs, and that is what the
    BIOS shows the user.
    """

    def __init__(self, formset, node):
        self.formset = formset
        self.node = node
        self.identifier = node.fields.get("id", 0)
        self.questions = []          # the entries that live in this form
        self.children = []           # the subforms, taken from the Refs
        self.parent = None
        self.external = []           # Refs pointing outside this form set

    @property
    def title(self):
        return self.formset.text(self.node.fields.get("title", 0))

    @property
    def path(self):
        """The titles from the starting form down to here."""
        chain, node = [], self
        seen = set()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            chain.append(node.title)
            node = node.parent
        chain.reverse()
        return chain

    def descendants(self):
        for child in self.children:
            yield child
            for inner in child.descendants():
                yield inner

    def __repr__(self):
        return "<Form %r %d questions %d subforms>" % (
            self.title[:30], len(self.questions), len(self.children))


class FormSet(object):
    """A set of forms: the BC-250's "AMD CBS" is one of these."""

    def __init__(self, node, strings, source):
        self.node = node
        self.strings = strings
        self.source = source                   # which file/section it came from
        self.guid = node.fields.get("guid", "")
        self.varstores = {}
        self.questions = []
        self.forms = []                        # every form, in file order
        self.forms_by_id = {}
        self.roots = []                        # forms no Ref points to
        self._build()

    def text(self, identifier):
        if self.strings is None:
            return "<string %d>" % identifier
        return self.strings(identifier)

    @property
    def title(self):
        return self.text(self.node.fields.get("title", 0))

    def _build(self):
        for child in self.node.children:
            if child.opcode in (0x24, 0x25, 0x26):
                store = VarStore(child)
                self.varstores[store.identifier] = store
        self._walk(self.node, [], None)
        self._link_forms()

    def _walk(self, node, path, form):
        for child in node.children:
            if child.opcode in (0x01, 0x5D):              # Form, FormMap
                inner = Form(self, child)
                self.forms.append(inner)
                # If two forms had the same number the first one wins: Refs go
                # where the BIOS goes, and the BIOS finds the first.
                self.forms_by_id.setdefault(inner.identifier, inner)
                self._walk(child, path + [inner.title], inner)
            else:
                if child.is_question:
                    question = Question(self, child, path, form)
                    self.questions.append(question)
                    if form is not None:
                        form.questions.append(question)
                self._walk(child, path, form)

    def _link_forms(self):
        """Build the real subform hierarchy by following the Refs.

        WARNING - two traps, both met on these images:
        1. a Ref can point at a form of ANOTHER form set (Setup has three):
           that is not an error, it must be reported as an external link rather
           than thrown away;
        2. Refs can form a LOOP (A leads to B and B leads back to A). Attaching
           children without checking makes the tree infinite and the window
           hangs on its first draw.
        """
        for question in self.questions:
            if question.node.opcode != 0x0F:              # Ref
                continue
            target_id = question.node.fields.get("form")
            source_form = question.form
            target = self.forms_by_id.get(target_id)
            if target is None:
                if source_form is not None:
                    source_form.external.append(question)
                continue
            if target is source_form or target.parent is not None:
                continue
            if source_form is not None and self._is_descendant(target, source_form):
                continue                                   # would close a loop
            target.parent = source_form
            if source_form is not None:
                source_form.children.append(target)

        self.roots = [form for form in self.forms if form.parent is None]

    @staticmethod
    def _is_descendant(candidate, form):
        """True when `form` already sits under `candidate`: linking would loop."""
        node = form
        seen = set()
        while node is not None and id(node) not in seen:
            if node is candidate:
                return True
            seen.add(id(node))
            node = node.parent
        return False

    @property
    def main_form(self):
        """The form the BIOS starts from: the first one with no parent."""
        return self.roots[0] if self.roots else None

    @property
    def orphan_forms(self):
        """Forms NO link points to, apart from the main one.

        They are not a reading mistake: they are menus the firmware reaches
        some other way - a call from its own code, or a Ref arriving from
        another form set, like Setup > Chipset jumping into AMD CBS. They must
        be shown anyway: they are half the reason this program exists, and in
        AMD CBS they are the majority.
        """
        return self.roots[1:]

    def __repr__(self):
        return "<FormSet %r %d questions>" % (self.title, len(self.questions))


# ============================================================== opening files

class Source(object):
    """Where a form set comes from inside the image: needed to rebuild it."""

    def __init__(self, file_guid, section, package_offset, length):
        self.file_guid = file_guid
        self.section = section
        self.package_offset = package_offset
        self.length = length

    def __repr__(self):
        return "<from %s +0x%X>" % (self.file_guid, self.package_offset)


def _blocks_to_scan(image):
    """Every block of bytes an HII package can hide in.

    Yields (file guid, section, data). Both sections and the body of raw files
    are looked at: raw files have no sections, and skipping them means not
    finding what is inside them.
    """
    for volume in volumes.find_volumes(image):
        if volume.kind == "nvram":
            continue
        top_level = ffs.read_files(volume)
        nested = ffs.nested_volumes(
            [section for entry in top_level for section in entry.sections])
        for container in [volume] + nested:
            for entry in ffs.read_files(container):
                if not entry.sections:
                    yield entry.guid, None, entry.data
                for section in ffs.all_sections(entry.sections):
                    if section.kind in (ffs.SECTION_PE32, ffs.SECTION_RAW,
                                        ffs.SECTION_TE, ffs.SECTION_PIC, 0x18):
                        yield entry.guid, section, section.data


def open_image(image):
    """Every form set in the image, with its strings already attached.

    The strings are taken from the same block the form set is in: that is how
    these images are organised (a driver carries its menu and its text). When a
    block holds several languages, English wins - the only one present in every
    BC-250 image.
    """
    formsets = []
    for file_guid, section, data in _blocks_to_scan(image):
        if len(data) < 16:
            continue
        form_packages, string_packages = scan(data)
        if not form_packages:
            continue
        english = [package for package in string_packages
                   if package.language.lower().startswith("en")]
        strings = (english or string_packages or [None])[0]
        for position, length in form_packages:
            body = data[position + 4:position + length]
            for root in ifr.parse(body):
                if root.opcode == 0x0E:
                    formsets.append(FormSet(
                        root, strings,
                        Source(file_guid, section, position, length)))
    return formsets


def open_file(path):
    return open_image(volumes.read_image(path))


def fingerprint(formset):
    """A form set's entries in a form that can be compared between two images.

    It lives here and not in the command line because two callers need it: the
    "compare" command and the window. The key is (text, offset, sequence): the
    sequence number is there because repeated entries do exist - AMD CBS has
    two "GRA Bus" at the same offset - and without it they would overwrite each
    other, making the comparison report "identical" having lost some on the way.
    """
    inside = {}
    for question in formset.questions:
        key = (question.text_label, question.offset, 0)
        while key in inside:
            key = (key[0], key[1], key[2] + 1)
        inside[key] = {
            "kind": question.kind,
            "width": question.width,
            "options": sorted((option.text, option.value)
                              for option in question.options),
            "defaults": dict(sorted(question.defaults.items())),
            # WARNING: conditions are compared by their EXPRESSION, not just by
            # name. A modified firmware can leave the SuppressIf where it is and
            # change the condition inside it: comparing names alone would miss
            # that change - which is exactly what unlocking a menu looks like -
            # and the comparison would say "identical".
            "conditions": ["%s: %s" % (name, ifr.describe_expression(
                ifr.split_expression(node.children)[0]))
                for name, node in question.conditions],
            "where": " > ".join(question.path),
        }
    return inside
