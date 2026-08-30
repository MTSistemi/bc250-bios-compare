# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""The setup screen, drawn with the firmware's own glyphs and walked with its
own keys.

The tree view answers "what is in this image". This one answers a different
question: "what would I see, and where would I have to go, sitting in front of
the board". It is meant to feel like the board, not like a program about the
board, so nothing here is an approximation of the setup screen:

  THE FONT is the one inside the image. The BIOS carries its glyphs as an HII
  Simple Font package - 8 by 19 pixels each - and hiifont.py pulls them out.
  The stock BC-250 image has 242 of them, frame pieces and arrows included, so
  every character on this screen is the character the board would draw.

  THE COLOURS are the sixteen EFI console colours, the palette the firmware
  itself is limited to. Not "a blue that looks about right": EFI blue, which is
  #0000A8, and the light grey of the title bar, which is #A8A8A8.

  THE GRID is 100 by 31 characters, the text mode the setup runs in.

  THE KEYS are the setup's: arrows to move, left and right to change tab, Enter
  into a submenu, Esc back, plus and minus through the values, F9 for defaults.

TWO THINGS THIS SCREEN DOES THAT A REAL BOARD CANNOT
  1. It can REVEAL the hidden entries, in their real place in the menu, marked
     instead of missing. On the stock BIOS that is 651 of them.
  2. Changing a value re-evaluates every condition at once, so entries appear
     and disappear under your hands - no reboot in between.

WARNING - WHAT IS DELIBERATELY NOT COPIED: the vendor's title and copyright
lines. The layout, the font and the palette are reproduced because they are the
point; the banner is not, because a program that prints somebody else's name at
the top of its own window is claiming to be their firmware. The top line says
what this is and which image it is showing.
"""
from __future__ import unicode_literals

import tkinter as tk

import engine
import hiifont
from languages import T

# --- the sixteen EFI console colours ---------------------------------------
# These are the only colours the firmware has: EFI text attributes are four
# bits of foreground and three of background, and this is that palette.
EFI = ["#000000", "#0000A8", "#00A800", "#00A8A8", "#A80000", "#A800A8",
       "#A85400", "#A8A8A8", "#545454", "#5454FC", "#54FC54", "#54FCFC",
       "#FC5454", "#FC54FC", "#FCFC54", "#FCFCFC"]
BLACK, BLUE, GREEN, CYAN, RED, MAGENTA, BROWN, LIGHTGRAY = range(8)
DARKGRAY, LIGHTBLUE, LIGHTGREEN, LIGHTCYAN, LIGHTRED, LIGHTMAGENTA, \
    YELLOW, WHITE = range(8, 16)

# How the setup paints itself, as (foreground, background) pairs.
ATTR_TITLE = (BLACK, LIGHTGRAY)
ATTR_TAB = (BLACK, LIGHTGRAY)
ATTR_TAB_ON = (WHITE, BLUE)
ATTR_FIELD = (LIGHTGRAY, BLUE)
ATTR_ITEM = (LIGHTGRAY, BLUE)
ATTR_VALUE = (WHITE, BLUE)
ATTR_SUBMENU = (WHITE, BLUE)
ATTR_SELECTED = (BLACK, LIGHTGRAY)
ATTR_FRAME = (LIGHTGRAY, BLUE)
ATTR_HELP = (WHITE, BLUE)
ATTR_KEYS = (LIGHTGRAY, BLUE)
ATTR_GREYED = (DARKGRAY, BLUE)
ATTR_HIDDEN = (LIGHTRED, BLUE)          # what the firmware would not show
ATTR_HIDDEN_SEL = (BLACK, LIGHTRED)

COLUMNS = 100                 # the text mode the setup runs in
ROWS = 31
HELP_AT = 63                  # column where the help panel starts

CELL_WIDTH = hiifont.GLYPH_WIDTH
CELL_HEIGHT = hiifont.GLYPH_HEIGHT


class BiosView(tk.Frame):
    """A setup screen you can walk through, drawn with the firmware's font."""

    def __init__(self, parent, on_select=None, on_formset_change=None, zoom=1):
        tk.Frame.__init__(self, parent, background=EFI[BLACK])
        self.on_select = on_select
        self.on_formset_change = on_formset_change
        self.zoom = zoom
        self.font = None                # the glyphs, out of the image
        self.formsets = []
        self.formset = None
        self.state = None
        self.tabs = []
        self.tab_index = 0
        self.stack = []
        self.row_index = 0
        self.rows = []
        self.show_hidden = False
        self.image_name = ""
        self._glyph_cache = {}
        self._cells = {}                # (row, column) -> (char, fg, bg)

        width = COLUMNS * CELL_WIDTH * zoom
        height = ROWS * CELL_HEIGHT * zoom
        self.screen = tk.Canvas(self, width=width, height=height,
                                background=EFI[BLUE], highlightthickness=0,
                                bd=0, takefocus=True, cursor="arrow")
        self.screen.pack(expand=True)

        for key in ("<Up>", "<Down>", "<Left>", "<Right>", "<Return>",
                    "<Escape>", "<plus>", "<minus>", "<KP_Add>", "<KP_Subtract>",
                    "<Prior>", "<Next>", "<Home>", "<End>", "<F9>"):
            self.screen.bind(key, self._key)
        self.screen.bind("<Button-1>", self._click)
        self.screen.bind("<Double-Button-1>", self._enter)

    # ------------------------------------------------------------- contents

    def load(self, formset, state, image=None, formsets=None, image_name=""):
        """Show a form set. `image` is the raw firmware, for its font."""
        if image is not None and self.font is None:
            self.font = hiifont.load(image)
        self.formsets = list(formsets or [formset])
        self.formset = formset
        self.state = state
        self.image_name = image_name
        self._set_tabs(formset)
        self.tab_index = 0
        self.stack = [self.tabs[0]] if self.tabs else []
        self.row_index = 0
        self.draw()

    def _set_tabs(self, formset):
        main = formset.main_form if formset else None
        # The tab bar is what the main form links to; when it links nowhere -
        # AMD CBS, which is reached from another form set - the roots are the
        # tabs, main first.
        if main and main.children:
            self.tabs = list(main.children)
        elif formset:
            self.tabs = ([main] if main else []) + [
                form for form in formset.roots if form is not main]
        else:
            self.tabs = []

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
            return self.rows[self.row_index]
        return None

    def go_to(self, formset, form, state):
        """Show one precise form - used after following a cross link."""
        self.formset = formset
        self.state = state
        self._set_tabs(formset)
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

    # --------------------------------------------------------------- drawing

    def _write(self, row, column, text, attribute):
        foreground, background = attribute
        for offset, character in enumerate(text):
            if 0 <= column + offset < COLUMNS and 0 <= row < ROWS:
                self._cells[(row, column + offset)] = (character, foreground,
                                                       background)

    def _fill(self, row, column, count, attribute):
        self._write(row, column, " " * count, attribute)

    def _entry_rows(self, form):
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
        entries = self._entry_rows(self.current_form)
        self.rows = [question for question, _ in entries]
        if self.row_index >= len(entries):
            self.row_index = max(0, len(entries) - 1)

        self._cells = {}
        for row in range(ROWS):
            self._fill(row, 0, COLUMNS, ATTR_FIELD)

        # --- line 0: what this is and which image ----------------------
        self._fill(0, 0, COLUMNS, ATTR_TITLE)
        heading = "BC-250 BIOS Compare"
        if self.image_name:
            heading += " - " + self.image_name
        self._write(0, max(0, (COLUMNS - len(heading)) // 2), heading, ATTR_TITLE)

        # --- line 1: the tab bar ---------------------------------------
        self._fill(1, 0, COLUMNS, ATTR_TAB)
        column = 1
        for index, form in enumerate(self.tabs):
            label = " %s " % form.title
            self._write(1, column, label,
                        ATTR_TAB_ON if index == self.tab_index else ATTR_TAB)
            column += len(label) + 1
            if column >= COLUMNS - 2:
                break

        # --- the frame -------------------------------------------------
        top, bottom = 2, ROWS - 3
        self._write(top, 0, "┌" + "─" * (HELP_AT - 1) + "┬"
                    + "─" * (COLUMNS - HELP_AT - 2) + "┐", ATTR_FRAME)
        self._write(bottom, 0, "└" + "─" * (HELP_AT - 1) + "┴"
                    + "─" * (COLUMNS - HELP_AT - 2) + "┘", ATTR_FRAME)
        for row in range(top + 1, bottom):
            self._write(row, 0, "│", ATTR_FRAME)
            self._write(row, HELP_AT, "│", ATTR_FRAME)
            self._write(row, COLUMNS - 1, "│", ATTR_FRAME)

        # --- the entries -----------------------------------------------
        body_height = bottom - top - 1
        first = max(0, min(self.row_index - body_height // 2,
                           len(entries) - body_height))
        first = max(0, first)
        for line in range(body_height):
            index = first + line
            if index >= len(entries):
                break
            question, result = entries[index]
            selected = (index == self.row_index)
            self._entry_line(top + 1 + line, question, result, selected)

        # --- the help panel and the key legend -------------------------
        self._help_panel(top + 1, bottom - 1, entries)

        # --- the bottom lines ------------------------------------------
        where = " > ".join(form.title for form in self.stack)
        self._write(ROWS - 2, 1, where[:COLUMNS - 2], ATTR_KEYS)
        self._write(ROWS - 1, 1, self._counts(entries)[:COLUMNS - 2], ATTR_KEYS)

        self._paint()
        if self.on_select:
            self.on_select(self.selected_question())

    def _entry_line(self, row, question, result, selected):
        is_link = question.kind == "Ref"
        attribute = ATTR_ITEM
        if result.hidden:
            attribute = ATTR_HIDDEN
        elif result.greyed:
            attribute = ATTR_GREYED
        elif is_link:
            attribute = ATTR_SUBMENU
        if selected:
            attribute = ATTR_HIDDEN_SEL if result.hidden else ATTR_SELECTED

        # The whole row takes the attribute, so the highlight is a bar across
        # the panel, the way the setup draws it.
        self._fill(row, 1, HELP_AT - 1, attribute)
        name = question.text_label.strip()
        if result.hidden:
            name = "x " + name          # our own mark: the board shows nothing
        elif is_link:
            name = "> " + name
        else:
            name = "  " + name
        self._write(row, 2, name[:HELP_AT - 22], attribute)

        if not is_link:
            raw = self.state.read(question)
            if raw is not engine.UNKNOWN:
                shown = None
                for option in question.options:
                    if option.value == raw:
                        shown = option.text
                if not shown:
                    shown = "0x%X" % raw
                text = "[%s]" % shown[:16]
                value_attribute = attribute if selected else (
                    ATTR_VALUE if not result.hidden and not result.greyed
                    else attribute)
                self._write(row, HELP_AT - len(text) - 2, text, value_attribute)

    def _counts(self, entries):
        hidden = sum(1 for _q, result in entries if result.hidden)
        total = len(self.current_form.questions)
        if self.show_hidden:
            return T("{shown} entries, {hidden} of them hidden by the firmware",
                     shown=total, hidden=hidden)
        return T("{shown} entries shown, {hidden} hidden by the firmware",
                 shown=len(entries), hidden=total - len(entries))

    def _help_panel(self, top, bottom, entries):
        width = COLUMNS - HELP_AT - 2
        text = ""
        if 0 <= self.row_index < len(entries):
            text = entries[self.row_index][0].help_text or ""
        lines, line = [], ""
        for word in text.split():
            if len(line) + len(word) + 1 > width:
                lines.append(line)
                line = word
            else:
                line = (line + " " + word).strip()
        if line:
            lines.append(line)

        legend = [
            "→←: Select Screen",
            "↑↓: Select Item",
            "Enter: Select",
            "+/-: Change Opt.",
            "F9: Optimized Defaults",
            "ESC: Exit",
        ]
        room = bottom - top + 1
        lines = lines[:max(0, room - len(legend) - 2)]
        for offset, line in enumerate(lines):
            self._write(top + offset, HELP_AT + 2, line, ATTR_HELP)
        start = bottom - len(legend)
        self._write(start - 1, HELP_AT + 1, "─" * width, ATTR_FRAME)
        for offset, line in enumerate(legend):
            self._write(start + offset, HELP_AT + 2, line, ATTR_KEYS)

    # ------------------------------------------------------------- painting

    def _glyph(self, character, foreground, background):
        """One character as a small image, kept for the next time it is used.

        A screen is three thousand cells and most of them repeat: without the
        cache every redraw would rebuild the same letters over and over, and
        the arrow keys would feel sticky.
        """
        key = (character, foreground, background)
        image = self._glyph_cache.get(key)
        if image is not None:
            return image
        rows = self.font.rows(character) if self.font else [0] * CELL_HEIGHT
        fore, back = EFI[foreground], EFI[background]
        picture = tk.PhotoImage(width=CELL_WIDTH, height=CELL_HEIGHT)
        data = []
        for bits in rows:
            data.append(" ".join(fore if bits & (0x80 >> column) else back
                                 for column in range(CELL_WIDTH)))
        picture.put("{" + "} {".join(data) + "}")
        if self.zoom > 1:
            picture = picture.zoom(self.zoom, self.zoom)
        self._glyph_cache[key] = picture
        return picture

    def _paint(self):
        self.screen.delete("all")
        step_x = CELL_WIDTH * self.zoom
        step_y = CELL_HEIGHT * self.zoom
        # The background first, in blocks: painting three thousand blank cells
        # one glyph at a time is the difference between instant and sluggish.
        blocks = {}
        for (row, column), (character, _fg, background) in self._cells.items():
            blocks.setdefault((row, background), []).append(column)
        for (row, background), columns in blocks.items():
            columns.sort()
            start = previous = columns[0]
            for column in columns[1:] + [None]:
                if column is not None and column == previous + 1:
                    previous = column
                    continue
                self.screen.create_rectangle(
                    start * step_x, row * step_y,
                    (previous + 1) * step_x, (row + 1) * step_y,
                    fill=EFI[background], width=0)
                if column is not None:
                    start = previous = column
        for (row, column), (character, foreground, background) in self._cells.items():
            if character == " ":
                continue
            self.screen.create_image(column * step_x, row * step_y,
                                     image=self._glyph(character, foreground,
                                                       background),
                                     anchor="nw")

    # -------------------------------------------------------------- export

    def export_png(self, path, zoom=2):
        """Write the screen to a PNG, straight from the cells.

        Not a screenshot: the pixels are built from the same glyphs and the
        same palette the canvas uses, so the picture is exact, repeatable, and
        cannot accidentally catch whatever else was on the desktop. That last
        part is why the documentation shots are made this way.
        """
        import struct
        import zlib

        width = COLUMNS * CELL_WIDTH * zoom
        height = ROWS * CELL_HEIGHT * zoom
        background = self._cells.get((0, 0), (" ", LIGHTGRAY, BLUE))[2]
        rows = [bytearray(self._rgb(background) * width) for _ in range(height)]

        for (row, column), (character, foreground, back) in self._cells.items():
            glyph = self.font.rows(character) if self.font else [0] * CELL_HEIGHT
            fore_rgb, back_rgb = self._rgb(foreground), self._rgb(back)
            for y, bits in enumerate(glyph):
                for x in range(CELL_WIDTH):
                    colour = fore_rgb if bits & (0x80 >> x) else back_rgb
                    for dy in range(zoom):
                        target = rows[(row * CELL_HEIGHT + y) * zoom + dy]
                        for dx in range(zoom):
                            start = ((column * CELL_WIDTH + x) * zoom + dx) * 3
                            target[start:start + 3] = colour

        raw = bytearray()
        for line in rows:
            raw.append(0)                       # filter "none"
            raw += line

        def chunk(name, data):
            block = name + data
            return (struct.pack(">I", len(data)) + block
                    + struct.pack(">I", zlib.crc32(block) & 0xFFFFFFFF))

        with open(path, "wb") as picture:
            picture.write(bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)))
            picture.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                                     8, 2, 0, 0, 0)))
            picture.write(chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
            picture.write(chunk(b"IEND", b""))
        return path

    @staticmethod
    def _rgb(colour):
        value = EFI[colour]
        return bytes((int(value[1:3], 16), int(value[3:5], 16),
                      int(value[5:7], 16)))

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
            # The tab bar only moves at the top level, exactly as on the board:
            # inside a submenu these keys do nothing.
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
        # The link points outside this form set. Not a dead end: on the board
        # Setup > Chipset > GFX Configuration lands inside AMD CBS, and Enter
        # has to land there here too, or the walk stops exactly where the
        # interesting part begins.
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
        row = int(event.y // (CELL_HEIGHT * self.zoom))
        first_row = 3
        index = row - first_row
        entries = self._entry_rows(self.current_form) if self.current_form else []
        body_height = (ROWS - 3) - 2 - 1
        first = max(0, min(self.row_index - body_height // 2,
                           len(entries) - body_height))
        first = max(0, first)
        if 0 <= index < len(self.rows):
            self.row_index = min(len(self.rows) - 1, first + index)
            self.draw()
        return "break"
