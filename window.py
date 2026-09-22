# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""BC-250 BIOS emulator - the window.

What the command line does with commands, this does by looking: open an image,
walk the tree of forms and subforms, pick an entry and read what it does;
change a value and the window says at once which other entries appear and which
disappear.

FOUR THINGS THIS WINDOW DOES AND A REAL BOARD DOES NOT
  1. It shows the HIDDEN entries. On the stock BC-250 BIOS there are 651 of
     them out of 1134: booting the board you cannot see them by definition.
  2. It shows ALL THE SUBFORMS, including those no link leads to. They are the
     majority: in AMD CBS, 66 forms out of 71.
  3. It evaluates the conditions against a state of your choosing - the
     firmware defaults, or the real variable read off a running board.
  4. It compares the menus of two images: not the bytes, the tree of entries.

WARNING: THE SUBFORM HIERARCHY IS NOT IN HOW THE DATA IS NESTED. Inside a form
set all forms are siblings; what links them are the Ref entries. Whoever looks
only at the nesting sees seventy-one forms in a row; the real hierarchy comes
from following the Refs, and hii.py builds it.

Only Python with tkinter is needed: it is already there on Windows, and on
Debian it lives in python3-tk. The theme is the BIOS programmer's: same project.
"""
from __future__ import unicode_literals

import os
import sys
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk

import biosview
import engine
import explain
import hii
import languages
import theme
import volumes

T = languages.T

# The program name is a proper noun: it is not translated, and it is the same
# in the title bar, in the dialogs and in the repository.
APP_NAME = "BC-250 BIOS Compare"

# How the four states of an entry look. The strong colour is spent in one place
# only, as the theme wants.
STATE_COLOURS = {
    "visible": theme.FG,
    "hidden": "#6F8496",
    "read-only": theme.WARN,
    "uncertain": theme.ACCENT,
}


def _state_name(result):
    """The English key of the state: it is also the translation key."""
    if result.uncertain:
        return "uncertain"
    if result.hidden:
        return "hidden"
    if result.greyed:
        return "read-only"
    return "visible"


def _readable(question, state):
    """An entry's value the way the BIOS menu would write it."""
    value = state.read(question)
    if value is engine.UNKNOWN:
        return ""
    for option in question.options:
        if option.value == value:
            return option.text
    return "0x%X" % value


class Application(tk.Tk):

    def __init__(self):
        tk.Tk.__init__(self)
        languages.set_language(languages.read_choice())
        self.geometry("1300x820")
        self.minsize(1040, 640)
        self.configure(background=theme.INK)
        self.theme = theme.Theme(self)
        theme.dark_titlebar(self)

        # --- the program state ---------------------------------------------
        self.path = None
        self.image = None            # the raw firmware, for the BIOS font
        self.formsets = []
        self.formset = None
        self.state = None                # the values we are looking through
        self.start_state = None          # how they were before our changes
        self.variable_path = None
        self.entries = {}                # tree row -> Question
        self.selected = None
        self.explanation = None
        self.counts = {"visible": 0, "hidden": 0, "read-only": 0, "uncertain": 0}
        self.shown = 0
        self.formset_index = 0

        self._tree_style()
        self._build_ui()

    # ================================================================== look

    def _tree_style(self):
        style = ttk.Style(self)
        style.configure("Tree.Treeview", background=theme.PANEL,
                        fieldbackground=theme.PANEL, foreground=theme.FG,
                        font=self.theme.f_text, rowheight=20, borderwidth=0)
        style.configure("Tree.Treeview.Heading", background=theme.PANEL2,
                        foreground=theme.MUT, font=self.theme.f_micro,
                        relief="flat", padding=(6, 4))
        style.map("Tree.Treeview",
                  background=[("selected", theme.ACCENT2)],
                  foreground=[("selected", "#FFFFFF")])
        style.map("Tree.Treeview.Heading", background=[("active", theme.ACTIVE)])
        # clam draws a light border around the Treeview that looks like a crack
        # on a dark background. No colour turns it off: the element is removed
        # from the layout, leaving only the row area.
        style.layout("Tree.Treeview",
                     [("Tree.Treeview.treearea", {"sticky": "nswe"})])
        # The scrollbar has to be dressed separately: the stock one is light and
        # on the slate background it reads as a line of light.
        style.configure("Tree.Vertical.TScrollbar", background=theme.PANEL2,
                        troughcolor=theme.PANEL, bordercolor=theme.PANEL,
                        darkcolor=theme.PANEL2, lightcolor=theme.PANEL2,
                        arrowcolor=theme.MUT, gripcount=0, relief="flat")
        style.map("Tree.Vertical.TScrollbar",
                  background=[("active", theme.ACTIVE)])
        # The notebook tabs: stock clam draws them light grey, which on the
        # slate background looks like a different program.
        style.configure("TNotebook", background=theme.INK, borderwidth=0,
                        tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=theme.PANEL,
                        foreground=theme.MUT, font=self.theme.f_micro,
                        padding=(14, 6), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", theme.PANEL2)],
                  foreground=[("selected", theme.FG)])

    def _build_ui(self):
        """Draw the whole window. Called again to change language.

        Redrawing everything instead of relabelling widget by widget is cruder
        but leaves nothing behind: with twenty labels scattered around, the one
        that gets forgotten is always found by the user, never by the person
        who wrote the code.
        """
        for child in list(self.winfo_children()):
            # WARNING: secondary windows are children of the root: destroying
            # every child would also close them, and whoever changes language
            # would watch the explanation they were reading disappear.
            if isinstance(child, tk.Toplevel):
                continue
            child.destroy()
        self.title(APP_NAME)
        self._header()
        self._toolbar()
        self._body()
        self._footer()
        if self.formset is not None:
            self._fill_formset_choice()
            self.fill_tree()
        else:
            self._update_footer()

    def _header(self):
        canvas = tk.Canvas(self, height=58, highlightthickness=0, bd=0,
                           background=theme.INK)
        canvas.pack(fill="x")
        title = APP_NAME
        subtitle = T("the menus of a firmware image, including the entries "
                     "the BIOS hides")

        def redraw(_event=None):
            canvas.delete("all")
            theme.gradient(canvas, max(canvas.winfo_width(), 1), 58)
            canvas.create_text(18, 20, anchor="w", text=title,
                               fill=theme.FG, font=self.theme.f_title)
            canvas.create_text(19, 40, anchor="w", text=subtitle,
                               fill=theme.MUT, font=self.theme.f_subtitle)
        canvas.bind("<Configure>", redraw)

    def _toolbar(self):
        bar = tk.Frame(self, background=theme.INK)
        bar.pack(fill="x", padx=14, pady=(10, 6))

        ttk.Button(bar, text=T("Open image..."), style="Primary.TButton",
                   command=self.open_image).pack(side="left")
        self.file_label = ttk.Label(
            bar, text=self.path or T("no image open"), style="Subtitle.TLabel")
        self.file_label.pack(side="left", padx=(12, 0))

        # On the right, in reverse order: they pack from the right.
        self.language_choice = ttk.Combobox(
            bar, state="readonly", width=13, font=self.theme.f_text,
            values=[languages.language_name(code) for code in languages.CODES])
        self.language_choice.current(languages.CODES.index(languages.current()))
        self.language_choice.pack(side="right")
        self.language_choice.bind("<<ComboboxSelected>>",
                                  lambda _e: self.change_language())
        tk.Label(bar, text=theme.micro(T("language")), background=theme.INK,
                 foreground=theme.MUT, font=self.theme.f_micro).pack(side="right",
                                                                     padx=(18, 8))
        ttk.Button(bar, text=T("Export JSON..."), style="Ghost.TButton",
                   command=self.export).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text=T("Compare with..."), style="Secondary.TButton",
                   command=self.compare).pack(side="right", padx=(0, 8))

        second = tk.Frame(self, background=theme.INK)
        second.pack(fill="x", padx=14, pady=(0, 8))

        tk.Label(second, text=theme.micro(T("menu")), background=theme.INK,
                 foreground=theme.MUT, font=self.theme.f_micro).pack(side="left")
        self.formset_choice = ttk.Combobox(second, state="readonly", width=34,
                                           font=self.theme.f_text)
        self.formset_choice.pack(side="left", padx=(8, 18))
        self.formset_choice.bind("<<ComboboxSelected>>",
                                 lambda _e: self.change_formset())

        tk.Label(second, text=theme.micro(T("values")), background=theme.INK,
                 foreground=theme.MUT, font=self.theme.f_micro).pack(side="left")
        self.source = tk.StringVar(
            value="variable" if self.variable_path else "defaults")
        ttk.Radiobutton(second, text=T("firmware defaults"), value="defaults",
                        variable=self.source, style="Ink.TRadiobutton",
                        command=self.change_source).pack(side="left", padx=(8, 4))
        ttk.Radiobutton(second, text=T("board variable"), value="variable",
                        variable=self.source, style="Ink.TRadiobutton",
                        command=self.change_source).pack(side="left")
        ttk.Button(second, text=T("Load variable..."), style="Ghost.TButton",
                   command=self.load_variable).pack(side="left", padx=(6, 18))

        self.show_hidden = tk.IntVar(value=1)
        theme.CheckBox(second, self.theme, self.show_hidden,
                       T("show hidden entries"), command=self.fill_tree,
                       background=theme.INK).pack(side="left")

        tk.Label(second, text=theme.micro(T("search")), background=theme.INK,
                 foreground=theme.MUT, font=self.theme.f_micro).pack(side="left",
                                                                     padx=(18, 8))
        self.search = tk.StringVar()
        ttk.Entry(second, textvariable=self.search, width=24,
                  font=self.theme.f_text).pack(side="left")
        self.search.trace_add("write", lambda *_: self.fill_tree())

    def _body(self):
        split = tk.PanedWindow(self, orient="horizontal", background=theme.INK,
                               sashwidth=6, bd=0, sashrelief="flat",
                               showhandle=False)
        split.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # --- left: two ways of looking at the same menu --------------------
        # The tree answers "what is in this image", the BIOS view answers
        # "what would I see sitting in front of the board". They share the
        # state, so a value changed in one shows up in the other.
        self.views = ttk.Notebook(split)
        split.add(self.views, minsize=520, stretch="always")

        tree_page = tk.Frame(self.views, background=theme.INK)
        self.views.add(tree_page, text="  %s  " % T("Menu tree"))
        left, left_body = theme.card(tree_page, T("menu entries"), self.theme)
        left.pack(fill="both", expand=True)

        self.bios = biosview.BiosView(self.views, on_select=self._bios_selected,
                                      on_formset_change=self._bios_crossed)
        self.views.add(self.bios, text="  %s  " % T("BIOS view"))
        self.views.bind("<<NotebookTabChanged>>", lambda _e: self._view_changed())

        columns = ("offset", "value", "state")
        self.tree = ttk.Treeview(left_body, columns=columns,
                                 style="Tree.Treeview", show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text=theme.micro(T("entry")), anchor="w")
        self.tree.heading("offset", text=theme.micro(T("offset")), anchor="w")
        self.tree.heading("value", text=theme.micro(T("value")), anchor="w")
        self.tree.heading("state", text=theme.micro(T("state")), anchor="w")
        self.tree.column("#0", width=400, minwidth=220, stretch=True)
        self.tree.column("offset", width=96, minwidth=80, stretch=False)
        self.tree.column("value", width=150, minwidth=90, stretch=False)
        self.tree.column("state", width=104, minwidth=70, stretch=False)

        bar = ttk.Scrollbar(left_body, orient="vertical", command=self.tree.yview,
                            style="Tree.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        for name, colour in STATE_COLOURS.items():
            self.tree.tag_configure(name, foreground=colour)
        self.tree.tag_configure("form", foreground=theme.ACCENT)
        self.tree.tag_configure("orphan_form", foreground=theme.WARN)
        self.tree.tag_configure("changed", background="#1D3346")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_details())
        self.tree.bind("<Double-1>", lambda _e: self.open_explanation())

        # --- right: the details of the entry -------------------------------
        right = tk.Frame(split, background=theme.INK)
        split.add(right, minsize=360, width=440, stretch="never")

        entry_card, self.panel = theme.card(right, T("selected entry"), self.theme)
        entry_card.pack(fill="both", expand=True)

        effect_card, effect_body = theme.card(right, T("effect of changes"),
                                              self.theme)
        effect_card.pack(fill="both", expand=True, pady=(8, 0))
        self.effect = tk.Text(effect_body, height=8, background=theme.LOG_BG,
                              foreground=theme.MUT, font=self.theme.f_log,
                              relief="flat", wrap="word", highlightthickness=0,
                              insertbackground=theme.FG)
        self.effect.pack(fill="both", expand=True)
        self.effect.tag_configure("appears", foreground=theme.OK)
        self.effect.tag_configure("disappears", foreground=theme.CRIT)
        self.effect.tag_configure("muted", foreground=theme.MUT)
        self.effect.configure(state="disabled")
        self._write_effect([("muted", T("No changes: values are the starting ones."))])
        self._clear_panel(T("Open an image and choose an entry."))

    def _footer(self):
        footer = tk.Frame(self, background=theme.BAR, height=26)
        footer.pack(fill="x", side="bottom")
        self.status = tk.Label(footer, text="", background=theme.BAR,
                               foreground=theme.MUT, font=self.theme.f_small,
                               anchor="w")
        self.status.pack(side="left", padx=14, pady=5)

    # ============================================================== language

    def change_language(self):
        index = self.language_choice.current()
        if index < 0:
            return
        code = languages.CODES[index]
        languages.set_language(code)
        languages.write_choice(code)
        selected = self.selected
        # The explanation window has labels of its own: it is rebuilt from
        # scratch, rather than translating its text and leaving the buttons in
        # the previous language.
        explanation_open = (self.explanation is not None
                            and self.explanation.winfo_exists())
        if explanation_open:
            self.explanation.destroy()
            self.explanation = None
        self._build_ui()
        if selected is not None:
            self._reselect(selected)
        if explanation_open and self.selected is not None:
            self.open_explanation()

    def _reselect(self, question):
        for row, candidate in self.entries.items():
            if candidate is question:
                self.tree.see(row)
                self.tree.selection_set(row)
                # WARNING: selection_set fires <<TreeviewSelect>>, but only on
                # the next turn of the event loop: a caller looking straight
                # afterwards would still find nothing selected. Update by hand.
                self.show_details()
                return

    # ================================================================== data

    def open_image(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title=T("BIOS image of the BC-250"),
                filetypes=[(T("Firmware images"), "*.rom *.ROM *.bin *.BIN"),
                           (T("All files"), "*.*")])
        if not path:
            return
        self._say(T("opening {file}...", file=os.path.basename(path)))
        self.update_idletasks()
        try:
            image = volumes.read_image(path)
            formsets = hii.open_image(image)
        except Exception as error:                         # noqa: BLE001
            messagebox.showerror(APP_NAME, T(
                "Cannot read {file}.\n\n{errore}\n\nA whole 16 MiB flash image "
                "is needed, not a piece already cut out.",
                file=os.path.basename(path), errore=error))
            self._update_footer()
            return
        if not formsets:
            messagebox.showwarning(APP_NAME, T(
                "No menu found in {file}.\n\nThe menus live in the UEFI volume, "
                "which this program finds by itself: if it finds none, either "
                "the image is not from a BC-250, or it has been cut.",
                file=os.path.basename(path)))
            self._update_footer()
            return

        self.path = path
        self.image = image
        self.formsets = formsets
        self.variable_path = None
        self.source.set("defaults")
        self.file_label.configure(text=path)
        self.formset_index = 0
        self._fill_formset_choice()
        self.change_formset()

    def _fill_formset_choice(self):
        self.formset_choice.configure(
            values=["%d - %s (%d)" % (index, formset.title, len(formset.questions))
                    for index, formset in enumerate(self.formsets)])
        if self.formsets:
            self.formset_choice.current(min(self.formset_index,
                                            len(self.formsets) - 1))

    def change_formset(self):
        index = self.formset_choice.current()
        if index < 0:
            return
        self.formset_index = index
        self.formset = self.formsets[index]
        self._prepare_state()
        self.fill_tree()

    def _prepare_state(self):
        self.state = engine.State(self.formset)
        self.state.apply_defaults()
        if self.source.get() == "variable" and self.variable_path:
            try:
                self._apply_variable(self.variable_path)
            except Exception as error:                     # noqa: BLE001
                messagebox.showwarning(APP_NAME, str(error))
                self.source.set("defaults")
                self.variable_path = None
        self.start_state = self.state.copy()
        self.selected = None

    def _apply_variable(self, path):
        with open(path, "rb") as variable_file:
            data = variable_file.read()
        candidates = [store for store in self.formset.varstores.values()
                      if store.size and len(data) in (store.size, store.size + 4)]
        if not candidates:
            sizes = ", ".join("%s=%d" % (store.name, store.size)
                              for store in self.formset.varstores.values())
            raise ValueError(T(
                "The file is {misura} bytes and matches no variable of this "
                "menu.\nHere we need: {attese}.\n\nOn the board the variable is "
                "read like this (scp does not copy it, efivarfs does not allow "
                "that):\n  ssh root@board \"base64 -w0 "
                "/sys/firmware/efi/efivars/NAME-GUID\" | base64 -d > variable.bin",
                misura=len(data), attese=sizes))
        self.state.load_variable(candidates[0].identifier, data)

    def load_variable(self):
        if self.formset is None:
            messagebox.showinfo(APP_NAME,
                                T("First open a BIOS image."))
            return
        path = filedialog.askopenfilename(
            title=T("Variable read from the board"),
            filetypes=[(T("UEFI variable"), "*.bin"), (T("All files"), "*.*")])
        if not path:
            return
        try:
            self._apply_variable(path)
        except Exception as error:                         # noqa: BLE001
            messagebox.showwarning(APP_NAME, str(error))
            return
        self.variable_path = path
        self.source.set("variable")
        self.start_state = self.state.copy()
        self.fill_tree()

    def change_source(self):
        if self.formset is None:
            return
        if self.source.get() == "variable" and not self.variable_path:
            self.load_variable()
            if not self.variable_path:
                self.source.set("defaults")
            return
        self._prepare_state()
        self.fill_tree()

    # ================================================================== tree

    def fill_tree(self):
        """Redraw the tree: forms, subforms and entries.

        The tree follows the real hierarchy (the Refs), and puts at the bottom
        the forms no link leads to: they are the majority and must not be lost,
        but they must not be mixed in with the reachable ones either, or it
        stops being clear what the BIOS would actually show.
        """
        if self.formset is None:
            return
        self.tree.delete(*self.tree.get_children())
        self.entries = {}
        wanted = self.search.get().strip().lower()
        show_hidden = bool(self.show_hidden.get())
        self.counts = {"visible": 0, "hidden": 0, "read-only": 0, "uncertain": 0}
        self.shown = 0

        verdicts = {}
        for question in self.formset.questions:
            result = engine.verdict(question, self.state)
            verdicts[id(question)] = result
            self.counts[_state_name(result)] += 1

        def keep(question):
            result = verdicts[id(question)]
            if not show_hidden and result.hidden:
                return False
            if wanted and wanted not in question.text_label.lower() \
                    and wanted not in question.help_text.lower():
                return False
            return True

        def add_form(form, parent, orphan=False):
            """Add the form and its children. Returns how many entries showed."""
            tags = ("orphan_form",) if orphan else ("form",)
            label = form.title
            if orphan:
                label = "%s  -  %s" % (label, T("not linked from any menu"))
            row = self.tree.insert(parent, "end", text=label, open=not parent,
                                   tags=tags)
            count = 0
            for question in form.questions:
                if not keep(question):
                    continue
                result = verdicts[id(question)]
                name = _state_name(result)
                entry_tags = [name]
                if self.start_state is not None:
                    before = _state_name(engine.verdict(question, self.start_state))
                    if before != name:
                        entry_tags.append("changed")
                position = ("0x%03X : %d" % (question.offset, question.width)
                            if question.offset is not None and question.width
                            else "")
                child = self.tree.insert(
                    row, "end", text=question.text_label,
                    values=(position, _readable(question, self.state),
                            "" if name == "visible" else T(name)),
                    tags=tuple(entry_tags))
                self.entries[child] = question
                count += 1
                self.shown += 1
            for subform in form.children:
                count += add_form(subform, row)
            if not count:
                # A form with nothing left to see (because of the filter, or
                # because it is all hidden) goes away: a tree full of empty
                # branches reads worse than a short one.
                self.tree.delete(row)
            # WARNING: entries are counted where they are inserted, not here:
            # `count` already includes the subforms, and adding it at every
            # level counts them once per ancestor. On the Setup form set that
            # made it say "703 rows" for 283 entries.
            return count

        main = self.formset.main_form
        if main is not None:
            add_form(main, "")
        for orphan in self.formset.orphan_forms:
            add_form(orphan, "", orphan=True)

        self._update_footer()
        self.show_details()
        self._refresh_bios_view()

    def _refresh_bios_view(self):
        """Keep the BIOS view on the same form set and the same values."""
        view = getattr(self, "bios", None)
        if view is None or self.formset is None:
            return
        view.set_show_hidden(bool(self.show_hidden.get()))
        if view.formset is not self.formset:
            view.load(self.formset, self.state, image=self.image,
                      formsets=self.formsets,
                      image_name=os.path.basename(self.path or ""))
        else:
            view.set_state(self.state)

    def _bios_selected(self, question):
        """The BIOS view moved: the details panel follows it."""
        if question is None:
            return
        self.selected = question
        if self.views.index(self.views.select()) == 1:
            self._show_details_for(question)
            self._tell_effect()

    def _bios_crossed(self, formset, form):
        """A Ref led into another form set: follow it, state and all."""
        if formset not in self.formsets:
            return
        self.formset_index = self.formsets.index(formset)
        self.formset_choice.current(self.formset_index)
        self.formset = formset
        self._prepare_state()
        self.fill_tree()
        self.bios.load(formset, self.state, image=self.image,
                       formsets=self.formsets,
                       image_name=os.path.basename(self.path or ""))
        self.bios.go_to(formset, form, self.state)
        self._update_footer()

    def _view_changed(self):
        """Switching view keeps the selection and gives the keyboard focus."""
        if self.formset is None:
            return
        if self.views.index(self.views.select()) == 1:
            self._refresh_bios_view()
            self.bios.screen.focus_set()
        else:
            self.fill_tree()
            if self.selected is not None:
                self._reselect(self.selected)

    def _update_footer(self):
        if self.formset is None:
            self.status.configure(text=T("no image open"))
            return
        source = (os.path.basename(self.variable_path)
                  if self.source.get() == "variable" and self.variable_path
                  else T("firmware defaults"))
        self.status.configure(text="%s   |   %s   |   %s   |   %s   |   %s" % (
            os.path.basename(self.path or ""), self.formset.title,
            T("{totale} entries: {visibili} visible, {nascoste} hidden, "
              "{spente} read-only, {incerte} uncertain",
              totale=len(self.formset.questions), visibili=self.counts["visible"],
              nascoste=self.counts["hidden"], spente=self.counts["read-only"],
              incerte=self.counts["uncertain"]),
            source, T("{righe} rows shown", righe=self.shown)))

    def _say(self, text):
        self.status.configure(text=text)

    # ============================================================== details

    def _clear_panel(self, message):
        for child in self.panel.winfo_children():
            child.destroy()
        tk.Label(self.panel, text=message, background=theme.PANEL,
                 foreground=theme.MUT, font=self.theme.f_text, wraplength=390,
                 justify="left").pack(anchor="w")

    def show_details(self):
        selection = self.tree.selection()
        question = self.entries.get(selection[0]) if selection else None
        if question is None:
            self._clear_panel(T("Choose an entry in the tree."))
            self.selected = None
            return
        self._show_details_for(question)

    def _show_details_for(self, question):
        """Fill the panel for one entry, whichever view chose it."""
        self.selected = question
        for child in self.panel.winfo_children():
            child.destroy()

        result = engine.verdict(question, self.state)
        name = _state_name(result)

        tk.Label(self.panel, text=question.text_label, background=theme.PANEL,
                 foreground=theme.FG, font=(self.theme.ui, 10, "bold"),
                 wraplength=390, justify="left", anchor="w").pack(fill="x")
        tk.Label(self.panel, text="%s - %s" % (question.kind, T(name)),
                 background=theme.PANEL, foreground=STATE_COLOURS[name],
                 font=self.theme.f_text, anchor="w").pack(fill="x", pady=(2, 8))

        store = question.varstore
        rows = [(T("where"), " > ".join(question.path) or "-")]
        if store is not None and question.offset is not None:
            rows += [
                (T("variable"), store.name),
                (T("guid"), store.guid),
                (T("position"), "0x%03X + %d" % (question.offset, question.width)),
                (T("in the file"), "0x%03X" % (question.offset + 4)),
            ]
        if "minimum" in question.node.fields:
            rows.append((T("range"), "%s .. %s" % (question.node.fields.get("minimum"),
                                                   question.node.fields.get("maximum"))))
        for label, value in rows:
            row = tk.Frame(self.panel, background=theme.PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=theme.micro(label), background=theme.PANEL,
                     foreground=theme.MUT, font=self.theme.f_micro, width=17,
                     anchor="w").pack(side="left")
            tk.Label(row, text=value, background=theme.PANEL, foreground=theme.FG,
                     font=self.theme.f_data, anchor="w", wraplength=250,
                     justify="left").pack(side="left", fill="x", expand=True)

        # --- the value, and how to change it ------------------------------
        self.value_widget = None
        if question.options or question.width:
            tk.Frame(self.panel, background=theme.LINE, height=1).pack(
                fill="x", pady=8)
            row = tk.Frame(self.panel, background=theme.PANEL)
            row.pack(fill="x")
            tk.Label(row, text=theme.micro(T("value")), background=theme.PANEL,
                     foreground=theme.MUT, font=self.theme.f_micro, width=17,
                     anchor="w").pack(side="left")
            current = self.state.read(question)
            if question.options:
                self.value_widget = ttk.Combobox(
                    row, state="readonly", width=22, font=self.theme.f_text,
                    values=["%s  (%s)" % (option.text, option.value)
                            for option in question.options])
                for index, option in enumerate(question.options):
                    if option.value == current:
                        self.value_widget.current(index)
            else:
                self.value_widget = ttk.Entry(row, width=22, font=self.theme.f_text)
                if current is not engine.UNKNOWN:
                    self.value_widget.insert(0, "0x%X" % current)
            self.value_widget.pack(side="left", fill="x", expand=True)

            buttons = tk.Frame(self.panel, background=theme.PANEL)
            buttons.pack(fill="x", pady=(8, 0))
            ttk.Button(buttons, text=T("Apply"), style="Secondary.TButton",
                       command=self.apply_value).pack(side="left")
            ttk.Button(buttons, text=T("Reset to starting values"),
                       style="Ghost.TButton",
                       command=self.reset_values).pack(side="left", padx=(8, 0))

        ttk.Button(self.panel, text=T("Explain in detail..."),
                   style="Primary.TButton",
                   command=self.open_explanation).pack(anchor="w", pady=(10, 0))

        if question.help_text:
            tk.Frame(self.panel, background=theme.LINE, height=1).pack(
                fill="x", pady=8)
            tk.Label(self.panel, text=question.help_text, background=theme.PANEL,
                     foreground=theme.MUT, font=self.theme.f_text, wraplength=390,
                     justify="left", anchor="w").pack(fill="x")

        if self.explanation is not None and self.explanation.winfo_exists():
            self.explanation.rebuild(question, self.formset, self.state)

    def open_explanation(self):
        if self.selected is None:
            return
        if self.explanation is None or not self.explanation.winfo_exists():
            self.explanation = ExplanationWindow(self)
        self.explanation.rebuild(self.selected, self.formset, self.state)
        self.explanation.lift()

    # ============================================================== changes

    def apply_value(self):
        question = self.selected
        if question is None or self.value_widget is None:
            return
        if question.options:
            index = self.value_widget.current()
            if index < 0:
                return
            value = question.options[index].value
        else:
            text = self.value_widget.get().strip()
            try:
                value = int(text, 0)
            except ValueError:
                messagebox.showwarning(APP_NAME,
                                       T("{testo} is not a number. Write 12 or "
                                         "0x0C.", testo=text))
                return
        try:
            self.state.set_value(question, value)
        except ValueError as error:
            messagebox.showwarning(APP_NAME, str(error))
            return
        self.fill_tree()
        self._reselect(question)
        self._tell_effect()

    def reset_values(self):
        if self.start_state is None:
            return
        self.state = self.start_state.copy()
        self.fill_tree()
        self._write_effect([("muted", T("No changes: values are the starting ones."))])

    def _tell_effect(self):
        appeared, disappeared, ungreyed, greyed = engine.differences(
            self.formset, self.start_state, self.state)
        rows = []
        if not (appeared or disappeared or ungreyed or greyed):
            rows.append(("muted", T("Values changed, but no entry changes state: "
                                    "this choice governs no other one.")))
        else:
            rows.append(("muted", T("With respect to the starting values:")))
            for label, group, tag in (
                    (T("appears"), appeared, "appears"),
                    (T("disappears"), disappeared, "disappears"),
                    (T("becomes editable"), ungreyed, "appears"),
                    (T("becomes read-only"), greyed, "disappears")):
                for question in group:
                    rows.append((tag, "  %-12s %s" % (label, question.text_label)))
        self._write_effect(rows)

    def _write_effect(self, rows):
        self.effect.configure(state="normal")
        self.effect.delete("1.0", "end")
        for tag, text in rows:
            self.effect.insert("end", text + "\n", tag)
        self.effect.configure(state="disabled")

    # ============================================================ comparison

    def compare(self):
        if self.formset is None:
            messagebox.showinfo(APP_NAME,
                                T("First open a BIOS image."))
            return
        path = filedialog.askopenfilename(
            title=T("Second image to compare"),
            filetypes=[(T("Firmware images"), "*.rom *.ROM *.bin *.BIN"),
                       (T("All files"), "*.*")])
        if not path:
            return
        self._say(T("comparing..."))
        self.update_idletasks()
        try:
            others = hii.open_image(volumes.read_image(path))
        except Exception as error:                         # noqa: BLE001
            messagebox.showerror(APP_NAME, T(
                "Cannot read {file}.\n\n{errore}\n\nA whole 16 MiB flash image "
                "is needed, not a piece already cut out.",
                file=os.path.basename(path), errore=error))
            self._update_footer()
            return
        CompareWindow(self, self.path, self.formsets, path, others)
        self._update_footer()

    def export(self):
        if not self.formsets:
            messagebox.showinfo(APP_NAME,
                                T("First open a BIOS image."))
            return
        path = filedialog.asksaveasfilename(
            title=T("Where should I write the JSON"), defaultextension=".json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        import argparse
        import emulator
        emulator.command_export(argparse.Namespace(image=self.path, output=path))
        self._say(T("written {file}", file=path))


# ====================================================== explanation window

class ExplanationWindow(tk.Toplevel):
    """Everything that can be said about an entry, in one window.

    It keeps the two sources apart - what the firmware says and what we know -
    and when the hand-written card is missing, it says so. See explain.py for
    why that distinction matters.
    """

    def __init__(self, parent):
        tk.Toplevel.__init__(self, parent)
        self.parent = parent
        self.title(T("Detailed explanation"))
        self.geometry("760x820")
        self.minsize(520, 420)
        self.configure(background=theme.INK)
        self.theme = parent.theme
        theme.dark_titlebar(self)

        container, body = theme.card(self, T("Detailed explanation"), self.theme)
        container.pack(fill="both", expand=True, padx=14, pady=(12, 8))
        self.text = tk.Text(body, background=theme.LOG_BG, foreground=theme.FG,
                            font=self.theme.f_text, relief="flat", wrap="word",
                            highlightthickness=0, padx=14, pady=12,
                            spacing1=2, spacing3=6, insertbackground=theme.FG)
        bar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview,
                            style="Tree.Vertical.TScrollbar")
        self.text.configure(yscrollcommand=bar.set)
        self.text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        self.text.tag_configure("title", foreground=theme.FG,
                                font=(self.theme.ui, 12, "bold"),
                                spacing1=4, spacing3=8)
        self.text.tag_configure("section", foreground=theme.ACCENT,
                                font=self.theme.f_micro, spacing1=14, spacing3=6)
        self.text.tag_configure("body", foreground=theme.FG)
        self.text.tag_configure("muted", foreground=theme.MUT)
        self.text.tag_configure("warning", foreground=theme.WARN)
        self.text.tag_configure("severe", foreground=theme.CRIT)
        self.text.tag_configure("data", foreground="#C3D2DE", font=self.theme.f_data)
        self.text.tag_configure("command", foreground=theme.LOG_OK,
                                font=self.theme.f_log, lmargin1=14, lmargin2=14)

        ttk.Button(self, text=T("Close"), style="Secondary.TButton",
                   command=self.destroy).pack(anchor="e", padx=14, pady=(0, 12))

    # --- writing -----------------------------------------------------------

    def _line(self, text, tag="body"):
        self.text.insert("end", text + "\n", tag)

    def _section(self, title):
        self._line(theme.micro(title), "section")

    def rebuild(self, question, formset, state):
        self.title(T("Detailed explanation"))
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if question is None:
            self._line(T("Choose an entry in the tree."), "muted")
            self.text.configure(state="disabled")
            return

        self._line(question.text_label, "title")
        self._line("%s  -  %s" % (question.kind, " > ".join(question.path)), "muted")

        self._card_part(question)
        self._firmware_part(question)
        self._storage_part(question)
        self._options_part(question, state)
        self._visibility_part(question, state)
        self._controls_part(question, formset, state)
        self._commands_part(question, state)
        self.text.configure(state="disabled")

    def _card_part(self, question):
        self._section(T("What this parameter does"))
        text, card_language = explain.card(question.text_label)
        if not text:
            self._line(T("There is no hand-written card for this entry yet. "
                         "Everything below is read from the firmware itself."),
                       "muted")
            return
        if card_language != languages.current():
            self._line(T("This card has not been translated into your language "
                         "yet, so it is shown in English."), "warning")
        for paragraph in text.split("\n\n"):
            # Warning paragraphs are recognised by the alert symbol at their
            # start, not by a word: that way it works in all nine languages.
            tag = "warning" if paragraph.strip().startswith("⚠") else "body"
            self._line(paragraph, tag)

    def _firmware_part(self, question):
        self._section(T("What the firmware says about it"))
        if question.help_text:
            self._line(question.help_text, "body")
        else:
            self._line(T("The firmware gives no help text for this entry."), "muted")

    def _storage_part(self, question):
        self._section(T("Where the value is stored"))
        store = question.varstore
        if store is None or question.offset is None:
            self._line(T("Not stored in any variable: this entry is a link to "
                         "another menu or an action."), "muted")
            return
        self._line("%s   %s" % (store.name, store.guid), "data")
        self._line(T("offset 0x{offset}, {byte} bytes",
                     offset="%03X" % question.offset, byte=question.width), "data")
        self._line(T("The first 4 bytes of the file are the attributes and are "
                     "not part of the variable: offset 0x{offset} of the "
                     "variable is at byte 0x{nel_file} of the file.",
                     offset="%03X" % question.offset,
                     nel_file="%03X" % (question.offset + 4)), "muted")

    def _options_part(self, question, state):
        if question.options:
            self._section(T("The options"))
            current = state.read(question)
            for option in question.options:
                mark = "->" if option.value == current else "  "
                self._line("%s %-28s = %s%s" % (
                    mark, option.text, option.value,
                    "   (%s)" % T("firmware defaults") if option.is_default else ""),
                    "data")
        self._section(T("The defaults"))
        if question.defaults:
            # 0 and 1 are the two default stores UEFI defines; other numbers
            # stay numbers, which beats an invented name.
            names = {0: "standard", 1: "manufacturing"}
            for identifier, value in sorted(question.defaults.items()):
                self._line("%-14s = %s" % (names.get(identifier,
                                                     "id %s" % identifier),
                                           value), "data")
        elif any(option.is_default for option in question.options):
            for option in question.options:
                if option.is_default:
                    self._line("%s = %s" % (option.text, option.value), "data")
        else:
            self._line(T("No explicit default: the firmware keeps whatever it "
                         "finds in the variable."), "muted")

    def _visibility_part(self, question, state):
        self._section(T("Visibility"))
        conditions = explain.conditions(question, state)
        if not conditions:
            self._line(T("This entry is always visible: no condition governs it."),
                       "body")
            return
        for condition in conditions:
            if condition["constant"] and condition["name"] in ("SuppressIf",
                                                               "DisableIf"):
                self._line(T("Hidden by a condition that looks at no variable "
                             "(suppressif TRUE). No variable will ever make it "
                             "appear: that would take changing the firmware "
                             "itself."), "severe")
                continue
            sentence = (T("Hidden while this holds: {condizione}",
                          condizione=condition["expression"])
                        if condition["name"] in ("SuppressIf", "DisableIf")
                        else T("Visible but not modifiable while this holds: "
                               "{condizione}", condizione=condition["expression"]))
            self._line(sentence, "body")
            outcome = condition["outcome"]
            outcome_name = (T("not computable without the firmware running")
                            if outcome is engine.UNKNOWN
                            else (T("true") if outcome else T("false")))
            self._line("   " + T("Right now the condition is {esito}.",
                                 esito=outcome_name), "muted")

    def _controls_part(self, question, formset, state):
        self._section(T("What it controls"))
        rows = explain.controls(formset, question, state)
        if not rows:
            self._line(T("Nothing: no other entry depends on this one."), "muted")
            return
        total = sum(len(group) for _value, _text, *groups in rows for group in groups)
        self._line(T("Changing this entry makes {quante} other entries change "
                     "state:", quante=total), "body")
        for value, value_text, appeared, disappeared, ungreyed, greyed in rows:
            self._line("  " + T("setting it to {valore}: {comparse} appear, "
                                "{sparite} disappear",
                                valore="%s (%s)" % (value_text, value),
                                comparse=len(appeared) + len(ungreyed),
                                sparite=len(disappeared) + len(greyed)), "data")
            for label, group in ((T("appears"), appeared),
                                 (T("disappears"), disappeared),
                                 (T("becomes editable"), ungreyed),
                                 (T("becomes read-only"), greyed)):
                for other in group[:12]:
                    self._line("      %-12s %s" % (label, other.text_label), "muted")
                if len(group) > 12:
                    self._line("      ... +%d" % (len(group) - 12), "muted")

    def _commands_part(self, question, state):
        read = explain.read_command(question)
        if read:
            self._section(T("How to read it on a running board"))
            self._line(read, "command")
        value = state.read(question)
        if value is not engine.UNKNOWN:
            write = explain.write_command(question, value)
            if write:
                self._section(T("How it would be written"))
                self._line(write, "command")
                self._section(T("Warnings"))
                self._line(T("Writing UEFI variables has never been proven on "
                             "this board. Do it only on the development board, "
                             "with the BIOS backup and the external programmer "
                             "ready."), "severe")


# ========================================================= comparison window

class CompareWindow(tk.Toplevel):
    """The differences between the menus of two images, entry by entry.

    It compares the TREES, not the bytes: that is how you see what a modified
    BIOS really adds, instead of only knowing that 1327 KB differ.
    """

    def __init__(self, parent, path_a, formsets_a, path_b, formsets_b):
        tk.Toplevel.__init__(self, parent)
        self.title(T("Menu comparison"))
        self.geometry("1100x700")
        self.configure(background=theme.INK)
        self.theme = parent.theme
        theme.dark_titlebar(self)

        self.a = {formset.title: formset for formset in formsets_a}
        self.b = {formset.title: formset for formset in formsets_b}

        header = tk.Frame(self, background=theme.INK)
        header.pack(fill="x", padx=14, pady=(12, 6))
        for label, path in (("A", path_a), ("B", path_b)):
            tk.Label(header, text="%s   %s" % (label, path),
                     background=theme.INK, foreground=theme.MUT,
                     font=self.theme.f_small, anchor="w").pack(fill="x")

        choice = tk.Frame(self, background=theme.INK)
        choice.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(choice, text=theme.micro(T("menu")), background=theme.INK,
                 foreground=theme.MUT, font=self.theme.f_micro).pack(side="left")
        common = sorted(set(self.a) & set(self.b))
        self.formset_choice = ttk.Combobox(choice, state="readonly", width=40,
                                           values=common, font=self.theme.f_text)
        self.formset_choice.pack(side="left", padx=(8, 0))
        self.formset_choice.bind("<<ComboboxSelected>>", lambda _e: self.fill())

        only_a = sorted(set(self.a) - set(self.b))
        only_b = sorted(set(self.b) - set(self.a))
        if only_a or only_b:
            tk.Label(choice,
                     text="   %s    %s" % (
                         T("menus only in A: {elenco}",
                           elenco=", ".join(only_a) or T("none")),
                         T("menus only in B: {elenco}",
                           elenco=", ".join(only_b) or T("none"))),
                     background=theme.INK, foreground=theme.WARN,
                     font=self.theme.f_small).pack(side="left", padx=(12, 0))

        container, body = theme.card(self, T("differences"), self.theme)
        container.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.table = ttk.Treeview(body, columns=("where", "detail"),
                                  show="tree headings", style="Tree.Treeview")
        self.table.heading("#0", text=theme.micro(T("entry")), anchor="w")
        self.table.heading("where", text=theme.micro(T("where")), anchor="w")
        self.table.heading("detail", text=theme.micro(T("what changes")), anchor="w")
        self.table.column("#0", width=340, stretch=True)
        self.table.column("where", width=250, stretch=False)
        self.table.column("detail", width=430, stretch=True)
        bar = ttk.Scrollbar(body, orient="vertical", command=self.table.yview,
                            style="Tree.Vertical.TScrollbar")
        self.table.configure(yscrollcommand=bar.set)
        self.table.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.table.tag_configure("added", foreground=theme.OK)
        self.table.tag_configure("removed", foreground=theme.CRIT)
        self.table.tag_configure("changed", foreground=theme.WARN)

        self.summary = tk.Label(self, text="", background=theme.BAR,
                                foreground=theme.MUT, font=self.theme.f_small,
                                anchor="w")
        self.summary.pack(fill="x", side="bottom", ipady=5)

        if common:
            preferred = "AMD CBS" if "AMD CBS" in common else common[0]
            self.formset_choice.set(preferred)
            self.fill()

    def fill(self):
        title = self.formset_choice.get()
        if not title:
            return
        self.table.delete(*self.table.get_children())
        inside_a = hii.fingerprint(self.a[title])
        inside_b = hii.fingerprint(self.b[title])

        added = sorted(set(inside_b) - set(inside_a))
        removed = sorted(set(inside_a) - set(inside_b))
        changed = [key for key in sorted(set(inside_a) & set(inside_b))
                   if inside_a[key] != inside_b[key]]

        for key in added:
            self.table.insert("", "end", text="+  " + key[0],
                              values=(inside_b[key]["where"], T("only in B")),
                              tags=("added",))
        for key in removed:
            self.table.insert("", "end", text="-  " + key[0],
                              values=(inside_a[key]["where"], T("only in A")),
                              tags=("removed",))
        for key in changed:
            fields = [field for field in inside_a[key]
                      if inside_a[key][field] != inside_b[key][field]]
            row = self.table.insert(
                "", "end", text="~  " + key[0],
                values=(inside_a[key]["where"], ", ".join(fields)),
                tags=("changed",))
            for field in fields:
                self.table.insert(row, "end", text="      " + field,
                                  values=("A: %s" % (inside_a[key][field],),
                                          "B: %s" % (inside_b[key][field],)))

        if not (added or removed or changed):
            self.table.insert("", "end", text=T("the two menus are identical"),
                              values=("", T("same entries, same offsets, same "
                                            "options, same conditions")))
        self.summary.configure(text="   " + T(
            "{titolo}: {a} entries in A, {b} in B - {agg} added, {tolte} removed, "
            "{cam} changed", titolo=title, a=len(inside_a), b=len(inside_b),
            agg=len(added), tolte=len(removed), cam=len(changed)))


# The name to type is not the same on the two systems, and printing the Windows
# one on a Linux shell sends people looking for a file that is not there.
COMMAND = "Bc250BiosCompare.exe" if os.name == "nt" else "bc250-bios-compare"
# Same for the command line: from a checkout it is a script, from the Debian
# package it is a command, and telling a packaged user to run `python3
# emulator.py` sends them looking for a file that the package does not install.
if os.path.dirname(os.path.abspath(__file__)).startswith("/usr/share/"):
    COMMAND_CLI = "bc250-bios-compare-cli"          # installed from the package
elif os.name == "nt":
    COMMAND_CLI = "python emulator.py"
else:
    COMMAND_CLI = "python3 emulator.py"

HELP = """BC-250 BIOS Compare - the window.

    %s [IMAGE.rom] [--bios]

Pass a BIOS image to open it straight away, or start with no arguments and use
"Open image...". Add --bios to land directly on the BIOS view, the one drawn
with the firmware's own font.

For the command line version - tree, entry, simulate, compare, export - run:
%s --help
""" % (COMMAND, COMMAND_CLI)


def main():
    # ⚠️ An argument starting with "-" is an option, not a file name. Without
    # this check, `--help` was taken for an image and the window answered
    # "cannot read --help", which is true but unhelpful.
    arguments = [argument for argument in sys.argv[1:]
                 if not argument.startswith("-")]
    options = [argument for argument in sys.argv[1:] if argument.startswith("-")]
    if any(option in ("-h", "--help", "/?") for option in options):
        print(HELP)
        # Started from a shortcut there is no console to read: show it anyway -
        # but only if there is a screen to show it on. Asked for the help over
        # ssh with no display, opening a window is not a thing that can be done,
        # and trying answered with a TclError traceback on top of the help that
        # had just been printed correctly.
        try:
            root = tk.Tk()
        except tk.TclError:
            return 0
        root.withdraw()
        messagebox.showinfo(APP_NAME, HELP)
        return 0
    try:
        application = Application()
    except tk.TclError as error:
        # The commonest case by far is a Linux shell with no DISPLAY. Saying
        # which program to use instead is worth more than the Tcl message.
        sys.stderr.write(
            "%s: no display to open a window on (%s).\n"
            "Over ssh, or with no graphical session, use the command line:\n"
            "    %s --help\n" % (APP_NAME, error, COMMAND_CLI))
        return 2
    if arguments:
        application.after(120, lambda: application.open_image(arguments[0]))
        if "--bios" in options:
            # After the image, so the view has something to draw.
            application.after(400, lambda: application.views.select(1))
    application.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
