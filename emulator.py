# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""BC-250 BIOS Compare - command line.

It does not boot the BIOS: it READS it and EVALUATES it. It shows the menus as
they really are inside, with the real conditions, and says what would happen if
an entry were changed - including the entries a running board never shows,
because the firmware hides them.

    python emulator.py volumes  IMAGE
    python emulator.py formsets IMAGE
    python emulator.py tree     IMAGE [--formset N] [--all] [--variable FILE]
    python emulator.py entry    IMAGE TEXT [--variable FILE]
    python emulator.py simulate IMAGE ENTRY=VALUE [ENTRY=VALUE ...]
    python emulator.py compare  IMAGE-A IMAGE-B
    python emulator.py export   IMAGE FILE.json

Runs the same on Windows and on Linux with Python alone: no library to
install, no external binary.
"""
from __future__ import unicode_literals

import argparse
import io
import json
import os
import sys

import engine
import hii
import volumes

# Tree markers. A single column, because that is where the eye looks.
VISIBLE = " "
HIDDEN = "x"
GREYED = "~"
UNCERTAIN = "?"

LEGEND = ("  legend:  (blank) shown    x hidden by the firmware"
          "    ~ shown but not changeable    ? condition not computable")


def _write(text=""):
    # On Windows the console is not always UTF-8: characters it cannot render
    # become '?' instead of making the command fail.
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, "replace").decode(encoding))


def _open(path):
    if not os.path.isfile(path):
        raise SystemExit("Cannot find the image %s.\n"
                         "A 16 MiB BIOS dump is needed; read it off the board with\n"
                         "  flashrom -p internal -c 'MX25L12835F/MX25L12873F' -r dump.rom"
                         % path)
    image = volumes.read_image(path)
    formsets = hii.open_image(image)
    if not formsets:
        raise SystemExit(
            "No menu found in %s.\n"
            "Check that this is a whole flash image (16 MiB) and not a piece\n"
            "already cut out: the menus live in the UEFI volume, which this\n"
            "program locates by itself." % path)
    return image, formsets


def _pick_formset(formsets, index):
    if index is None:
        return formsets[0]
    if not 0 <= index < len(formsets):
        raise SystemExit("There is no form set %d: there are %d (0..%d). "
                         "List them with 'formsets'."
                         % (index, len(formsets), len(formsets) - 1))
    return formsets[index]


def _state(formset, variable_path=None):
    """The starting state: firmware defaults, or the real variable."""
    state = engine.State(formset)
    state.apply_defaults()
    if variable_path:
        with open(variable_path, "rb") as variable_file:
            data = variable_file.read()
        store = None
        for candidate in formset.varstores.values():
            expected = candidate.size
            if expected and len(data) in (expected, expected + 4):
                store = candidate
                break
        if store is None:
            raise SystemExit(
                "The file %s is %d bytes and matches no variable of this form\n"
                "set (%s).\n"
                "On the board the right variable is read like this:\n"
                "  cat /sys/firmware/efi/efivars/NAME-GUID > variable.bin"
                % (variable_path, len(data),
                   ", ".join("%s=%d" % (candidate.name, candidate.size)
                             for candidate in formset.varstores.values())))
        state.load_variable(store.identifier, data)
    return state


def _mark(result):
    if result.uncertain:
        return UNCERTAIN
    if result.hidden:
        return HIDDEN
    if result.greyed:
        return GREYED
    return VISIBLE


def _readable_value(question, state):
    value = state.read(question)
    if value is engine.UNKNOWN:
        return "-"
    for option in question.options:
        if option.value == value:
            return "%s (%d)" % (option.text, value)
    return "0x%X" % value


# ================================================================== commands

def command_volumes(args):
    image = volumes.read_image(args.image)
    _write("%s - %d bytes" % (args.image, len(image)))
    for volume in volumes.find_volumes(image):
        _write("  0x%08X  %9d bytes  %-8s %s"
               % (volume.offset, volume.size, volume.kind, volume.description))


def command_formsets(args):
    _image, formsets = _open(args.image)
    _write("%d form sets found in %s" % (len(formsets), args.image))
    for index, formset in enumerate(formsets):
        conditional = sum(1 for question in formset.questions
                          if question.has_hiding_condition)
        _write("\n  [%d] %s" % (index, formset.title))
        _write("      %s   from file %s" % (formset.guid, formset.source.file_guid))
        _write("      %d entries, %d of them with a condition that can hide them"
               % (len(formset.questions), conditional))
        for store in formset.varstores.values():
            _write("      variable %-16s %s  %d bytes"
                   % (store.name, store.guid, store.size))


def command_tree(args):
    _image, formsets = _open(args.image)
    formset = _pick_formset(formsets, args.formset)
    state = _state(formset, args.variable)

    _write("%s   (%s)" % (formset.title, formset.guid))
    if args.variable:
        _write("values read from %s" % args.variable)
    else:
        _write("values: the defaults written in the firmware")
    _write(LEGEND)
    _write()

    current_path = None
    shown = 0
    for question in formset.questions:
        result = engine.verdict(question, state)
        if not args.all and result.hidden:
            continue
        if question.path != current_path:
            current_path = question.path
            _write("\n  " + " > ".join(current_path or ["(no form)"]))
        position = ("0x%03X:%d" % (question.offset, question.width)
                    if question.offset is not None and question.width else "        ")
        _write("  %s   %-9s %-46s %-9s %s"
               % (_mark(result), question.kind, question.text_label[:46], position,
                  _readable_value(question, state)))
        shown += 1

    hidden = sum(1 for question in formset.questions
                 if engine.verdict(question, state).hidden)
    _write("\n  %d entries shown, %d hidden by the firmware with these values."
           % (shown, hidden))
    if not args.all and hidden:
        _write("  To see those too: add --all.")


def command_entry(args):
    _image, formsets = _open(args.image)
    wanted = args.text.lower()
    found = 0
    for formset in formsets:
        state = _state(formset, args.variable if formset is formsets[0] else None)
        for question in formset.questions:
            if wanted not in question.text_label.lower():
                continue
            found += 1
            result = engine.verdict(question, state)
            _write("\n%s   [form set: %s]" % (question.text_label, formset.title))
            if question.path:
                _write("  where      %s" % " > ".join(question.path))
            _write("  kind       %s" % question.kind)
            store = question.varstore
            if store is not None and question.offset is not None:
                _write("  variable   %s  %s" % (store.name, store.guid))
                _write("  position   offset 0x%03X, %d bytes"
                       % (question.offset, question.width))
                _write("  on Linux   /sys/firmware/efi/efivars/%s" % store.variable_name)
                _write("             ! the first 4 bytes of the file are the "
                       "attributes: offset 0x%03X sits at 0x%03X in the file"
                       % (question.offset, question.offset + 4))
            if question.options:
                _write("  options")
                for option in question.options:
                    _write("      %-30s = %-6s%s"
                           % (option.text, option.value,
                              "  (default)" if option.is_default else ""))
            if question.defaults:
                _write("  defaults   %s" % question.defaults)
            if "minimum" in question.node.fields:
                _write("  range      %s .. %s step %s"
                       % (question.node.fields.get("minimum"),
                          question.node.fields.get("maximum"),
                          question.node.fields.get("step")))
            if question.help_text:
                _write("  help       %s" % question.help_text)
            if question.conditions:
                _write("  conditions")
                for name, outcome in result.why:
                    _write("      %-14s -> %s" % (name, outcome))
            _write("  now        %s, %s" % (_readable_value(question, state),
                                            repr(result).strip("<>")))
    if not found:
        _write("No entry contains %r. The search ignores case but wants the "
               "actual entry text, not an arbitrary word." % args.text)


def _find_one(formset, text):
    candidates = [question for question in formset.questions
                  if question.text_label.lower() == text.lower()]
    if not candidates:
        candidates = [question for question in formset.questions
                      if text.lower() in question.text_label.lower()]
    if not candidates:
        raise SystemExit("Form set %r has no entry %r." % (formset.title, text))
    if len(candidates) > 1:
        names = ", ".join(sorted({question.text_label for question in candidates}))[:200]
        raise SystemExit("'%s' matches several entries: %s.\n"
                         "Write the exact text of the one you mean." % (text, names))
    return candidates[0]


def command_simulate(args):
    _image, formsets = _open(args.image)
    formset = _pick_formset(formsets, args.formset)
    before = _state(formset, args.variable)
    after = before.copy()

    for assignment in args.assignments:
        if "=" not in assignment:
            raise SystemExit("'%s' is not of the form ENTRY=VALUE." % assignment)
        text, value = assignment.rsplit("=", 1)
        question = _find_one(formset, text.strip())
        number = None
        for option in question.options:
            if option.text.lower() == value.strip().lower():
                number = option.value
        if number is None:
            try:
                number = int(value, 0)
            except ValueError:
                choices = ", ".join(option.text for option in question.options)
                raise SystemExit("For '%s' I do not know the value %r. Choices: %s."
                                 % (question.text_label, value.strip(),
                                    choices or "a number"))
        after.set_value(question, number)
        _write("setting %-40s = %s" % (question.text_label, value.strip()))

    appeared, disappeared, ungreyed, greyed = engine.differences(formset, before, after)
    _write("\nresult: %d entries appear, %d disappear, %d become changeable, "
           "%d become read-only"
           % (len(appeared), len(disappeared), len(ungreyed), len(greyed)))
    for label, group in (("appears", appeared), ("disappears", disappeared),
                         ("unlocks", ungreyed), ("greys out", greyed)):
        for question in group:
            _write("  %-11s %-46s %s" % (label, question.text_label[:46],
                                         " > ".join(question.path)))
    if not (appeared or disappeared or ungreyed or greyed):
        _write("  No entry changes state: this choice governs no other entry.")


# ---------------------------------------------------------------- comparison

def _position(offset):
    """An entry's offset, or a dash when it has none."""
    return "offset 0x%03X" % offset if offset is not None else "-"


# The form set fingerprint lives in hii.py: both this command and the window
# use it, and one definition means one comparison.
_fingerprint = hii.fingerprint


def command_compare(args):
    _a, formsets_a = _open(args.image_a)
    _b, formsets_b = _open(args.image_b)
    titles_a = {formset.title: formset for formset in formsets_a}
    titles_b = {formset.title: formset for formset in formsets_b}

    _write("A = %s" % args.image_a)
    _write("B = %s" % args.image_b)

    only_a = sorted(set(titles_a) - set(titles_b))
    only_b = sorted(set(titles_b) - set(titles_a))
    if only_a:
        _write("\nform sets only in A: %s" % ", ".join(only_a))
    if only_b:
        _write("\nform sets only in B: %s" % ", ".join(only_b))

    for title in sorted(set(titles_a) & set(titles_b)):
        inside_a = _fingerprint(titles_a[title])
        inside_b = _fingerprint(titles_b[title])
        added = sorted(set(inside_b) - set(inside_a))
        removed = sorted(set(inside_a) - set(inside_b))
        changed = [key for key in sorted(set(inside_a) & set(inside_b))
                   if inside_a[key] != inside_b[key]]
        if not (added or removed or changed):
            _write("\n%-28s identical (%d entries)" % (title, len(inside_a)))
            continue
        _write("\n%-28s %d entries in A, %d in B - %d added, %d removed, %d changed"
               % (title, len(inside_a), len(inside_b), len(added), len(removed),
                  len(changed)))
        for key in added[:args.rows]:
            _write("   + %-46s %s" % (key[0][:46], _position(key[1])))
        for key in removed[:args.rows]:
            _write("   - %-46s %s" % (key[0][:46], _position(key[1])))
        for key in changed[:args.rows]:
            fields = [field for field in inside_a[key]
                      if inside_a[key][field] != inside_b[key][field]]
            _write("   ~ %-46s changes: %s" % (key[0][:46], ", ".join(fields)))
            for field in fields:
                _write("       %-10s A: %s" % (field, inside_a[key][field]))
                _write("       %-10s B: %s" % (" ", inside_b[key][field]))
        too_many = max(len(added), len(removed), len(changed)) - args.rows
        if too_many > 0:
            _write("   ... and %d more rows: raise --rows to see them all." % too_many)


def command_export(args):
    _image, formsets = _open(args.image)
    out = []
    for formset in formsets:
        state = engine.State(formset)
        state.apply_defaults()
        entries = []
        for question in formset.questions:
            result = engine.verdict(question, state)
            store = question.varstore
            entries.append({
                "text": question.text_label,
                "help": question.help_text,
                "kind": question.kind,
                "where": question.path,
                "variable": store.name if store else None,
                "offset": question.offset,
                "width": question.width,
                "options": [{"text": option.text, "value": option.value,
                             "default": option.is_default}
                            for option in question.options],
                "defaults": {str(key): value
                             for key, value in question.defaults.items()},
                "conditions": [name for name, _ in question.conditions],
                "hidden_with_defaults": result.hidden,
                "uncertain": result.uncertain,
            })
        out.append({
            "title": formset.title,
            "guid": formset.guid,
            "file": formset.source.file_guid,
            "variables": [{"name": store.name, "guid": store.guid,
                           "size": store.size}
                          for store in formset.varstores.values()],
            "entries": entries,
        })
    with io.open(args.output, "w", encoding="utf-8") as output_file:
        json.dump(out, output_file, indent=2, ensure_ascii=False)
    _write("written %s: %d form sets, %d entries"
           % (args.output, len(out), sum(len(item["entries"]) for item in out)))


# ==================================================================== startup

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="BC-250 BIOS Compare: reads the menus of a firmware image "
                    "and evaluates their conditions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    commands = parser.add_subparsers(dest="command")

    one = commands.add_parser("volumes", help="the UEFI volumes inside the image")
    one.add_argument("image")
    one.set_defaults(function=command_volumes)

    two = commands.add_parser("formsets", help="the form sets and their variables")
    two.add_argument("image")
    two.set_defaults(function=command_formsets)

    three = commands.add_parser("tree", help="the entries of a form set, conditions evaluated")
    three.add_argument("image")
    three.add_argument("--formset", type=int, default=None,
                       help="which form set (see 'formsets')")
    three.add_argument("--all", action="store_true", help="show hidden entries too")
    three.add_argument("--variable", help="variable file read from the board")
    three.set_defaults(function=command_tree)

    four = commands.add_parser("entry", help="everything we know about one entry")
    four.add_argument("image")
    four.add_argument("text")
    four.add_argument("--variable")
    four.set_defaults(function=command_entry)

    five = commands.add_parser("simulate", help="what changes when an entry changes")
    five.add_argument("image")
    five.add_argument("assignments", nargs="+", metavar="ENTRY=VALUE")
    five.add_argument("--formset", type=int, default=None)
    five.add_argument("--variable")
    five.set_defaults(function=command_simulate)

    six = commands.add_parser("compare", help="differences between the menus of two images")
    six.add_argument("image_a")
    six.add_argument("image_b")
    six.add_argument("--rows", type=int, default=20,
                     help="how many rows per category (default 20)")
    six.set_defaults(function=command_compare)

    seven = commands.add_parser("export", help="write everything to a JSON file")
    seven.add_argument("image")
    seven.add_argument("output")
    seven.set_defaults(function=command_export)

    choices = parser.parse_args(argv)
    if not getattr(choices, "function", None):
        parser.print_help()
        return 1
    choices.function(choices)
    return 0


if __name__ == "__main__":
    sys.exit(main())
