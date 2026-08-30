# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the program into one file - Bc250BiosCompare.exe on Windows,
bc250-bios-compare on Linux - and, where the tools are there, its installer.

A virtual environment of its own is made inside this directory: the system
Python is not touched. The network is only needed the first time, to fetch
pyinstaller.

    python build.py            # the executable
    python build.py --setup    # Windows: also the Inno Setup installer
    python build.py --setup --sign   # and sign them (see sign.ps1)
    python build.py --install  # Linux: build, then put it in ~/.local
    python build.py --install-only   # install what is already in dist/
    python build.py --clean    # throw away build/ dist/ .venv/

WARNING: the executable is for people who do not have Python: the program
itself has no dependencies and already runs from source on Windows and Linux
with `python Bc250BiosCompare.pyw`. Anyone working on the code has no reason to
use it.

WARNING, WINDOWS: PyInstaller cannot rewrite the exe while it is running. It
answers "PermissionError: [WinError 5]" and LEAVES THE OLD FILE IN PLACE,
translations and all - so a rebuild that looks fine ships yesterday's data. With
--onefile the child process outlives a terminate() of the parent: close it first
with
  taskkill /F /IM Bc250BiosCompare.exe

WARNING, LINUX: a one-file build is tied to the glibc of the machine that made
it - it runs on that version and on newer ones, never on older. Built on
SkillFishOS (glibc 2.43) it will refuse to start on Debian 12 or Ubuntu 22.04.
For something to hand around, build on the oldest system you are willing to
support; for a machine of your own, any is fine. The source has no such problem:
python3 plus python3-tk and it runs anywhere.
"""
from __future__ import unicode_literals

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")
WINDOWS = os.name == "nt"
VENV_PYTHON = os.path.join(VENV, "Scripts", "python.exe") if WINDOWS \
    else os.path.join(VENV, "bin", "python")
REQUIREMENTS = ["pyinstaller>=6.0"]
NAME = "Bc250BiosCompare"           # the Windows name, CamelCase as usual there
LINUX_NAME = "bc250-bios-compare"   # the Linux one, lowercase as usual there
VERSION = "1.0.0"
ISCC = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Version=1.0
Name=BC-250 BIOS Compare
GenericName=BIOS menu reader
Comment=Reads the menus of a BC-250 BIOS image, hidden entries included. It writes nothing.
Exec=%(command)s %%f
Icon=%(icon)s
Terminal=false
Categories=Development;Electronics;System;
Keywords=BIOS;UEFI;firmware;BC-250;
MimeType=application/octet-stream;
"""


def run(args, **kw):
    print(">", " ".join(args))
    return subprocess.call(args, cwd=HERE, **kw)


def prepare_venv():
    if not os.path.isfile(VENV_PYTHON):
        print("Creating the virtual environment in .venv")
        if run([sys.executable, "-m", "venv", VENV]) != 0:
            sys.exit("cannot create .venv (on Debian: apt install python3-venv)")
    if run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"]) != 0:
        sys.exit("pip will not upgrade")
    if run([VENV_PYTHON, "-m", "pip", "install"] + REQUIREMENTS) != 0:
        sys.exit("the requirements will not install (the network is needed)")


def prepare_icon():
    """The icon, in the format the system in front of us understands."""
    name = "emulator.ico" if WINDOWS else "emulator.png"
    icon = os.path.join(HERE, name)
    if not os.path.isfile(icon):
        print("Generating the icon")
        args = [sys.executable, os.path.join(HERE, "icon.py")]
        if not WINDOWS:
            args.append("--png")
        run(args)
    return icon


def prepare_version_file():
    """The version resource, which only Windows has."""
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
    return version_file


def build_executable():
    icon = prepare_icon()
    name = NAME if WINDOWS else LINUX_NAME
    args = [
        VENV_PYTHON, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", name,
        # The program uses neither: keeping them out means a 10 MiB executable
        # instead of a 60 MiB one.
        "--exclude-module", "numpy",
        "--exclude-module", "PIL",
    ]
    if WINDOWS:
        # WARNING: --icon and --version-file are Windows resources. On Linux
        # PyInstaller takes them and puts them nowhere: the icon of a Linux
        # program is not in the binary, it is in the .desktop file.
        args += ["--icon", icon, "--version-file", prepare_version_file()]
    # WARNING: translations and cards are data files: without --add-data they
    # stay outside the executable and the program comes up mute, in English and
    # with no explanations, without saying that anything is missing.
    # The separator is ';' on Windows and ':' on Linux, which is exactly what
    # os.pathsep is.
    for directory in ("languages", "cards"):
        args += ["--add-data", "%s%s%s" % (os.path.join(HERE, directory),
                                           os.pathsep, directory)]
    args.append(os.path.join(HERE, "Bc250BiosCompare.pyw"))
    if run(args) != 0:
        sys.exit("PyInstaller failed")
    built = os.path.join(HERE, "dist", name + (".exe" if WINDOWS else ""))
    if not WINDOWS:
        build_desktop_files(icon)
    print("\nDone: %s (%.1f MiB)" % (built, os.path.getsize(built) / 1048576.0))
    return built


def build_desktop_files(icon):
    """The two files a Linux desktop needs beside the binary: the icon and the
    .desktop entry. They are written next to it, in dist/."""
    dist = os.path.join(HERE, "dist")
    shutil.copyfile(icon, os.path.join(dist, LINUX_NAME + ".png"))
    entry = os.path.join(dist, LINUX_NAME + ".desktop")
    with open(entry, "w", encoding="utf-8") as handle:
        handle.write(DESKTOP_ENTRY % {"command": LINUX_NAME, "icon": LINUX_NAME})
    return entry


def install_linux():
    """Put the three files where a single user's desktop looks for them.

    ~/.local, not /usr: no root, and nothing of the system is touched. Removing
    it is deleting three files, which --uninstall does.
    """
    home = os.path.expanduser("~")
    binary = os.path.join(HERE, "dist", LINUX_NAME)
    if not os.path.isfile(binary):
        sys.exit("build it first: python3 build.py")
    targets = [
        (binary, os.path.join(home, ".local", "bin", LINUX_NAME), True),
        (os.path.join(HERE, "dist", LINUX_NAME + ".png"),
         os.path.join(home, ".local", "share", "icons", "hicolor", "256x256",
                      "apps", LINUX_NAME + ".png"), False),
        (os.path.join(HERE, "dist", LINUX_NAME + ".desktop"),
         os.path.join(home, ".local", "share", "applications",
                      LINUX_NAME + ".desktop"), False),
    ]
    for source, target, executable in targets:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
        if executable:
            os.chmod(target, 0o755)
        print("installed %s" % target)
    if shutil.which("update-desktop-database"):
        run(["update-desktop-database",
             os.path.join(home, ".local", "share", "applications")])
    path = os.environ.get("PATH", "")
    if os.path.join(home, ".local", "bin") not in path.split(os.pathsep):
        print("\nWARNING: ~/.local/bin is not in the PATH: the menu entry works,"
              "\ntyping %s in a shell does not." % LINUX_NAME)
    return 0


def uninstall_linux():
    home = os.path.expanduser("~")
    for target in (
            os.path.join(home, ".local", "bin", LINUX_NAME),
            os.path.join(home, ".local", "share", "icons", "hicolor", "256x256",
                         "apps", LINUX_NAME + ".png"),
            os.path.join(home, ".local", "share", "applications",
                         LINUX_NAME + ".desktop")):
        if os.path.isfile(target):
            os.remove(target)
            print("removed %s" % target)
    return 0


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
    for name in ("build", "dist", ".venv", NAME + ".spec", LINUX_NAME + ".spec",
                 "__pycache__"):
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
    if "--uninstall" in sys.argv:
        if WINDOWS:
            sys.exit("--uninstall is for Linux: on Windows use the installer.")
        return uninstall_linux()
    # WARNING: --install BUILDS first. It used to skip the build when dist/
    # already held a binary, which meant that after editing a source file
    # `build.py --install` cheerfully installed yesterday's build and said
    # nothing. Installing without building is now something you have to ask for
    # by name.
    if "--install-only" in sys.argv:
        return install_linux()
    prepare_venv()
    built = build_executable()
    wants_signature = "--sign" in sys.argv
    if not WINDOWS:
        if "--install" in sys.argv:
            install_linux()
        return 0
    if wants_signature:
        sign([built])
    if "--setup" in sys.argv:
        build_setup()
        setup = os.path.join(HERE, "dist", "%s-Setup-%s.exe" % (NAME, VERSION))
        if wants_signature and os.path.isfile(setup):
            sign([setup])
    return 0


if __name__ == "__main__":
    sys.exit(main())
