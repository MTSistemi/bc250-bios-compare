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

import datetime
import tkinter as tk

import engine
import hiifont
import tse
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
ATTR_EDIT = (WHITE, BLACK)          # the part of a date or time being typed
ATTR_POPUP = (BLACK, LIGHTGRAY)     # the option list the setup pops up
ATTR_POPUP_SEL = (WHITE, BLUE)

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
        self.image = None               # the raw firmware, for font and tabs
        self.tabs_from_tse = False      # whether the tab bar is the real one
        # The board keeps date and time in the RTC, not in a variable: those
        # two entries have no varstore at all (offset 0xFFFF). To behave like
        # the setup we keep a clock of our own, started from this machine.
        self.clock = datetime.datetime.now().replace(microsecond=0)
        self.field = 0                  # which part of a date or time is being edited
        self.popup = None               # the option list or the number box
        self.notice = ""                # one line about what just happened
        self._glyph_cache = {}
        self._cells = {}                # (row, column) -> (char, fg, bg)

        width = COLUMNS * CELL_WIDTH * zoom
        height = ROWS * CELL_HEIGHT * zoom
        self.screen = tk.Canvas(self, width=width, height=height,
                                background=EFI[BLUE], highlightthickness=0,
                                bd=0, takefocus=True, cursor="arrow")
        self.screen.pack(expand=True)

        # One handler for everything, the way a console has one keyboard: the
        # setup answers to arrows, Enter, Esc, Tab, plus and minus AND to typed
        # digits, and splitting that across a dozen bindings is how a key ends
        # up doing nothing without anyone noticing.
        self.screen.bind("<Key>", self._key)
        self.screen.bind("<Button-1>", self._click)
        self.screen.bind("<Double-Button-1>", self._enter)

    # ------------------------------------------------------------- contents

    def load(self, formset, state, image=None, formsets=None, image_name=""):
        """Show a form set. `image` is the raw firmware: its font and its tabs."""
        if image is not None:
            self.image = image
            if self.font is None:
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
        """Which forms become the bar across the top.

        A main form that holds nothing but links IS the tab bar - that is what
        Setup is, six Refs to Main, Advanced, Chipset and the rest. A main form
        that also holds real entries is a page in its own right, and its
        children are submenus reached with Enter, not tabs.

        WARNING: taking the children as tabs in both cases threw the main page
        away. On the menu MeiMeiDXEv3 adds, that meant landing on the eight core
        checkboxes and never seeing ACPI Patch, SMU Unlock and Core Unlock,
        which are the reason the mod exists.
        """
        if not formset:
            self.tabs = []
            return
        main = formset.main_form
        # The tabs the setup engine really shows are listed in AMITSE, not in
        # the IFR. When that list can be read, it wins: on this board it is the
        # difference between showing Security and showing Chipset, and it is
        # the whole of what the CHIPSETMENU mod changes.
        if self.image is not None:
            numbers = tse.tab_form_ids(self.image, formset.guid)
            real = [formset.forms_by_id[number] for number in numbers
                    if number in formset.forms_by_id
                    and formset.forms_by_id[number] is not main]
            if real:
                self.tabs = real
                self.tabs_from_tse = True
                return
        self.tabs_from_tse = False
        only_links = bool(main and main.questions) and all(
            question.kind == "Ref" for question in main.questions)
        if main and main.children and only_links:
            self.tabs = list(main.children)
        else:
            self.tabs = ([main] if main else []) + [
                form for form in formset.roots if form is not main]

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
        """The rows to draw, and how many were left out and why.

        WARNING: entries with no name at all are skipped. They exist - the
        Save & Exit form of the stock BIOS has thirty-eight of them, mostly
        numerics whose prompt points at an empty string - and the firmware does
        not draw them either. Drawing them fills the screen with anonymous
        "[0]" rows that hide the eight entries that mean something. They are
        counted at the bottom instead, so nothing disappears quietly.
        """
        rows = []
        unnamed = 0
        for question in form.questions:
            if not question.text_label.strip():
                unnamed += 1
                continue
            result = engine.verdict(question, self.state)
            if result.hidden and not self.show_hidden:
                continue
            rows.append((question, result))
        self._unnamed = unnamed
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
        bottom_line = self.notice or self._counts(entries)
        self._write(ROWS - 1, 1, bottom_line[:COLUMNS - 2],
                    ATTR_EDIT if self.notice else ATTR_KEYS)

        if self.popup is not None:
            self._draw_popup()

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

        shown = self.value_text(question)
        if shown is not None:
            text = "[%s]" % shown[:22]
            value_attribute = attribute if selected else (
                ATTR_VALUE if not result.hidden and not result.greyed
                else attribute)
            column = HELP_AT - len(text) - 2
            self._write(row, column, text, value_attribute)
            # While a date or a time is being edited, the part under the cursor
            # is shown in reverse, the way the setup marks it.
            if selected and question.kind in ("Date", "Time"):
                start, length = self._field_span(question, shown)
                self._write(row, column + 1 + start, shown[start:start + length],
                            ATTR_EDIT)

    # ----------------------------------------------------------- the values

    def value_text(self, question):
        """What the setup would print between the brackets, or None."""
        kind = question.kind
        if kind in ("Ref", "Action", "ResetButton", "Subtitle", "Text"):
            return None
        if kind == "Date":
            return self.clock.strftime("%a %m/%d/%Y")
        if kind == "Time":
            return self.clock.strftime("%H:%M:%S")
        if kind == "String":
            return self._read_string(question)
        if kind == "Password":
            # The firmware keeps a hash, not the password. What can honestly be
            # said is whether one has been set, which is what the setup shows.
            raw = self.state.read_bytes(question)
            if raw is None:
                return None
            return "Installed" if any(raw) else "Not Installed"
        raw = self.state.read(question)
        if raw is engine.UNKNOWN:
            return None
        if kind == "CheckBox":
            return "X" if raw else " "
        for option in question.options:
            if option.value == raw:
                if option.text:
                    return option.text
                break
        if kind == "Numeric":
            # The setup prints numbers in decimal; the mask entries of AMD CBS
            # are the exception, and they say so in their own name.
            name = question.text_label.lower()
            if "mask" in name or "address" in name or "value" in name:
                return "0x%X" % raw
            return str(raw)
        return "0x%X" % raw

    def _read_string(self, question):
        """A string entry, decoded from the UCS-2 the firmware stores."""
        raw = self.state.read_bytes(question)
        if raw is None:
            return None
        text = raw.decode("utf-16-le", "replace")
        cut = text.find("\x00")
        return text[:cut] if cut >= 0 else text

    def _field_span(self, question, shown):
        """Which slice of a date or time the cursor is on: (start, length)."""
        if question.kind == "Date":                 # "Sat 08/30/2026"
            spans = [(4, 2), (7, 2), (10, 4)]       # month, day, year
        else:                                       # "19:28:45"
            spans = [(0, 2), (3, 2), (6, 2)]        # hours, minutes, seconds
        return spans[min(self.field, len(spans) - 1)]

    def _counts(self, entries):
        hidden = sum(1 for _q, result in entries if result.hidden)
        total = len(self.current_form.questions)
        unnamed = getattr(self, "_unnamed", 0)
        if self.show_hidden:
            line = T("{shown} entries, {hidden} of them hidden by the firmware",
                     shown=total, hidden=hidden)
        else:
            line = T("{shown} entries shown, {hidden} hidden by the firmware",
                     shown=len(entries), hidden=total - len(entries) - unnamed)
        if unnamed:
            line += ", " + T("{count} with no name", count=unnamed)
        return line

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

    # --------------------------------------------------------------- popup

    def _draw_popup(self):
        """The little window the setup opens on top of the menu."""
        popup = self.popup
        question = popup["question"]
        if popup["kind"] == "options":
            body = [option.text or ("0x%X" % option.value)
                    for option in question.options]
            chosen = popup["index"]
        elif popup["kind"] == "password":
            body = ["*" * len(popup["buffer"]) + "_", "",
                    T("The firmware keeps a hash of the password, not the "
                      "password itself: nothing is written here.")]
            chosen = -1
        elif popup["kind"] == "text":
            longest = question.node.fields.get("maximum") or 0
            body = [popup["buffer"] + "_", "",
                    T("Up to {count} characters", count=longest) if longest else ""]
            chosen = -1
        else:
            limits = ""
            minimum = question.node.fields.get("minimum")
            maximum = question.node.fields.get("maximum")
            if minimum is not None:
                limits = "Range: %s - %s" % (minimum, maximum)
            body = [popup["buffer"] + "_", "", limits]
            chosen = -1

        title = question.text_label.strip()
        width = max([len(title)] + [len(line) for line in body]) + 6
        width = min(max(width, 24), COLUMNS - 8)
        height = len(body) + 4
        top = max(3, (ROWS - height) // 2)
        left = max(2, (COLUMNS - width) // 2)

        self._write(top, left, "╔" + "═" * (width - 2) + "╗", ATTR_POPUP)
        self._write(top + 1, left, "║" + title.center(width - 2) + "║", ATTR_POPUP)
        self._write(top + 2, left, "╠" + "═" * (width - 2) + "╣", ATTR_POPUP)
        for offset, line in enumerate(body):
            row = top + 3 + offset
            attribute = ATTR_POPUP_SEL if offset == chosen else ATTR_POPUP
            self._write(row, left, "║", ATTR_POPUP)
            self._write(row, left + 1, (" " + line).ljust(width - 2), attribute)
            self._write(row, left + width - 1, "║", ATTR_POPUP)
        self._write(top + height - 1, left, "╚" + "═" * (width - 2) + "╝",
                    ATTR_POPUP)

    def _open_editor(self):
        """Enter on an entry: what the setup does depends on the kind."""
        question = self.selected_question()
        if question is None:
            return
        kind = question.kind
        if kind == "CheckBox":
            self._change_value(1)
            return
        if question.options:
            current = self.state.read(question)
            index = 0
            for position, option in enumerate(question.options):
                if option.value == current:
                    index = position
            self.popup = {"kind": "options", "question": question, "index": index}
            return
        if kind == "Numeric":
            self.popup = {"kind": "number", "question": question, "buffer": ""}
            return
        if kind == "String":
            self.popup = {"kind": "text", "question": question,
                          "buffer": self._read_string(question) or ""}
            return
        if kind == "Password":
            self.popup = {"kind": "password", "question": question, "buffer": ""}
            return
        # Date and time are edited in place, like the setup: Tab moves between
        # the parts, plus and minus or the digits change them.

    def _popup_key(self, event):
        popup = self.popup
        key = event.keysym
        question = popup["question"]
        if key == "Escape":
            self.popup = None
        elif popup["kind"] == "options":
            if key == "Up":
                popup["index"] = max(0, popup["index"] - 1)
            elif key == "Down":
                popup["index"] = min(len(question.options) - 1, popup["index"] + 1)
            elif key == "Return":
                try:
                    self.state.set_value(question,
                                         question.options[popup["index"]].value)
                except ValueError:
                    # the firmware refuses the value: the entry keeps the one it had
                    pass
                self.popup = None
        elif popup["kind"] in ("text", "password"):
            longest = question.node.fields.get("maximum") or 32
            if key == "BackSpace":
                popup["buffer"] = popup["buffer"][:-1]
            elif key == "Return":
                if popup["kind"] == "text":
                    self._apply_typed_text(question, popup["buffer"])
                else:
                    # Nothing is written: see the note in the box. Saying it
                    # after the fact would be worse than not offering the box.
                    self.notice = T("Password not written: the firmware stores "
                                    "a hash we cannot compute.")
                self.popup = None
            elif event.char and event.char.isprintable():
                popup["buffer"] = (popup["buffer"] + event.char)[:longest]
        else:
            if key == "BackSpace":
                popup["buffer"] = popup["buffer"][:-1]
            elif key == "Return":
                self._apply_typed_number(question, popup["buffer"])
                self.popup = None
            elif event.char and event.char.isdigit():
                popup["buffer"] = (popup["buffer"] + event.char)[:10]
        self.draw()
        return "break"

    def _apply_typed_text(self, question, text):
        """Write a string entry back as the UCS-2 the firmware expects."""
        longest = question.node.fields.get("maximum") or 0
        if longest:
            text = text[:longest]
        try:
            self.state.write_bytes(question, text.encode("utf-16-le"))
        except ValueError:
            # the firmware refuses the value: the entry keeps the one it had
            pass

    def _apply_typed_number(self, question, text):
        if not text:
            return
        try:
            value = int(text, 0)
        except ValueError:
            return
        minimum = question.node.fields.get("minimum")
        maximum = question.node.fields.get("maximum")
        if minimum is not None and value < minimum:
            value = minimum
        if maximum is not None and value > maximum:
            value = maximum
        try:
            self.state.set_value(question, value)
        except ValueError:
            # the firmware refuses the value: the entry keeps the one it had
            pass

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
        if self.popup is not None:
            return self._popup_key(event)
        self.notice = ""
        key = event.keysym
        question = self.selected_question()
        if key == "Up":
            self.row_index = max(0, self.row_index - 1)
            self.field = 0
        elif key == "Down":
            self.row_index = min(len(self.rows) - 1, self.row_index + 1)
            self.field = 0
        elif key == "Prior":
            self.row_index = max(0, self.row_index - 10)
        elif key == "Next":
            self.row_index = min(len(self.rows) - 1, self.row_index + 10)
        elif key == "Home":
            self.row_index = 0
        elif key == "End":
            self.row_index = max(0, len(self.rows) - 1)
        elif key in ("Left", "Right"):
            # Inside a date or a time these move between its parts; at the top
            # of a tab they change tab. Same keys, same places as the setup.
            if question is not None and question.kind in ("Date", "Time"):
                self.field = (self.field + (1 if key == "Right" else -1)) % 3
            elif len(self.stack) == 1 and self.tabs:
                step = -1 if key == "Left" else 1
                self.tab_index = (self.tab_index + step) % len(self.tabs)
                self.stack = [self.tabs[self.tab_index]]
                self.row_index = 0
        elif key == "Tab":
            self.field = (self.field + 1) % 3
        elif key == "Return":
            return self._enter()
        elif key == "Escape":
            if len(self.stack) > 1:
                self.stack.pop()
                self.row_index = 0
        elif key in ("plus", "KP_Add", "equal"):
            self._change_value(1)
        elif key in ("minus", "KP_Subtract"):
            self._change_value(-1)
        elif key == "F9":
            if self.state is not None:
                self.state.apply_defaults()
        elif event.char and event.char.isdigit():
            self._typed_digit(question, event.char)
        else:
            return None
        self.draw()
        return "break"

    def _typed_digit(self, question, digit):
        """Typing a digit: on a number it opens the box, on a clock it edits.

        This is what the setup does, and it is the difference between a screen
        you look at and one you use: nobody walks a BIOS pressing plus forty
        times to get a temperature from 20 to 60.
        """
        if question is None:
            return
        if question.kind == "Numeric":
            self.popup = {"kind": "number", "question": question, "buffer": digit}
        elif question.kind in ("Date", "Time"):
            self._type_into_clock(question, digit)

    def _type_into_clock(self, question, digit):
        """Digits typed into the date or the time, one part at a time."""
        buffer_key = (question.kind, self.field)
        if getattr(self, "_clock_key", None) != buffer_key:
            self._clock_key, self._clock_buffer = buffer_key, ""
        self._clock_buffer = (self._clock_buffer + digit)[-4:]
        try:
            number = int(self._clock_buffer)
        except ValueError:
            return
        clock = self.clock
        try:
            if question.kind == "Date":
                if self.field == 0:
                    clock = clock.replace(month=max(1, min(12, number)))
                elif self.field == 1:
                    clock = clock.replace(day=max(1, min(28, number)))
                elif len(self._clock_buffer) == 4:
                    clock = clock.replace(year=max(1998, min(9999, number)))
            else:
                if self.field == 0:
                    clock = clock.replace(hour=min(23, number))
                elif self.field == 1:
                    clock = clock.replace(minute=min(59, number))
                else:
                    clock = clock.replace(second=min(59, number))
        except ValueError:
            return
        self.clock = clock

    def _enter(self, _event=None):
        question = self.selected_question()
        if question is None:
            self.draw()
            return "break"
        if question.kind != "Ref":
            # Enter on anything that is not a link opens its editor: the option
            # list, the number box, or the checkbox flipping over. On the board
            # that is what Enter does, and a menu where Enter does nothing is
            # a picture of a menu.
            self._open_editor()
            self.draw()
            return "break"
        wanted = question.node.fields.get("form")
        target = self.formset.forms_by_id.get(wanted)
        if target is not None:
            # WARNING: a form can be reached again from inside itself - six of
            # the unnamed Refs of Save & Exit point at the form that holds
            # them. Pushing it again grew the stack and the path at the bottom
            # read "Save & Exit > Save & Exit > Save & Exit". Going back to it
            # is the honest move.
            if target in self.stack:
                self.stack = self.stack[:self.stack.index(target) + 1]
            else:
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
        """Plus and minus, on every kind of entry the setup lets you change."""
        question = self.selected_question()
        if question is None:
            return
        kind = question.kind

        if kind in ("Date", "Time"):
            self._step_clock(question, direction)
            return

        if question.options:                       # OneOf, and CheckBox with options
            current = self.state.read(question)
            values = [option.value for option in question.options]
            try:
                position = values.index(current)
            except ValueError:
                position = 0
            position = (position + direction) % len(values)
            self._set(question, values[position])
            return

        if kind == "CheckBox":
            current = self.state.read(question)
            self._set(question, 0 if current else 1)
            return

        if kind == "Numeric":
            current = self.state.read(question)
            if current is engine.UNKNOWN:
                current = question.node.fields.get("minimum") or 0
            step = question.node.fields.get("step") or 1
            minimum = question.node.fields.get("minimum")
            maximum = question.node.fields.get("maximum")
            value = current + step * direction
            # The setup wraps around at the ends instead of stopping dead.
            if minimum is not None and value < minimum:
                value = maximum if maximum is not None else minimum
            elif maximum is not None and value > maximum:
                value = minimum if minimum is not None else maximum
            self._set(question, value)

    def _set(self, question, value):
        try:
            self.state.set_value(question, value)
        except ValueError:
            # the firmware refuses the value: the entry keeps the one it had
            pass

    def _step_clock(self, question, direction):
        """Plus and minus on the part of the date or time under the cursor."""
        clock = self.clock
        try:
            if question.kind == "Date":
                if self.field == 0:
                    month = (clock.month - 1 + direction) % 12 + 1
                    clock = clock.replace(month=month)
                elif self.field == 1:
                    clock = clock + datetime.timedelta(days=direction)
                else:
                    clock = clock.replace(year=max(1998, clock.year + direction))
            else:
                seconds = {0: 3600, 1: 60, 2: 1}[min(self.field, 2)]
                clock = clock + datetime.timedelta(seconds=seconds * direction)
        except ValueError:
            return
        self.clock = clock

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
