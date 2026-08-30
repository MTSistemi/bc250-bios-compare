# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""The "instrument panel" dark theme, ported to tkinter.

It is not decoration: it is the visual language we use across our tools. A
monitoring console,
not a generic dashboard: thin rules, spaced small-caps micro labels, numbers
and logs in a fixed-width face, and the strong colour spent in ONE place only.

It comes here from the BIOS programmer: same project, and it should look like
it.
"""
from __future__ import unicode_literals

import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ---------------------------------------------------------------- colours
INK = "#0B1119"        # slate background leaning blue (not neutral grey: on purpose)
PANEL = "#141E29"      # card surface
PANEL2 = "#1A2634"     # raised surface
LINE = "#24323F"       # rules and borders
FG = "#E4EDF4"         # text
MUT = "#8095A6"        # secondary text
ACCENT = "#2F9BE0"     # accent (the house blue, lightened for the dark background)
ACCENT2 = "#0070B0"    # the house blue

OK = "#35B87A"
WARN = "#E0A030"
CRIT = "#E5484D"

OK_BG, OK_BORDER = "#12241C", "#1E4D38"
WARN_BG, WARN_BORDER = "#241D10", "#4D3C1A"
CRIT_BG, CRIT_BORDER = "#251215", "#4F2225"

BAR = "#0E161F"            # sidebar / trough
ACTIVE = "#16273A"
HEADER_FROM, HEADER_TO = "#0F2C42", INK    # 103deg gradient

LOG_BG = "#080D13"
LOG_TIME = "#546B7E"
LOG_OK = "#63C08E"

WINDOW_BORDER = "#1E2A36"


def dark_titlebar(window):
    """A dark title bar, like the rest of the window.

    From Windows 10 1809 on it is asked of the window manager (DWM). The
    attribute is 20 on recent versions and 19 on older ones; if nothing works,
    we live with a light title bar.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        window.update_idletasks()
        handle = ctypes.windll.user32.GetParent(window.winfo_id())
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                handle, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled))
            if result == 0:
                return
    except Exception:                                  # noqa: BLE001
        pass


def micro(text):
    """A micro label: UPPERCASE and letter-spaced.

    tkinter knows nothing about letter-spacing, so it is done by hand with thin
    spaces between the letters. Ugly to write, right to look at.
    """
    return " ".join(text.upper())


def _first_available(root, candidates, fallback):
    present = set(tkfont.families(root))
    for name in candidates:
        if name in present:
            return name
    return fallback


class Theme(object):
    """Holds the chosen fonts and applies the ttk styles."""

    def __init__(self, root):
        self.ui = _first_available(
            root, ["Segoe UI Variable Text", "Segoe UI"], "TkDefaultFont")
        self.mono = _first_available(
            root, ["Cascadia Code", "Cascadia Mono", "Consolas"], "Courier New")

        # Deliberately small sizes: the window has to be wide, not tall.
        self.f_title = (self.ui, 12, "bold")
        self.f_subtitle = (self.ui, 8)
        self.f_text = (self.ui, 8)
        self.f_micro = (self.ui, 7, "bold")
        self.f_small = (self.ui, 7)
        self.f_data = (self.mono, 8)
        self.f_log = (self.mono, 8)
        self.f_button = (self.ui, 8)

        self._apply(root)

    # -------------------------------------------------------------- ttk
    def _apply(self, root):
        root.configure(background=INK)
        style = ttk.Style(root)
        # clam is the only ttk theme that really lets itself be recoloured:
        # vista and xpnative draw with Windows images and ignore background.
        style.theme_use("clam")

        style.configure(".", background=INK, foreground=FG, font=self.f_text,
                        borderwidth=0, focuscolor=ACCENT)
        style.configure("TFrame", background=INK)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("Raised.TFrame", background=PANEL2)

        style.configure("TLabel", background=INK, foreground=FG, font=self.f_text)
        style.configure("Card.TLabel", background=PANEL, foreground=FG)
        style.configure("Micro.TLabel", background=PANEL, foreground=MUT,
                        font=self.f_micro)
        style.configure("MicroInk.TLabel", background=INK, foreground=MUT,
                        font=self.f_micro)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUT,
                        font=(self.ui, 8))
        style.configure("Title.TLabel", background=INK, foreground=FG,
                        font=self.f_title)
        style.configure("Subtitle.TLabel", background=INK, foreground=MUT,
                        font=self.f_subtitle)
        style.configure("Data.TLabel", background=PANEL, foreground=FG,
                        font=self.f_data)

        # --- buttons --------------------------------------------------
        self._button(style, "Primary.TButton", ACCENT2, "#FFFFFF", "#1B6E9F",
                     "#0A80C8", "#0C5F92")
        self._button(style, "Secondary.TButton", "#1D2937", FG, "#2A3846",
                     "#243244", "#18222E")
        self._button(style, "Ghost.TButton", PANEL, "#8FC2E3", "#2A4457",
                     "#17242F", "#111A23")
        self._button(style, "Danger.TButton", CRIT_BG, "#FF9C9F", CRIT_BORDER,
                     "#31171B", "#1E0F12")

        # --- fields ---------------------------------------------------
        for name in ("TEntry", "TCombobox"):
            style.configure(name, fieldbackground=BAR, background=BAR,
                            foreground=FG, bordercolor=LINE, lightcolor=LINE,
                            darkcolor=LINE, insertcolor=FG, arrowcolor=MUT,
                            selectbackground=ACCENT2, selectforeground="#FFFFFF",
                            padding=4)
            style.map(name,
                      bordercolor=[("focus", ACCENT)],
                      lightcolor=[("focus", ACCENT)],
                      darkcolor=[("focus", ACCENT)],
                      fieldbackground=[("disabled", "#101922")],
                      foreground=[("disabled", "#4A5C6B")],
                      arrowcolor=[("disabled", "#3A4A58")])
        # the combobox drop-down is a plain Tk Listbox and is dressed apart
        root.option_add("*TCombobox*Listbox.background", PANEL2)
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT2)
        root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        root.option_add("*TCombobox*Listbox.font", self.f_text)

        # --- radio buttons --------------------------------------------
        for name, background in (("TRadiobutton", PANEL), ("Ink.TRadiobutton", INK)):
            style.configure(name, background=background, foreground=FG,
                            indicatorbackground=BAR, indicatorforeground=ACCENT,
                            bordercolor=LINE, font=self.f_text, padding=2)
            style.map(name, background=[("active", background)],
                      indicatorbackground=[("selected", ACCENT),
                                           ("active", PANEL2)])

        # --- progress bar ---------------------------------------------
        style.configure("Thin.Horizontal.TProgressbar", troughcolor=BAR,
                        background=ACCENT, bordercolor=BAR, lightcolor=ACCENT,
                        darkcolor=ACCENT2, thickness=5)

        # --- scrollbars ------------------------------------------------
        style.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=INK,
                        bordercolor=INK, arrowcolor=MUT, gripcount=0)
        style.map("Vertical.TScrollbar", background=[("active", "#28394A")])
        style.configure("Horizontal.TScrollbar", background=PANEL2, troughcolor=INK,
                        bordercolor=INK, arrowcolor=MUT, gripcount=0)

        style.configure("TSeparator", background=LINE)

    @staticmethod
    def _button(style, name, background, text, border, hover, pressed):
        style.configure(name, background=background, foreground=text,
                        bordercolor=border, lightcolor=background,
                        darkcolor=background, focusthickness=1, focuscolor=border,
                        padding=(11, 6), relief="flat")
        style.map(name,
                  background=[("pressed", pressed), ("active", hover),
                              ("disabled", "#141C25")],
                  foreground=[("disabled", "#43535F")],
                  bordercolor=[("disabled", "#1B242E")],
                  lightcolor=[("pressed", pressed), ("active", hover)],
                  darkcolor=[("pressed", pressed), ("active", hover)])


# ------------------------------------------------------------- widgets

def card(parent, title=None, theme=None):
    """A card: --panel background, --line rule, micro-label heading.

    Returns (outer container, body). Content goes into the body.
    """
    outer = tk.Frame(parent, background=PANEL, highlightbackground=LINE,
                     highlightcolor=LINE, highlightthickness=1, bd=0)
    body = tk.Frame(outer, background=PANEL)
    if title is not None:
        head = tk.Frame(outer, background=PANEL)
        head.pack(fill="x", padx=12, pady=(9, 0))
        label = tk.Label(head, text=micro(title), background=PANEL,
                         foreground=MUT, font=theme.f_micro if theme else None,
                         anchor="w")
        label.pack(side="left")
        tk.Frame(outer, background=LINE, height=1).pack(fill="x", padx=12,
                                                        pady=(7, 0))
        outer.title_label = label
    body.pack(fill="both", expand=True, padx=12, pady=10)
    outer.body = body
    return outer, body


class Chip(tk.Frame):
    """A status pill: coloured dot plus text."""

    def __init__(self, parent, theme, background=PANEL):
        tk.Frame.__init__(self, parent, background=background)
        self.theme = theme
        self.background = background
        self.pill = tk.Frame(self, background=background, highlightthickness=1,
                             highlightbackground=background, bd=0)
        self.dot = tk.Canvas(self.pill, width=8, height=8, highlightthickness=0,
                             background=background, bd=0)
        self.dot.pack(side="left", padx=(8, 6), pady=4)
        self.label = tk.Label(self.pill, background=background, foreground=MUT,
                              font=theme.f_text, anchor="w", justify="left",
                              wraplength=820)
        self.label.pack(side="left", padx=(0, 10), pady=3)
        self.pill.pack(anchor="w")
        self.hide()

    def hide(self):
        self.pill.pack_forget()

    def show(self, text, colour=MUT, background=None, border=None):
        fill = background or self.background
        self.pill.configure(background=fill, highlightbackground=border or fill)
        self.dot.configure(background=fill)
        self.label.configure(background=fill, foreground=colour, text=text)
        self.dot.delete("all")
        self.dot.create_oval(1, 1, 7, 7, fill=colour, outline="")
        self.pill.pack(anchor="w")


class CheckBox(tk.Frame):
    """A hand-drawn check box: 15px, 3px corners, the tick traced.

    ttk.Checkbutton on clam shows a system box that clashes with everything
    else; this is the design system's box, drawn on a Canvas.
    """

    SIDE = 15

    def __init__(self, parent, theme, variable, text="", command=None,
                 background=PANEL, colour=FG):
        tk.Frame.__init__(self, parent, background=background, cursor="hand2")
        self.var = variable
        self.command = command
        self.colour = colour
        self.canvas = tk.Canvas(self, width=self.SIDE + 2, height=self.SIDE + 2,
                                highlightthickness=0, background=background, bd=0)
        self.canvas.pack(side="left")
        self.label = tk.Label(self, text=text, background=background,
                              foreground=colour, font=theme.f_text)
        self.label.pack(side="left", padx=(8, 0))
        for widget in (self, self.canvas, self.label):
            widget.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *_: self.redraw())
        self.redraw()

    def configure(self, cnf=None, **kw):
        """Also accepts `text=`, so a translator can treat it like the others."""
        text = kw.pop("text", None)
        if text is not None:
            self.label.configure(text=text)
        if cnf or kw:
            return tk.Frame.configure(self, cnf, **kw)
        return None

    config = configure

    def _toggle(self, _event=None):
        if str(self.label.cget("state")) == "disabled":
            return
        self.var.set(0 if self.var.get() else 1)
        if self.command:
            self.command()

    def redraw(self):
        canvas = self.canvas
        canvas.delete("all")
        on = bool(self.var.get())
        border, side = 1, self.SIDE
        canvas.create_rectangle(border, border, border + side, border + side,
                                fill=ACCENT if on else BAR,
                                outline=ACCENT if on else LINE, width=1)
        if on:
            # the tick is traced by hand, not a font character
            canvas.create_line(border + 3.5, border + 7.5, border + 6.2,
                               border + 10.5, border + 11.5, border + 4.5,
                               fill="#08131C", width=2, capstyle="round",
                               joinstyle="round")


def gradient(canvas, width, height, start=HEADER_FROM, end=HEADER_TO, degrees=103):
    """The header gradient, drawn as stripes.

    tkinter has no gradients: N lines are drawn interpolating the colour. At
    103 degrees the direction is almost horizontal, with a slight tilt.
    """
    import math
    canvas.delete("gradient")
    start_r, start_g, start_b = canvas.winfo_rgb(start)
    end_r, end_g, end_b = canvas.winfo_rgb(end)
    radians = math.radians(degrees - 90)
    shift = math.tan(radians) * height
    steps = max(int(width + abs(shift)), 2)
    for index in range(steps):
        ratio = index / float(steps - 1)
        colour = "#%02x%02x%02x" % (
            int((start_r + (end_r - start_r) * ratio)) >> 8,
            int((start_g + (end_g - start_g) * ratio)) >> 8,
            int((start_b + (end_b - start_b) * ratio)) >> 8)
        x = index - abs(shift) * 0.5
        canvas.create_line(x, 0, x + shift, height, fill=colour, tags="gradient")
    canvas.tag_lower("gradient")
