# -*- coding: utf-8 -*-
# Copyright (C) 2026 MTSistemi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Start the window without a console.

The .pyw extension tells Windows to use pythonw.exe: no black box behind the
window. On Linux it starts just the same, with `python3 Bc250BiosCompare.pyw`, or
directly with `python3 window.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import window

if __name__ == "__main__":
    window.main()
