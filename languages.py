# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""The program's languages: the same nine SkillFishOS speaks.

THE CONVENTION IS SkillFishOS's, AND THAT IS NOT A DETAIL.
The keys are the ENGLISH strings: `T("Open image...")` looks up that very line
in the chosen language file. One file per language, in `languages/<code>.json`.
The reason is written in the SkillFishOS system module and holds here too:
somebody who wants to help translate sends ONE FILE, not a change inside Python
sources they have never seen. The Polish of our applications was written by
someone who had no write access to the repository: it really happened, and this
is how not to make them redo it every release.

WARNING: ENGLISH IS BOTH THE SOURCE AND THE FALLBACK. If a file is missing,
broken, or does not have that line, English is shown and we carry on. A missing
translation is an annoyance; a program that does not start is a fault.

WARNING: here English is also the DEFAULT at startup, unlike our other
applications: this tool was born for the BC-250 community, which speaks
English. Whoever wants it in Italian picks it from the drop-down, and the
choice is remembered.
"""
from __future__ import unicode_literals

import io
import json
import os
import sys

# WARNING: inside the executable built with PyInstaller the files do not sit
# next to the source but in the temporary directory the bootloader creates
# (_MEIPASS): looking for them next to __file__ works from source and fails in
# the executable, where the program would come up entirely in English without
# saying why.
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LANGUAGES_DIR = os.path.join(HERE, "languages")

# In the order they appear in the drop-down: English first, being the default,
# then the others as on the SkillFishOS website.
LANGUAGES = ("en", "it", "es", "pt", "fr", "de", "pl", "uk", "ru")

# The names as written by the people who speak them. They stay out of the
# dictionary because they are not translated: in every language Polish is
# called "Polski".
NATIVE_NAMES = {
    "en": "English", "it": "Italiano", "es": "Español",
    "pt": "Português", "fr": "Français", "de": "Deutsch",
    "pl": "Polski", "uk": "Українська",
    "ru": "Русский",
}

CODES = LANGUAGES
DEFAULT = "en"

_dictionaries = {}
_current = DEFAULT


def _load(code):
    """One language's dictionary. When it cannot be read, an empty one.

    Nothing is raised and nothing is printed: the caller would only see
    English, which is an acceptable and silent fallback.
    """
    if code in _dictionaries:
        return _dictionaries[code]
    path = os.path.join(LANGUAGES_DIR, "%s.json" % code)
    dictionary = {}
    try:
        with io.open(path, encoding="utf-8") as language_file:
            loaded = json.load(language_file)
        if isinstance(loaded, dict):
            dictionary = {key: value for key, value in loaded.items()
                          if isinstance(value, str) and value}
    except Exception:                                      # noqa: BLE001
        dictionary = {}
    _dictionaries[code] = dictionary
    return dictionary


def set_language(code):
    """Choose the language. A code we do not know falls back to English."""
    global _current
    _current = code if code in CODES else DEFAULT
    return _current


def current():
    return _current


def language_name(code):
    return NATIVE_NAMES.get(code, code)


def T(text, **values):
    """The translation of `text` in the chosen language, with the gaps filled.

    Gaps are written {like_this}: `T("{count} entries", count=12)`. If the
    translation has a gap we do not pass - it happens, translators make
    mistakes - the English sentence is shown instead of killing the window.
    """
    translated = text
    if _current != DEFAULT:
        translated = _load(_current).get(text, text)
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError):
        try:
            return text.format(**values)
        except Exception:                                  # noqa: BLE001
            return text


def missing(code):
    """The keys that language does not have yet: for whoever is translating."""
    reference = _load("it")                    # Italian is the most complete
    dictionary = _load(code)
    return sorted(key for key in reference if key not in dictionary)


# --- remembering the choice -------------------------------------------------
# A two-line file in the user's home: no Windows registry.
# WARNING: NOT next to the program: installed under Program Files it would not
# be writable, and the language would be forgotten at every close without an
# error to explain it. If even this cannot be written, never mind: we start in
# English.
# Where that file goes is where each system expects it: a dotfile in the home on
# Windows, $XDG_CONFIG_HOME (in practice ~/.config) on Linux. A program that
# drops its own dotfile in a Linux home is a program written on Windows.


def _settings_path():
    if os.name == "nt":
        return os.path.join(os.path.expanduser("~"), ".bc250-bios-compare.json")
    base = os.environ.get("XDG_CONFIG_HOME") or \
        os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "bc250-bios-compare.json")


SETTINGS = _settings_path()
# Anyone who used the Windows layout on Linux keeps their choice: it is read
# from the old place when the new one is not there yet.
LEGACY_SETTINGS = os.path.join(os.path.expanduser("~"), ".bc250-bios-compare.json")


def read_choice():
    for path in (SETTINGS, LEGACY_SETTINGS):
        try:
            with io.open(path, encoding="utf-8") as settings_file:
                return json.load(settings_file).get("language", DEFAULT)
        except Exception:                                  # noqa: BLE001
            continue
    return DEFAULT


def write_choice(code):
    try:
        directory = os.path.dirname(SETTINGS)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        with io.open(SETTINGS, "w", encoding="utf-8") as settings_file:
            settings_file.write(json.dumps({"language": code}, ensure_ascii=False))
    except Exception:                                      # noqa: BLE001
        pass
