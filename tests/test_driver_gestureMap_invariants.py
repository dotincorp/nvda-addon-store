# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Regression guard: driver ``gestureMap`` entries preserved by feature 016.

Feature 016 left the driver's ``gestureMap`` unchanged. ``braille_scrollBack``
/ ``braille_scrollForward`` mapping to ``br(dotPad):panLeft`` /
``br(dotPad):panRight`` continues to drive NVDA's normal scroll of the
always-on 20-cell text braille display (outside the presentation layer).

This test asserts those entries are still present. If a future refactor
accidentally removes them, this test fails — surfacing the regression at
CI time instead of when a user can't scroll braille any more.

See FR-005 and FR-010 (f).
"""

from __future__ import annotations

import unittest


class TestDriverGestureMapInvariants(unittest.TestCase):
	"""``BrailleDisplayDriver.gestureMap`` keeps its essential braille entries."""

	def _readDriverMap(self) -> dict[str, dict[str, str]]:
		"""Return the raw driver gestureMap as a dict-of-dicts.

		``inputCore.GlobalGestureMap`` exposes the underlying mapping via
		its ``_map`` attribute; we inspect it for the entries this feature
		protects.
		"""
		from addon.brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver

		# NVDA's GlobalGestureMap stores entries in a (class → script → identifiers) dict.
		# Flatten to {scriptName: gestureIdentifier} for the GlobalCommands class.
		gestureMap = BrailleDisplayDriver.gestureMap
		# Use the public iteration API: getScriptsForAllGestures yields
		# (cls, gesture, scriptName) triples.
		flat: dict[str, str] = {}
		for _cls, gesture, scriptName in gestureMap.getScriptsForAllGestures():
			# Lowercase scriptName because that's how NVDA stores it.
			flat[scriptName] = gesture
		return flat  # type: ignore[return-value]

	def test_braille_scrollBack_still_mapped_to_panLeft(self) -> None:
		flat = self._readDriverMap()
		self.assertIn(
			"braille_scrollBack",
			flat,
			"Driver gestureMap MUST keep braille_scrollBack — it scrolls "
			"the 20-cell text braille display (FR-005).",
		)
		# Normalised identifier is lowercase.
		self.assertEqual(flat["braille_scrollBack"].lower(), "br(dotpad):panleft")

	def test_braille_scrollForward_still_mapped_to_panRight(self) -> None:
		flat = self._readDriverMap()
		self.assertIn(
			"braille_scrollForward",
			flat,
			"Driver gestureMap MUST keep braille_scrollForward.",
		)
		self.assertEqual(flat["braille_scrollForward"].lower(), "br(dotpad):panright")


if __name__ == "__main__":
	unittest.main()
