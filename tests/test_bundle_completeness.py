# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Smoke tests for the vendored TactileDisplayAPI bundle layout.

Asserts every file the runtime expects to find under
``addon/tactileDisplayAPI/`` is present on disk. Catches the
"vendor-zip swap forgot a file" failure mode at unit-test time
(satisfies FR-009) before that failure surfaces as a runtime
``OSError(126)`` ("procedure not found") on the next import.

Membership test only — does NOT load the DLL or compare bytes.
The test runs on any machine that has the addon source tree,
including CI workers without a DotPad attached.
"""

from __future__ import annotations

import unittest
from pathlib import Path


_BUNDLE_DIR = Path(__file__).resolve().parent.parent / "addon" / "tactileDisplayAPI"


# Top-level DLLs the addon ships. Every one of these is required by either
# `comLoader._loadDll()` directly or by the v1.15 TactileDisplayAPI.dll's
# runtime `LoadLibrary` chain. A missing file here surfaces at runtime as
# a hard-to-debug OSError; making it a unit-test failure surfaces it during
# a normal test run.
#
# `liblouis.dll` and the `tables/` directory were dropped in feature 025:
# the addon patches each per-locale ini to point the library at the running
# NVDA's own liblouis + louis/tables, so the bundled copies are redundant.
#
# `jsoncpp.dll` was dropped by the vendor in v1.0.34: no DLL in the drop
# imports it any more.
_REQUIRED_DLLS = (
	"TactileDisplayAPI.dll",
	"DotPadSDK-3.0.1.dll",
	"Mecab.dll",
	"TTBEngine.dll",
	"libmathcat_c.dll",
)


# Top-level Python modules the addon owns. They must coexist with the
# vendor files in the same directory because comLoader resolves the
# library directory relative to its own __file__.
_REQUIRED_PYTHON_MODULES = (
	"__init__.py",
	"comInterface.py",
	"comLoader.py",
	"wrapper.py",
	"libraryWorker.py",
	"callbackServer.py",
	"simulatedDisplay.py",
)


class TestBundleLayout(unittest.TestCase):
	"""Vendored bundle is intact at a structural level."""

	def test_bundleDirectoryExists(self) -> None:
		self.assertTrue(_BUNDLE_DIR.is_dir(), f"missing bundle dir: {_BUNDLE_DIR}")

	def test_requiredDllsPresent(self) -> None:
		missing = [name for name in _REQUIRED_DLLS if not (_BUNDLE_DIR / name).is_file()]
		self.assertEqual(missing, [], f"missing vendor DLL(s) under {_BUNDLE_DIR}: {missing}")

	def test_requiredPythonModulesPresent(self) -> None:
		missing = [name for name in _REQUIRED_PYTHON_MODULES if not (_BUNDLE_DIR / name).is_file()]
		self.assertEqual(missing, [], f"missing addon module(s) under {_BUNDLE_DIR}: {missing}")

	def test_enuDirectoryHasIniFile(self) -> None:
		ini = _BUNDLE_DIR / "enu" / "TactileDisplayAPI.ini"
		self.assertTrue(ini.is_file(), f"missing language config: {ini}")

	def test_tablesDirectoryNotBundled(self) -> None:
		# Feature 025 dropped the bundled liblouis tables; the library now
		# loads NVDA's louis/tables via the patched ini TablesPath.
		tables = _BUNDLE_DIR / "tables"
		self.assertFalse(tables.exists(), f"tables/ should no longer be bundled: {tables}")

	def test_liblouisDllNotBundled(self) -> None:
		# Feature 025 dropped the bundled liblouis.dll; the library now loads
		# NVDA's liblouis.dll via the patched ini LiblouisPath.
		dll = _BUNDLE_DIR / "liblouis.dll"
		self.assertFalse(dll.exists(), f"liblouis.dll should no longer be bundled: {dll}")

	def test_mathCatRulesDirectoryPresent(self) -> None:
		# v1.15 introduced MathCAT support and ships a rules directory next
		# to the DLL. Without it, libmathcat_c.dll fails to initialise on
		# first MathML render.
		rulesDir = _BUNDLE_DIR / "MathCATRules"
		self.assertTrue(rulesDir.is_dir(), f"missing MathCATRules dir: {rulesDir}")
		# Spot-check the canonical entry points the rules system loads.
		for expected in ("definitions.yaml", "intent.yaml", "prefs.yaml"):
			path = rulesDir / expected
			self.assertTrue(path.is_file(), f"missing MathCATRules entry: {path}")


if __name__ == "__main__":
	unittest.main()
