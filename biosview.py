# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""The menu drawn and driven the way the board itself would show it.

The tree view answers "what is in this image". This one answers a different
question: "what would I see, and where would I have to go, sitting in front of
the board". Same layout as the firmware setup - tab bar across the top, entries
on the left with their value in brackets, help panel on the right, key legend
at the bottom - and the same keys: arrows to move, Enter to walk into a
submenu, Esc to come back, plus and minus to change a value.

WHY IT IS WORTH THE TROUBLE. Reading an offset table tells you the firmware has
1134 entries. Walking the menu tells you that the door to them is bricked up -
you press Enter on Chipset and nothing happens, because a condition no variable
can change hides it. That is a different kind of understanding, and it is the
one you can hand to somebody else.

TWO THINGS THIS VIEW DOES THAT A REAL BOARD CANNOT
  1. It can REVEAL the hidden entries, in their real position in the menu,
     marked instead of missing. On the stock BIOS that is 651 of them.
  2. Changing a value with plus and minus re-evaluates every condition at once,
     so entries appear and disappear under your hands - no reboot involved.

WARNING - WHAT THIS DELIBERATELY DOES NOT COPY: the vendor's title and
copyright lines. The layout is reproduced because it is the point; the AMI
banner is not, because a program that prints somebody else's name at the top of
its own window is claiming to be their firmware. The header says what this is,
and the footer shows the firmware version read from the image, which is true.
"""
from __future__ import unicode_literals

import tkinter as tk
from tkinter import ttk

import engine
import theme
from languages import T

# The setup screen palette. Kept together here on purpose: matching a photo of
# a real board is a matter of nudging these seven values, not of hunting
# through the drawing code.
BG = "#0B1F3A"          # deep blue field
CHROME = "#7FA8D0"      # frame lines
HEAD_BG = "#C3CEDA"     # title and tab bar
HEAD_FG = "#0A1725"
ITEM = "#E6EDF5"        # entry names
VALUE = "#7FD1FF"       # values, in brackets
SELECT_BG = "#E6EDF5"   # the highlighted row: reversed, as in text mode
SELECT_FG = "#0A1725"
HELP = "#C8D6E5"
KEYS = "#9FB8CF"
HIDDEN = "#C77B7B"      # entries the firmware hides, when we reveal them
GREYED = "#8090A0"      # visible but not changeable

WIDTH = 98              # character grid, like a text mode screen
LEFT = 62               # where the help panel starts
HEIGHT = 30


class BiosView(tk.Frame):
    """A setup screen you can walk through, driven by the same keys."""

    def __init__(self, parent, on_select=None, on_formset_change=None):
        tk.Frame.__init__(self, parent, background=BG)
        self.on_select = on_select          # told which entry is highlighted
        self.on_formset_change = on_formset_change   # told when we leave for
        self.formsets = []                           # another form set
        self.formset = None
        self.state = None
        self.tabs = []                      # the top level forms
        self.tab_index = 0
        self.stack = []                     # forms walked into, innermost last
        self.row_index = 0
        self.rows = []                      # (question, form) for each drawn row
        self.show_hidden = False
        self.firmware_version = ""

        self.screen = tk.Text(self, background=BG, foreground=ITEM,
                              relief="flat", highlightthickness=0, wrap="none",
                              cursor="arrow", padx=10, pady=8,
                              width=WIDTH, height=HEIGHT, spacing1=0, spacing3=0)
        self.screen.pack(fill="both", expand=True)
        self.screen.configure(state="disabled")

        for name, colour in (("chrome", CHROME), ("item", ITEM), ("value", VALUE),
                             ("help", HELP), ("keys", KEYS), ("hidden", HIDDEN),
                             ("greyed", GREYED)):
            self.screen.tag_configure(name, foreground=colour)
        self.screen.tag_configure("head", foreground=HEAD_FG, background=HEAD_BG)
        self.screen.tag_configure("tab_on", foreground=HEAD_FG, background=HEAD_BG)
        self.screen.tag_configure("tab_off", foreground=HEAD_BG, background=BG)
        self.screen.tag_configure("selected", foreground=SELECT_FG,
                                  background=SELECT_BG)
        self.screen.tag_configure("selected_hidden", foreground=SELECT_FG,
                                  background=HIDDEN)

        # The keys are bound on the widget, not on the window: the tree view
        # next door has to keep its own arrow keys.
        for key in ("<Up>", "<Down>", "<Left>", "<Right>", "<Return>",
                    "<Escape>", "<plus>", "<minus>", "<KP_Add>", "<KP_Subtract>",
                    "<Prior>", "<Next>", "<Home>", "<End>", "<F9>"):
            self.screen.bind(key, self._key)
        self.screen.bind("<Button-1>", self._click)
        self.screen.bind("<Double-Button-1>", self._enter)

    # ------------------------------------------------------------- contents

    def load(self, formset, state, firmware_version="", formsets=None):
        self.formsets = list(formsets or [formset])
        self.formset = formset
        self.state = state
        self.firmware_version = firmware_version
        main = formset.main_form if formset else None
        # The tab bar is what the main form links to; when it links to nothing
        # (AMD CBS reached from outside), the roots themselves are the tabs.
        self.tabs = list(main.children) if main and main.children else list(
            formset.roots if formset else [])
        if main and not main.children:
            self.tabs = [main] + [form for form in formset.roots if form is not main]
        self.tab_index = 0
        self.stack = [self.tabs[0]] if self.tabs else []
        self.row_index = 0
        self.draw()

    def set_state(self, state):
        self.state = state
        self.draw()

    def set_show_hidden(self, show):
        self.show_hidden = bool(show)
        self.draw()

    @property
    def current_form(self):
        return self.stack[-1] if self.stack else None

    def selected_question(self):
        if 0 <= self.row_index < len(self.rows):
            return self.rows[self.row_index][0]
        return None

    # --------------------------------------------------------------- drawing

    def _visible_rows(self, form):
        """The entries of this form, in menu order, with their verdict."""
        rows = []
        for question in form.questions:
            result = engine.verdict(question, self.state)
            if result.hidden and not self.show_hidden:
                continue
            rows.append((question, result))
        return rows

    def draw(self):
        if self.formset is None or self.current_form is None:
            return
        rows = self._visible_rows(self.current_form)
        self.rows = [(question, self.current_form) for question, _ in rows]
        if self.row_index >= len(rows):
            self.row_index = max(0, len(rows) - 1)

        lines = []          # (text, [(start, end, tag), ...])

        def plain(text, tag=None):
            lines.append((text.ljust(WIDTH), [(0, WIDTH, tag)] if tag else []))

        # --- title -----------------------------------------------------
        title = " %s " % T("BIOS view - how the board would show this menu")
        plain(title.center(WIDTH), "head")

        # --- tab bar ---------------------------------------------------
        pieces, spans, column = [], [], 1
        pieces.append(" ")
        for index, form in enumerate(self.tabs):
            label = "  %s  " % form.title
            spans.append((column, column + len(label),
                          "tab_on" if index == self.tab_index else "tab_off"))
            pieces.append(label)
            column += len(label)
        row = "".join(pieces).ljust(WIDTH)
        lines.append((row, spans))

        # --- frame -----------------------------------------------------
        lines.append(("┌" + "─" * (LEFT - 2) + "┬" + "─" * (WIDTH - LEFT - 1) + "┐",
                      [(0, WIDTH, "chrome")]))

        help_lines = self._help_lines(rows)
        body_height = HEIGHT - 8
        for offset in range(body_height):
            left_text = ""
            spans = []
            if offset < len(rows):
                question, result = rows[offset]
                left_text, item_tag = self._entry_line(question, result)
                if offset == self.row_index:
                    item_tag = ("selected_hidden" if result.hidden else "selected")
                spans.append((1, LEFT - 1, item_tag))
            right_text = help_lines[offset] if offset < len(help_lines) else ""
            line = ("│" + left_text.ljust(LEFT - 2)[:LEFT - 2] + "│"
                    + right_text.ljust(WIDTH - LEFT - 1)[:WIDTH - LEFT - 1] + "│")
            spans += [(0, 1, "chrome"), (LEFT - 1, LEFT, "chrome"),
                      (WIDTH - 1, WIDTH, "chrome"),
                      (LEFT, WIDTH - 1, "help" if offset < self._help_body else "keys")]
            lines.append((line, spans))

        lines.append(("└" + "─" * (LEFT - 2) + "┴" + "─" * (WIDTH - LEFT - 1) + "┘",
                      [(0, WIDTH, "chrome")]))

        # --- footer ----------------------------------------------------
        where = " > ".join(form.title for form in self.stack)
        counts = self._counts(rows)
        plain(" %s" % where, "keys")
        plain(" %s%s" % (counts, ("   |   " + self.firmware_version)
                         if self.firmware_version else ""), "keys")

        self._paint(lines)
        if self.on_select:
            self.on_select(self.selected_question())

    def _entry_line(self, question, result):
        """One menu row: name on the left, value in brackets on the right."""
        is_link = question.kind == "Ref"
        name = ("> " if is_link else "  ") + question.text_label.strip()
        if result.hidden:
            name = "x " + question.text_label.strip()
        value = ""
        if not is_link:
            raw = self.state.read(question)
            if raw is not engine.UNKNOWN:
                shown = None
                for option in question.options:
                    if option.value == raw:
                        shown = option.text
                # An option whose text is empty happens (the language list is
                # one): showing "[]" would look like a bug in the reader, so
                # the raw number is shown instead - it is at least true.
                if not shown:
                    shown = "0x%X" % raw
                value = "[%s]" % shown
        room = LEFT - 4
        line = " " + name[:room - len(value) - 1].ljust(room - len(value)) + value
        tag = "item"
        if result.hidden:
            tag = "hidden"
        elif result.greyed:
            tag = "greyed"
        return line, tag

    def _counts(self, rows):
        hidden = sum(1 for _q, result in rows if result.hidden)
        total = len(self.current_form.questions)
        if self.show_hidden:
            return T("{shown} entries, {hidden} of them hidden by the firmware",
                     shown=total, hidden=hidden)
        return T("{shown} entries shown, {hidden} hidden by the firmware",
                 shown=len(rows), hidden=total - len(rows))

    def _help_lines(self, rows):
        """The right hand panel: help text on top, key legend underneath."""
        text = ""
        if 0 <= self.row_index < len(rows):
            question = rows[self.row_index][0]
            text = question.help_text or ""
        width = WIDTH - LEFT - 3
        wrapped = []
        for paragraph in text.split("\n"):
            words, line = paragraph.split(), ""
            for word in words:
                if len(line) + len(word) + 1 > width:
                    wrapped.append(" " + line)
                    line = word
                else:
                    line = (line + " " + word).strip()
            wrapped.append(" " + line)
        wrapped = wrapped[:10]
        self._help_body = len(wrapped)
        legend = [
            "",
            " " + "─" * (width - 1),
            " >< : Select Screen",
            " ^v : Select Item",
            " Enter: Select > SubMenu",
            " +/- : Change Opt.",
            " F9  : Load Defaults",
            " ESC : Back",
        ]
        return wrapped + legend

    def _paint(self, lines):
        self.screen.configure(state="normal")
        self.screen.delete("1.0", "end")
        for number, (text, spans) in enumerate(lines, start=1):
            self.screen.insert("end", text + "\n")
            for start, end, tag in spans:
                if not tag:
                    continue
                # A span reaching the right edge is closed with "end" instead
                # of a column number: the Text widget counts what it actually
                # holds, and a title bar that stops two characters short of the
                # edge is the sort of thing that makes the whole screen look
                # like an imitation.
                stop = ("%d.end" % number if end >= WIDTH
                        else "%d.%d" % (number, end))
                self.screen.tag_add(tag, "%d.%d" % (number, start), stop)
        self.screen.configure(state="disabled")

    # ------------------------------------------------------------ navigation

    def _key(self, event):
        key = event.keysym
        if key == "Up":
            self.row_index = max(0, self.row_index - 1)
        elif key == "Down":
            self.row_index = min(len(self.rows) - 1, self.row_index + 1)
        elif key == "Prior":
            self.row_index = max(0, self.row_index - 10)
        elif key == "Next":
            self.row_index = min(len(self.rows) - 1, self.row_index + 10)
        elif key == "Home":
            self.row_index = 0
        elif key == "End":
            self.row_index = max(0, len(self.rows) - 1)
        elif key in ("Left", "Right"):
            # The tab bar only moves when we are at the top of a tab, exactly
            # as on the board: inside a submenu the arrows do nothing.
            if len(self.stack) == 1 and self.tabs:
                step = -1 if key == "Left" else 1
                self.tab_index = (self.tab_index + step) % len(self.tabs)
                self.stack = [self.tabs[self.tab_index]]
                self.row_index = 0
        elif key == "Return":
            return self._enter()
        elif key == "Escape":
            if len(self.stack) > 1:
                self.stack.pop()
                self.row_index = 0
        elif key in ("plus", "KP_Add", "minus", "KP_Subtract"):
            self._change_value(1 if key in ("plus", "KP_Add") else -1)
        elif key == "F9":
            if self.state is not None:
                self.state.apply_defaults()
        self.draw()
        return "break"

    def _enter(self, _event=None):
        question = self.selected_question()
        if question is None or question.kind != "Ref":
            self.draw()
            return "break"
        wanted = question.node.fields.get("form")
        target = self.formset.forms_by_id.get(wanted)
        if target is not None:
            self.stack.append(target)
            self.row_index = 0
            self.draw()
            return "break"
        # The link points outside this form set. That is not a dead end: on the
        # board, Setup > Chipset > GFX Configuration lands inside AMD CBS, and
        # pressing Enter has to land there here too, or the walk stops exactly
        # where the interesting part begins.
        for other in self.formsets:
            if other is self.formset:
                continue
            elsewhere = other.forms_by_id.get(wanted)
            if elsewhere is not None:
                if self.on_formset_change:
                    self.on_formset_change(other, elsewhere)
                return "break"
        self.draw()
        return "break"

    def go_to(self, formset, form, state):
        """Show one precise form of a form set - used after a cross link."""
        self.formset = formset
        self.state = state
        main = formset.main_form
        self.tabs = list(main.children) if main and main.children else list(formset.roots)
        if main and not main.children:
            self.tabs = [main] + [f for f in formset.roots if f is not main]
        # The tab we land under is the outermost ancestor of the target form.
        chain, node = [], form
        while node is not None:
            chain.append(node)
            node = node.parent
        chain.reverse()
        self.tab_index = 0
        for index, tab in enumerate(self.tabs):
            if tab in chain:
                self.tab_index = index
        self.stack = chain if chain else [form]
        self.row_index = 0
        self.draw()

    def _change_value(self, direction):
        """Plus and minus walk the options, as they do in the firmware."""
        question = self.selected_question()
        if question is None or not question.options:
            return
        current = self.state.read(question)
        values = [option.value for option in question.options]
        try:
            position = values.index(current)
        except ValueError:
            position = 0
        position = (position + direction) % len(values)
        try:
            self.state.set_value(question, values[position])
        except ValueError:
            pass

    def _click(self, event):
        self.screen.focus_set()
        row = int(self.screen.index("@%d,%d" % (event.x, event.y)).split(".")[0])
        # rows start after title, tab bar and the top frame line
        index = row - 4
        if 0 <= index < len(self.rows):
            self.row_index = index
            self.draw()
        return "break"
