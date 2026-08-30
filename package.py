# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the Debian package.

    python3 package.py             # writes dist/bc250-bios-compare_<version>_all.deb

WHY A PACKAGE AND NOT THE ONE-FILE BINARY. The binary that build.py makes is
tied to the glibc of the machine that made it: built on SkillFishOS (2.43) it
will not start on Debian 12 (2.36). This program is pure Python and needs
nothing but the standard library and tkinter, so the package is
`Architecture: all` and has no such problem - one file, every Debian, every
architecture, and 200 KB instead of 14 MB.

WHERE THINGS GO, and it is the Debian layout, not ours:
    /usr/share/bc250-bios-compare/      the modules, the languages, the cards
    /usr/bin/bc250-bios-compare         the window
    /usr/bin/bc250-bios-compare-cli     the command line
    /usr/share/applications/            the menu entry
    /usr/share/icons/hicolor/256x256/   the icon
    /usr/share/doc/bc250-bios-compare/  copyright and changelog

Needs `dpkg-deb`, so it runs on a Debian machine. Nothing else: no debhelper,
no build dependencies, no root - `--root-owner-group` gives every file to root
without needing to be root.
"""
from __future__ import unicode_literals

import email.utils
import gzip
import hashlib
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "bc250-bios-compare"
VERSION = "1.0.0"
REVISION = "1"                    # the Debian revision: bumped for packaging fixes
MAINTAINER = "MTSistemi <info@mtsistemi.it>"
HOMEPAGE = "https://github.com/MTSistemi/bc250-bios-compare"

# The modules that make up the program. Listed rather than globbed: build.py,
# icon.py and package.py build it and have no business being installed.
MODULES = ["window.py", "emulator.py", "biosview.py", "engine.py", "explain.py",
           "ffs.py", "hii.py", "hiifont.py", "ifr.py", "languages.py",
           "theme.py", "tse.py", "volumes.py"]
DATA_DIRECTORIES = ["languages", "cards"]

DESCRIPTION = """read and compare the menus of AMD BC-250 BIOS images
 Reads a BIOS image of the AMD BC-250 and shows its menus - all of them,
 including the entries the firmware hides, which a running board cannot show
 by definition. It then evaluates the firmware's own conditions against a
 state of the variables and says what changes when an entry is changed.
 .
 It does not boot the firmware and it writes nothing to the hardware: it reads
 the IFR forms out of the image and interprets them the way the setup engine
 does. Two images can be compared menu by menu, which is how a modified BIOS
 is told from the stock one.
 .
 The window draws the setup screen with the glyphs and the palette taken from
 the image itself, and can be walked with the same keys as the board. There is
 a command line too, and the interface speaks nine languages.
"""

CONTROL = """Package: %(name)s
Version: %(version)s-%(revision)s
Architecture: all
Maintainer: %(maintainer)s
Installed-Size: %(size)d
Depends: python3 (>= 3.8), python3-tk
Section: utils
Priority: optional
Homepage: %(homepage)s
Description: %(description)s"""

COPYRIGHT = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: %(name)s
Source: %(homepage)s

Files: *
Copyright: 2026 MTSistemi
License: GPL-3.0+

License: GPL-3.0+
 This program is free software: you can redistribute it and/or modify it
 under the terms of the GNU General Public License as published by the Free
 Software Foundation, either version 3 of the License, or (at your option)
 any later version.
 .
 This program is distributed in the hope that it will be useful, but WITHOUT
 ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
 more details.
 .
 On Debian systems, the complete text of the GNU General Public License
 version 3 can be found in "/usr/share/common-licenses/GPL-3".
"""

CHANGELOG = """%(name)s (%(version)s-%(revision)s) unstable; urgency=low

  * First package. The program itself is the one that reads the BC-250
    firmware menus; nothing in it is Debian-specific.

 -- %(maintainer)s  %(date)s
"""

POSTRM = """#!/bin/sh
set -e
case "$1" in
  remove|purge)
    # Python writes __pycache__ next to the modules the first time they run.
    # dpkg did not install those files, so it does not remove them, and the
    # purge left the directory behind with a warning. They are ours - they only
    # exist because our modules ran - so we clear them.
    rm -rf /usr/share/%(name)s
    ;;
esac
exit 0
"""

LAUNCHER = """#!/bin/sh
# The window. The modules sit together in /usr/share, and python3 puts the
# directory of the script it runs at the front of sys.path, so the imports
# between them work with no PYTHONPATH of our own.
exec /usr/bin/python3 /usr/share/%(name)s/window.py "$@"
"""

LAUNCHER_CLI = """#!/bin/sh
# The command line: tree, entry, simulate, compare, export.
exec /usr/bin/python3 /usr/share/%(name)s/emulator.py "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Version=1.0
Name=BC-250 BIOS Compare
GenericName=BIOS menu reader
Comment=Reads the menus of a BC-250 BIOS image, hidden entries included. It writes nothing.
Exec=%(name)s %%f
Icon=%(name)s
Terminal=false
Categories=Development;Electronics;System;
Keywords=BIOS;UEFI;firmware;BC-250;
MimeType=application/octet-stream;
"""


def build_date():
    """The changelog date, reproducible when SOURCE_DATE_EPOCH says so."""
    stamp = os.environ.get("SOURCE_DATE_EPOCH")
    return email.utils.formatdate(float(stamp) if stamp else time.time(),
                                  localtime=not stamp)


def write(path, text, mode=0o644):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.chmod(path, mode)


def tree_size(root):
    """Installed-Size, in KiB: what the package occupies once unpacked."""
    total = 0
    for directory, _subdirectories, files in os.walk(root):
        for name in files:
            total += os.path.getsize(os.path.join(directory, name))
    return (total + 1023) // 1024


def write_md5sums(root):
    """DEBIAN/md5sums: what dpkg checks the installed files against.

    dpkg-deb does not write it, and without it `dpkg --verify` has nothing to
    say about this package.
    """
    lines = []
    for directory, _subdirectories, files in sorted(os.walk(root)):
        if os.path.basename(directory) == "DEBIAN":
            continue
        for name in sorted(files):
            path = os.path.join(directory, name)
            with open(path, "rb") as handle:
                digest = hashlib.md5(handle.read()).hexdigest()
            lines.append("%s  %s" % (digest,
                                     os.path.relpath(path, root).replace("\\", "/")))
    write(os.path.join(root, "DEBIAN", "md5sums"), "\n".join(lines) + "\n")


def build():
    if not shutil.which("dpkg-deb"):
        sys.exit("dpkg-deb is not here: the package is built on a Debian machine.")
    root = os.path.join(HERE, "build", "deb")
    shutil.rmtree(root, ignore_errors=True)
    fields = {"name": NAME, "version": VERSION, "revision": REVISION,
              "maintainer": MAINTAINER, "homepage": HOMEPAGE,
              "description": DESCRIPTION, "date": build_date()}

    # the program itself
    share = os.path.join(root, "usr", "share", NAME)
    os.makedirs(share)
    for module in MODULES:
        shutil.copyfile(os.path.join(HERE, module), os.path.join(share, module))
    for directory in DATA_DIRECTORIES:
        shutil.copytree(os.path.join(HERE, directory),
                        os.path.join(share, directory))

    # the two commands
    write(os.path.join(root, "usr", "bin", NAME), LAUNCHER % fields, 0o755)
    write(os.path.join(root, "usr", "bin", NAME + "-cli"), LAUNCHER_CLI % fields,
          0o755)

    # the desktop entry and the icon
    write(os.path.join(root, "usr", "share", "applications", NAME + ".desktop"),
          DESKTOP % fields)
    icon = os.path.join(HERE, "emulator.png")
    if not os.path.isfile(icon):
        subprocess.check_call([sys.executable, os.path.join(HERE, "icon.py"),
                               "--png"], cwd=HERE)
    icon_target = os.path.join(root, "usr", "share", "icons", "hicolor",
                               "256x256", "apps", NAME + ".png")
    os.makedirs(os.path.dirname(icon_target))
    shutil.copyfile(icon, icon_target)

    # the manual pages, gzipped as Debian wants them
    manual = os.path.join(root, "usr", "share", "man", "man1")
    os.makedirs(manual)
    for page in (NAME + ".1", NAME + "-cli.1"):
        with open(os.path.join(HERE, "man", page), "rb") as source:
            with gzip.GzipFile(os.path.join(manual, page + ".gz"), "wb",
                               mtime=0) as target:
                target.write(source.read())

    # copyright and changelog: without them the package is not a Debian package,
    # it is a tarball with a control file.
    documentation = os.path.join(root, "usr", "share", "doc", NAME)
    write(os.path.join(documentation, "copyright"), COPYRIGHT % fields)
    changelog = (CHANGELOG % fields).encode("utf-8")
    os.makedirs(documentation, exist_ok=True)
    with gzip.GzipFile(os.path.join(documentation, "changelog.Debian.gz"), "wb",
                       mtime=0) as handle:      # mtime=0: same bytes every build
        handle.write(changelog)

    fields["size"] = tree_size(root)
    write(os.path.join(root, "DEBIAN", "control"), CONTROL % fields)
    write(os.path.join(root, "DEBIAN", "postrm"), POSTRM % fields, 0o755)
    write_md5sums(root)

    dist = os.path.join(HERE, "dist")
    os.makedirs(dist, exist_ok=True)
    package = os.path.join(dist, "%s_%s-%s_all.deb" % (NAME, VERSION, REVISION))
    if subprocess.call(["dpkg-deb", "--root-owner-group", "--build", root,
                        package]) != 0:
        sys.exit("dpkg-deb failed")
    print("\nDone: %s (%.0f KiB)" % (package, os.path.getsize(package) / 1024.0))
    if shutil.which("lintian"):
        subprocess.call(["lintian", "--no-tag-display-limit", package])
    return package


if __name__ == "__main__":
    build()
