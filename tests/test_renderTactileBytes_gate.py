# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the presentation-aware gate in ``renderTactileBytes`` (feature 017).

``renderTactileBytes`` writes library bytes to the multi-line tactile
area ONLY when the active presentation is ``GraphicPresentation`` or
``LibraryBraillePresentation``. For any other presentation
(``BraillePresentation``, ``TablePresentation``, ``ChartPresentation``,
``ScreenCapturePresentation``, ``None``), bytes are discarded with a
debug log entry.

"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _makeGraphicDisplay():
	"""A mock ``graphicDisplay`` good enough for the buffer-build path."""
	display = MagicMock(name="graphicDisplay")
	display.physicalNumCols = 30
	display.physicalNumRows = 10
	display.cellHeight = 4
	return display


def _makePresentation(presentationClassPath: str):
	"""Construct a real presentation instance of the given class.

	Real instances are needed (not MagicMocks) because the gate checks
	``isinstance``. We bypass ``__init__`` via ``__new__`` and let
	``ScriptableObject`` defaults take over for the gate's purposes.
	"""
	module, className = presentationClassPath.rsplit(".", 1)
	cls = getattr(__import__(module, fromlist=[className]), className)
	return cls.__new__(cls)


class TestRenderTactileBytesGate(unittest.TestCase):
	"""FR-008: library bytes write only when a library-bytes-consumer is active."""

	def _runGate(self, activePresentation):
		"""Call ``renderTactileBytes`` with the given active presentation set."""
		from addon.tactileDisplayAPI import simulatedDisplay

		graphicDisplay = _makeGraphicDisplay()
		with (
			patch.object(simulatedDisplay, "_getGraphicDisplay", return_value=graphicDisplay),
			patch.object(simulatedDisplay, "_getActivePresentation", return_value=activePresentation),
		):
			# Payload size: 30 cols × 10 rows = 300 bytes.
			simulatedDisplay.renderTactileBytes(b"\x00" * (30 * 10))
		return graphicDisplay

	def test_gate_passes_for_graphic_presentation(self) -> None:
		"""GraphicPresentation active → bytes reach graphicDisplay.display."""
		presentation = _makePresentation("addon.presentations.graphic.GraphicPresentation")
		graphicDisplay = self._runGate(presentation)
		graphicDisplay.display.assert_called_once()

	def test_gate_passes_for_library_braille_presentation(self) -> None:
		"""LibraryBraillePresentation active → bytes reach graphicDisplay.display."""
		presentation = _makePresentation("addon.presentations.braille.LibraryBraillePresentation")
		graphicDisplay = self._runGate(presentation)
		graphicDisplay.display.assert_called_once()

	def test_gate_discards_for_nvda_braille_presentation(self) -> None:
		"""BraillePresentation active → bytes discarded (US2 no-regression)."""
		presentation = _makePresentation("addon.presentations.braille.BraillePresentation")
		graphicDisplay = self._runGate(presentation)
		graphicDisplay.display.assert_not_called()

	def test_gate_discards_for_table_presentation(self) -> None:
		presentation = _makePresentation("addon.presentations.table.TablePresentation")
		graphicDisplay = self._runGate(presentation)
		graphicDisplay.display.assert_not_called()

	def test_gate_discards_for_chart_presentation(self) -> None:
		presentation = _makePresentation("addon.presentations.chart.ChartPresentation")
		graphicDisplay = self._runGate(presentation)
		graphicDisplay.display.assert_not_called()

	def test_gate_discards_for_screen_capture_presentation(self) -> None:
		presentation = _makePresentation("addon.presentations.screenCapture.ScreenCapturePresentation")
		graphicDisplay = self._runGate(presentation)
		graphicDisplay.display.assert_not_called()

	def test_gate_discards_when_no_active_presentation(self) -> None:
		"""``activePresentation = None`` → discard, no write."""
		graphicDisplay = self._runGate(None)
		graphicDisplay.display.assert_not_called()

	def test_gate_safe_when_driver_chain_broken(self) -> None:
		"""``_getActivePresentation`` returns ``None`` because chain is broken.

		The function MUST NOT raise — it logs and returns.
		"""
		from addon.tactileDisplayAPI import simulatedDisplay

		with (
			patch.object(simulatedDisplay, "_getGraphicDisplay", return_value=None),
			patch.object(simulatedDisplay, "_getActivePresentation", return_value=None),
		):
			# Must not raise.
			simulatedDisplay.renderTactileBytes(b"\x00" * 300)


if __name__ == "__main__":
	unittest.main()
