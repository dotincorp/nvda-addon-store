# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for multi-line braille line spacing on the graphic display (feature 030).

The DotPad tactile area renders multi-line braille with one empty dot-row between
braille lines, matching the TactileDisplayAPI library. ``Display.verticalCellSpacing``
is the single source of truth for that gap. These tests lock in:

- the graphic display is created with ``verticalCellSpacing=1`` (the production wiring),
- the ``_get_numRows`` line-count formula's behaviour for that spacing (more lines fit),
- the small-geometry boundary: reducing the gap never reduces the line count.

The board-info → display-creation path is exercised with ``_createDisplay`` and the
``PresentationRenderer`` construction mocked, so no real ``Display`` I/O runs.
"""

from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from addon.brailleDisplayDrivers.dotPad import driver as dotpad_driver


class TestGraphicDisplayVerticalSpacing(unittest.TestCase):
	"""The graphic display is built with a 1-dot inter-line gap (FR-001/FR-002)."""

	def test_graphicDisplay_createdWith1DotVerticalSpacing(self) -> None:
		"""On board info, ``_createDisplay`` for the graphic area gets ``verticalCellSpacing=1``."""
		driver = dotpad_driver.BrailleDisplayDriver.__new__(dotpad_driver.BrailleDisplayDriver)
		# __init__ is skipped, so supply the send gate _handleResponse signals.
		driver._readyToSend = threading.Event()

		createdKwargs: list[dict] = []

		def fakeCreate(descriptor, **kwargs):
			disp = MagicMock(name="display")
			disp.numCols = descriptor.columnCount
			disp.numRows = descriptor.rowCount
			createdKwargs.append(kwargs)
			return disp

		driver._createDisplay = MagicMock(side_effect=fakeCreate)

		# 12-byte RSP_BOARD_INFORMATION args:
		#   [0..3] features, dotsPerCell, distanceBetweenPins, functionKeyCount
		#   [4..7] text descriptor   -> columnCount 0  (skips the text-display branch)
		#   [8..11] graphic descriptor -> rowCount 10, columnCount 30 (DotPad300A-like)
		packet = MagicMock(name="boardInfoPacket")
		packet.packetType = dotpad_driver.PacketType.RSP_BOARD_INFORMATION
		packet.args = bytes([0, 1, 0x1A, 0, 0, 0, 0, 0, 10, 30, 0, 1])

		with (
			patch("addon.presentations.PresentationRenderer", MagicMock()),
			patch.object(dotpad_driver.configuration, "getAutoRefresh", return_value=0),
		):
			driver._handleResponse(packet)

		graphicKwargs = [k for k in createdKwargs if k.get("supportsGraphic")]
		self.assertEqual(len(graphicKwargs), 1, "graphic display should be created exactly once")
		self.assertEqual(
			graphicKwargs[0]["verticalCellSpacing"],
			1,
			"graphic display must use a 1-dot inter-line gap to match the library",
		)


class TestDisplayNumRowsFormula(unittest.TestCase):
	"""``Display._get_numRows`` derives the braille line count from the spacing."""

	def _numRows(self, physicalNumRows: int, verticalCellSpacing: int, cellHeight: int = 4) -> int:
		"""Call the real ``_get_numRows`` on a bare ``Display`` with the needed attributes."""
		disp = dotpad_driver.Display.__new__(dotpad_driver.Display)
		disp.physicalNumRows = physicalNumRows
		disp.cellHeight = cellHeight
		disp.verticalCellSpacing = verticalCellSpacing
		return disp._get_numRows()

	def test_tenRows_oneDotSpacing_fitsEightLines(self) -> None:
		"""10 physical cell-rows with a 1-dot gap fit 8 braille lines (SC-002)."""
		self.assertEqual(self._numRows(10, 1), 8)

	def test_tenRows_twoDotSpacing_fitsSevenLines(self) -> None:
		"""Characterises the previous 2-dot behaviour (7 lines): formula is spacing-sensitive."""
		self.assertEqual(self._numRows(10, 2), 7)

	def test_smallAreas_oneDotNeverFitsFewerLinesThanTwoDot(self) -> None:
		"""Edge case: reducing the gap must never reduce the line count on small geometries."""
		for physicalNumRows in (3, 4, 5, 7, 10, 20):
			with self.subTest(physicalNumRows=physicalNumRows):
				self.assertGreaterEqual(
					self._numRows(physicalNumRows, 1),
					self._numRows(physicalNumRows, 2),
					"1-dot spacing must fit at least as many lines as 2-dot spacing",
				)


if __name__ == "__main__":
	unittest.main()
