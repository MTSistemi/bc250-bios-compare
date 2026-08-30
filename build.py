# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build Bc250BiosCompare.exe (and, if Inno Setup is around, the installer).

A virtual environment of its own is made inside this directory: the system
Python is not touched. The network is only needed the first time, to fetch
pyinstaller.

    python build.py            # exe
    python build.py --setup    # exe + installer
    python build.py --setup --sign   # and sign them (see sign.ps1)
    python build.py --clean    # throw away build/ dist/ .venv/

WARNING: the executable is for people who do not have Python: the program
itself has no dependencies and already runs from source on Windows and Linux
with `python Bc250BiosCompare.pyw`. Anyone working on the code has no reason to use
the exe.

WARNING: PyInstaller cannot rewrite the exe while it is running. It answers
"PermissionError: [WinError 5]" and LEAVES THE OLD FILE IN PLACE, translations
and all - so a rebuild that looks fine ships yesterday's data. With --onefile
the child process outlives a terminate() of the parent: close it first with
  taskkill /F /IM Bc250BiosCompare.exe
"""
from __future__ import unicode_literals

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")
VENV_PYTHON = os.path.join(VENV, "Scripts", "python.exe")
REQUIREMENTS = ["pyinstaller>=6.0"]
NAME = "Bc250BiosCompare"
VERSION = "1.0.0"
ISCC = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def run(args, **kw):
    print(">", " ".join(args))
    return subprocess.call(args, cwd=HERE, **kw)


def prepare_venv():
    if not os.path.isfile(VENV_PYTHON):
        print("Creating the virtual environment in .venv")
        if run([sys.executable, "-m", "venv", VENV]) != 0:
            sys.exit("cannot create .venv")
    if run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"]) != 0:
        sys.exit("pip will not upgrade")
    if run([VENV_PYTHON, "-m", "pip", "install"] + REQUIREMENTS) != 0:
        sys.exit("the requirements will not install (the network is needed)")


def prepare_resources():
    """Icon and file properties: for something that gets distributed they count."""
    icon = os.path.join(HERE, "emulator.ico")
    if not os.path.isfile(icon):
        print("Generating the icon")
        run([sys.executable, os.path.join(HERE, "icon.py")])
    version_file = os.path.join(HERE, "build", "version.txt")
    parts = VERSION.split(".") + ["0", "0", "0", "0"]
    numbers = tuple(int(part) for part in parts[:4])
    os.makedirs(os.path.dirname(version_file), exist_ok=True)
    with open(version_file, "w", encoding="utf-8") as handle:
        handle.write("""VSVersionInfo(
  ffi=FixedFileInfo(filevers=%r, prodvers=%r, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'MTSistemi'),
      StringStruct('FileDescription', 'BC-250 BIOS Compare'),
      StringStruct('FileVersion', '%s'),
      StringStruct('InternalName', '%s'),
      StringStruct('OriginalFilename', '%s.exe'),
      StringStruct('ProductName', 'BC-250 BIOS Compare'),
      StringStruct('ProductVersion', '%s'),
      StringStruct('Comments',
                   'Reads the menus of a BC-250 BIOS image, hidden entries '
                   'included. It writes nothing.')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
""" % (numbers, numbers, VERSION, NAME, NAME, VERSION))
    return icon, version_file


def build_exe():
    icon, version_file = prepare_resources()
    args = [
        VENV_PYTHON, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME,
        "--icon", icon,
        "--version-file", version_file,
        # The program uses neither: keeping them out means a 10 MiB executable
        # instead of a 60 MiB one.
        "--exclude-module", "numpy",
        "--exclude-module", "PIL",
    ]
    # WARNING: translations and cards are data files: without --add-data they
    # stay outside the executable and the program comes up mute, in English and
    # with no explanations, without saying that anything is missing.
    for directory in ("languages", "cards"):
        args += ["--add-data", "%s%s%s" % (os.path.join(HERE, directory),
                                           os.pathsep, directory)]
    args.append(os.path.join(HERE, "Bc250BiosCompare.pyw"))
    if run(args) != 0:
        sys.exit("PyInstaller failed")
    exe = os.path.join(HERE, "dist", NAME + ".exe")
    print("\nDone: %s (%.1f MiB)" % (exe, os.path.getsize(exe) / 1048576.0))
    return exe


def sign(paths):
    """Sign with sign.ps1, when it is there.

    WARNING: THE ORDER MATTERS: the executable first, then the installer that
    carries it. Signing only at the end would leave the exe inside the setup
    unsigned.
    """
    script = os.path.join(HERE, "sign.ps1")
    if not os.path.isfile(script):
        print("sign.ps1 is not here: skipping the signature. To sign, copy it "
              "from the BIOS programmer together with the certificate.")
        return
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", script, "-File"] + list(paths)
    run(args)


def build_setup():
    iscc = next((path for path in ISCC if os.path.isfile(path)), None)
    if not iscc:
        print("Inno Setup not found: skipping the installer.")
        return None
    if run([iscc, os.path.join(HERE, NAME + ".iss")]) != 0:
        sys.exit("Inno Setup failed")
    return os.path.join(HERE, "dist")


def clean():
    for name in ("build", "dist", ".venv", NAME + ".spec", "__pycache__"):
        path = os.path.join(HERE, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            os.remove(path)
    print("cleaned")


def main():
    if "--clean" in sys.argv:
        clean()
        return 0
    prepare_venv()
    exe = build_exe()
    wants_signature = "--sign" in sys.argv
    if wants_signature:
        sign([exe])
    if "--setup" in sys.argv:
        build_setup()
        setup = os.path.join(HERE, "dist", "%s-Setup-%s.exe" % (NAME, VERSION))
        if wants_signature and os.path.isfile(setup):
            sign([setup])
    return 0


if __name__ == "__main__":
    sys.exit(main())
