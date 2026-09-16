# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the NVDA braille name facade.

NVDA 2026.3 split ``braille`` into a package and deprecated the old names, whose shims
log a warning with a full stack trace on every access. The add-on supports 2026.1
onwards, so ``addon.compat.nvdaBraille`` resolves each name wherever the running version
keeps it, and nothing in the add-on may read it off ``braille`` directly.
"""

from __future__ import annotations

import unittest
from pathlib import Path

NAMES = ("BrailleBuffer", "DisplayDimensions", "Region", "TextInfoRegion", "getFocusRegions")

ADDON_DIR = Path(__file__).resolve().parent.parent / "addon"


class TestFacadeResolvesEveryName(unittest.TestCase):
	def test_every_name_is_bound(self) -> None:
		from addon.compat import nvdaBraille

		for name in NAMES:
			with self.subTest(name=name):
				self.assertTrue(hasattr(nvdaBraille, name), f"{name} is not resolved")

	def test_all_matches_what_is_exported(self) -> None:
		from addon.compat import nvdaBraille

		self.assertEqual(sorted(NAMES), sorted(nvdaBraille.__all__))


class TestNothingImportsTheDeprecatedNames(unittest.TestCase):
	"""A direct ``from braille import <name>`` is what floods the log; keep it out."""

	def test_no_addon_source_imports_them_from_braille(self) -> None:
		offenders: list[str] = []
		for path in ADDON_DIR.rglob("*.py"):
			if "_vendor" in path.parts or path.name == "nvdaBraille.py":
				continue
			source = path.read_text(encoding="utf-8")
			for name in NAMES:
				if f"from braille import {name}" in source or f"braille.{name}" in source:
					offenders.append(f"{path.relative_to(ADDON_DIR)}: {name}")
		self.assertEqual([], offenders, "import these from addon.compat.nvdaBraille instead")


if __name__ == "__main__":
	unittest.main()
