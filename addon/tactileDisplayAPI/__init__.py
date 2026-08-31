# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""TactileDisplayAPI COM library integration.

This package bundles the TactileDisplayAPI v1.11 COM library
(TactileDisplayAPI.dll) and its dependencies for DotPad tactile
graphics rendering.

Uses registration-free COM via DllGetClassObject — no regsvr32, no admin
rights, no registry writes required. Pure ctypes — no comtypes dependency.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_library_path() -> Path:
	"""Return the path to the TactileDisplayAPI library directory."""
	return Path(os.path.dirname(__file__))


def get_dll_path() -> Path:
	"""Return the path to TactileDisplayAPI.dll."""
	return get_library_path() / "TactileDisplayAPI.dll"


def get_ini_path() -> Path:
	"""Return the path to enu/TactileDisplayAPI.ini.

	The DLL reads this INI at runtime for liblouis table paths and
	per-display keymaps (added in v1.07/v1.08).
	"""
	return get_library_path() / "enu" / "TactileDisplayAPI.ini"
