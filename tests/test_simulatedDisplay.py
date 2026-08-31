# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the SimulateDisplay render path (feature 014).

The render path is the chain that turns library callback bytes into
DotPad device writes:

1. Validate the payload length.
2. Construct a `DpTactileGraphicsBuffer` sized to the graphic display.
3. For each row, call `tactile.braille.drawBrailleCells` with
   `hCellPadding=0` so no cell spacing is introduced (graphic mode).
4. Call `graphicDisplay.display(buf)` for delta-aware queueing.

These tests mock ``braille.handler.display.graphicDisplay`` and assert
the render path produces the expected buffer state + makes the right
calls. Hardware-dependent integration (the actual COM-callback fires
against a real DotPad) is exempt per the constitution's last bullet.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _makeGraphicDisplayMock(physicalNumCols: int = 2, physicalNumRows: int = 1):
	"""Build a mock that quacks like driver.Display's graphic-mode surface."""
	display = MagicMock(name="graphicDisplay")
	display.physicalNumCols = physicalNumCols
	display.physicalNumRows = physicalNumRows
	display.cellWidth = 2  # DotPad D2 cell
	display.cellHeight = 4
	return display


def _makeGraphicPresentation():
	"""Bare ``GraphicPresentation`` good enough for the gate's isinstance check.

	Feature 017 added a presentation-aware gate at ``renderTactileBytes``:
	bytes only reach the display when the active presentation is a
	library-bytes consumer (``GraphicPresentation`` or the new
	``LibraryBraillePresentation``). The render-path tests below mock the
	active presentation with a real ``GraphicPresentation`` instance so
	the gate passes — this preserves the test's intent (exercise the
	permutation logic), it just plumbs the gate setup along the way.
	"""
	from addon.presentations.graphic import GraphicPresentation

	return GraphicPresentation.__new__(GraphicPresentation)


class TestRenderTactileBytes(unittest.TestCase):
	"""``renderTactileBytes`` performs the standard-braille → pin permutation."""

	def test_renderPathCallsGraphicDisplayDisplay(self) -> None:
		"""Given a 2-cell payload, the render path calls display(buf) once.

		The buffer it passes must be the correctly-sized
		``DpTactileGraphicsBuffer``.
		"""
		from addon.brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
		from addon.tactileDisplayAPI import simulatedDisplay

		graphicDisplay = _makeGraphicDisplayMock(physicalNumCols=2, physicalNumRows=1)
		brailleHandler = MagicMock()
		brailleHandler.display.graphicDisplay = graphicDisplay

		with (
			patch.object(simulatedDisplay, "_getBrailleHandler", return_value=brailleHandler),
			patch.object(
				simulatedDisplay,
				"_getActivePresentation",
				return_value=_makeGraphicPresentation(),
			),
		):
			simulatedDisplay.renderTactileBytes(bytes([0x00, 0x00]))

		graphicDisplay.display.assert_called_once()
		(buf,) = graphicDisplay.display.call_args.args
		self.assertIsInstance(buf, DpTactileGraphicsBuffer)
		self.assertEqual(buf.hCellCount, 2)
		self.assertEqual(buf.vCellCount, 1)

	def test_renderPathPermutesKnownDots(self) -> None:
		"""Specific braille patterns produce the expected DotPad pin encoding.

		Locks the standard-braille → DotPad-pin permutation. Even though
		the permutation lives in ``tactile.braille.drawBrailleCells``
		(reused not re-implemented), regressions in either the source
		function or the way we call it would be caught here.

		Mappings (per CLAUDE.md + ``_brailleDotCoords`` + ``setDot`` bit math):
		- braille 0x01 (only dot 1)  → pin 0x01 (only pin 1, top-left)
		- braille 0x80 (only dot 8)  → pin 0x80 (only pin 8, bottom-right)
		- braille 0x40 (only dot 7)  → pin 0x08 (only pin 4, bottom-left)
		- braille 0xFF (all 8 dots)  → pin 0xFF (all 8 pins)
		"""
		from addon.tactileDisplayAPI import simulatedDisplay

		cases = [
			(0x01, 0x01, "dot 1 → pin 1"),
			(0x80, 0x80, "dot 8 → pin 8"),
			(0x40, 0x08, "dot 7 → pin 4 (the canonical 'swapped' bit)"),
			(0xFF, 0xFF, "all dots → all pins"),
		]
		for braille, expectedPin, msg in cases:
			with self.subTest(case=msg):
				graphicDisplay = _makeGraphicDisplayMock(physicalNumCols=1, physicalNumRows=1)
				brailleHandler = MagicMock()
				brailleHandler.display.graphicDisplay = graphicDisplay

				with (
					patch.object(
						simulatedDisplay,
						"_getBrailleHandler",
						return_value=brailleHandler,
					),
					patch.object(
						simulatedDisplay,
						"_getActivePresentation",
						return_value=_makeGraphicPresentation(),
					),
				):
					simulatedDisplay.renderTactileBytes(bytes([braille]))

				(buf,) = graphicDisplay.display.call_args.args
				self.assertEqual(
					buf.getRowCells(0)[0],
					expectedPin,
					f"{msg}: braille 0x{braille:02X} → expected pin 0x{expectedPin:02X}, got 0x{buf.getRowCells(0)[0]:02X}",
				)

	def test_renderPathHandlesShortPayload(self) -> None:
		"""Payload shorter than `physicalNumRows * physicalNumCols` doesn't raise.

		Short payloads result in trailing zero cells (buffer starts
		zero-initialised; we only fill rows we have data for).
		"""
		from addon.tactileDisplayAPI import simulatedDisplay

		graphicDisplay = _makeGraphicDisplayMock(physicalNumCols=2, physicalNumRows=2)
		brailleHandler = MagicMock()
		brailleHandler.display.graphicDisplay = graphicDisplay

		# Two-byte payload but 4-cell display: row 0 gets [0xFF, 0xFF], row 1 stays zero.
		with (
			patch.object(simulatedDisplay, "_getBrailleHandler", return_value=brailleHandler),
			patch.object(
				simulatedDisplay,
				"_getActivePresentation",
				return_value=_makeGraphicPresentation(),
			),
		):
			simulatedDisplay.renderTactileBytes(bytes([0xFF, 0xFF]))

		(buf,) = graphicDisplay.display.call_args.args
		self.assertEqual(bytes(buf.getRowCells(0)), bytes([0xFF, 0xFF]))
		self.assertEqual(bytes(buf.getRowCells(1)), bytes([0x00, 0x00]))

	def test_noGraphicDisplayIsNoOp(self) -> None:
		"""When ``graphicDisplay`` is None, the render path returns without raising."""
		from addon.tactileDisplayAPI import simulatedDisplay

		brailleHandler = MagicMock()
		brailleHandler.display.graphicDisplay = None

		with patch.object(simulatedDisplay, "_getBrailleHandler", return_value=brailleHandler):
			# Must not raise.
			simulatedDisplay.renderTactileBytes(bytes([0xFF, 0xFF]))


class TestComputeSimulateDisplayArgs(unittest.TestCase):
	"""``computeSimulateDisplayArgs`` derives the SimulateDisplay arguments."""

	def test_dotCountsAreCellsTimesPixelSize(self) -> None:
		"""Library expects dot counts, not cell counts.

		The helper MUST multiply ``physicalNumRows/Cols`` by ``cellHeight/cellWidth``
		to produce dot counts (per vendor docs and user clarification).
		"""
		from addon.tactileDisplayAPI import simulatedDisplay

		graphicDisplay = _makeGraphicDisplayMock(physicalNumCols=30, physicalNumRows=10)
		textDisplay = MagicMock(name="textDisplay")
		textDisplay.physicalNumRows = 1
		textDisplay.physicalNumCols = 20

		brailleHandler = MagicMock()
		brailleHandler.display.graphicDisplay = graphicDisplay
		brailleHandler.display.textDisplay = textDisplay
		brailleHandler.display._deviceName = "DotPad300A"

		with patch.object(simulatedDisplay, "_getBrailleHandler", return_value=brailleHandler):
			args = simulatedDisplay.computeSimulateDisplayArgs()

		displayName, dotsX, dotsY, totalCells, lineCount = args
		self.assertEqual(displayName, "DotPad300A")
		self.assertEqual(dotsX, 30 * 2)  # 60 dots wide
		self.assertEqual(dotsY, 10 * 4)  # 40 dots tall
		self.assertEqual(totalCells, 1 * 20)  # 20 braille cells
		self.assertEqual(lineCount, 1)

	def test_noTextDisplayPassesZeroCells(self) -> None:
		"""DotPad models without a separate text display use 0 / 0 for braille args."""
		from addon.tactileDisplayAPI import simulatedDisplay

		graphicDisplay = _makeGraphicDisplayMock(physicalNumCols=30, physicalNumRows=10)
		brailleHandler = MagicMock()
		brailleHandler.display.graphicDisplay = graphicDisplay
		brailleHandler.display.textDisplay = None
		brailleHandler.display._deviceName = "DotPadGraphicOnly"

		with patch.object(simulatedDisplay, "_getBrailleHandler", return_value=brailleHandler):
			args = simulatedDisplay.computeSimulateDisplayArgs()

		_, _, _, totalCells, lineCount = args
		self.assertEqual(totalCells, 0)
		self.assertEqual(lineCount, 0)


if __name__ == "__main__":
	unittest.main()
