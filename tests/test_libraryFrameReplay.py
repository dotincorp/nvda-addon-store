# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for replaying the library's last braille frame.

Leaving a presentation that drew the tactile area itself — table, chart, screen
capture — used to leave that drawing on the pins, because the library-braille
presentation writes nothing of its own and the library has no reason to emit a
fresh frame for a mode it is already in. The frame to show already exists: the
library keeps sending them throughout, and the gate discards them.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def makeGraphicDisplay():
	display = MagicMock(name="graphicDisplay")
	display.physicalNumCols = 30
	display.physicalNumRows = 10
	display.cellHeight = 4
	return display


def makePresentation(classPath: str):
	"""A real instance, bypassing __init__ — the gate checks isinstance."""
	module, className = classPath.rsplit(".", 1)
	cls = getattr(__import__(module, fromlist=[className]), className)
	return cls.__new__(cls)


class TestPayloadIsRemembered(unittest.TestCase):
	def setUp(self):
		from addon.tactileDisplayAPI import simulatedDisplay

		self.simulatedDisplay = simulatedDisplay
		simulatedDisplay.forgetLastPayload()
		self.addCleanup(simulatedDisplay.forgetLastPayload)
		self.graphicDisplay = makeGraphicDisplay()

	def _send(self, payload: bytes, activePresentation) -> None:
		with (
			patch.object(self.simulatedDisplay, "_getGraphicDisplay", return_value=self.graphicDisplay),
			patch.object(
				self.simulatedDisplay,
				"_getActivePresentation",
				return_value=activePresentation,
			),
		):
			self.simulatedDisplay.renderTactileBytes(payload)

	def _replay(self) -> bool:
		with patch.object(self.simulatedDisplay, "_getGraphicDisplay", return_value=self.graphicDisplay):
			return self.simulatedDisplay.replayLastPayload()

	def test_a_discarded_frame_is_still_remembered(self):
		"""The frame arriving while a table is up is the one to show on the way out."""
		table = makePresentation("addon.presentations.table.TablePresentation")

		self._send(b"\x01" * 300, table)

		self.graphicDisplay.display.assert_not_called()
		self.assertTrue(self._replay())
		self.graphicDisplay.display.assert_called_once()

	def test_replaying_without_a_frame_reports_nothing_to_show(self):
		self.assertFalse(self._replay())
		self.graphicDisplay.display.assert_not_called()

	def test_the_most_recent_frame_wins(self):
		table = makePresentation("addon.presentations.table.TablePresentation")
		self._send(b"\x01" * 300, table)
		self._send(b"\x02" * 300, table)

		self._replay()

		buffer = self.graphicDisplay.display.call_args.args[0]
		self.assertTrue(any(buffer.getRowCells(0)), "the replayed frame should not be blank")

	def test_a_frame_that_passed_the_gate_is_remembered_too(self):
		"""So a switch away and back does not need the library to speak first."""
		braille = makePresentation("addon.presentations.braille.LibraryBraillePresentation")

		self._send(b"\x01" * 300, braille)
		self.graphicDisplay.display.reset_mock()

		self.assertTrue(self._replay())
		self.graphicDisplay.display.assert_called_once()

	def test_a_frame_sent_under_graphic_mode_is_not_remembered(self):
		"""Those carry the image, so replaying one would redraw the picture."""
		graphic = makePresentation("addon.presentations.graphic.GraphicPresentation")

		self._send(b"\x01" * 300, graphic)
		self.graphicDisplay.display.reset_mock()

		self.assertFalse(self._replay())
		self.graphicDisplay.display.assert_not_called()

	def test_graphic_mode_does_not_overwrite_an_earlier_braille_frame(self):
		"""The braille frame from before the image is still the way back."""
		table = makePresentation("addon.presentations.table.TablePresentation")
		graphic = makePresentation("addon.presentations.graphic.GraphicPresentation")

		self._send(b"\x01" * 300, table)
		self._send(b"\x02" * 300, graphic)
		self.graphicDisplay.display.reset_mock()

		self.assertTrue(self._replay())
		self.graphicDisplay.display.assert_called_once()


class TestLibraryBrailleReplaysOnce(unittest.TestCase):
	"""The presentation asks for the replay on its first render, then stops."""

	def _makePresentation(self):
		from addon.presentations.braille import LibraryBraillePresentation

		presentation = LibraryBraillePresentation.__new__(LibraryBraillePresentation)
		presentation._display = MagicMock(name="display")
		presentation._hasReplayed = False
		return presentation

	def test_first_render_replays(self):
		presentation = self._makePresentation()
		with patch.object(presentation, "_replayLastLibraryFrame") as replay:
			self.assertIsNone(presentation.render(MagicMock()))

		replay.assert_called_once_with()

	def test_later_renders_do_not(self):
		"""A newer frame from the library must not be undone by an old one."""
		presentation = self._makePresentation()
		with patch.object(presentation, "_replayLastLibraryFrame") as replay:
			presentation.render(MagicMock())
			presentation.render(MagicMock())
			presentation.render(MagicMock())

		replay.assert_called_once_with()

	def test_a_failing_replay_does_not_break_the_render(self):
		presentation = self._makePresentation()
		with patch.object(
			presentation,
			"_replayLastLibraryFrame",
			side_effect=RuntimeError("no display"),
		):
			self.assertIsNone(presentation.render(MagicMock()))


class TestTheNvdaDrivenFallbackNeedsNoReplay(unittest.TestCase):
	"""Only the library-driven presentation depends on the replay.

	The replay exists because ``LibraryBraillePresentation`` writes nothing of
	its own, so leaving a table would leave the table on the pins. The
	NVDA-driven presentation - what the provider builds when the braille source
	is NVDA, when the library is still starting, and when it is unavailable -
	paints the tactile area itself, so the outgoing drawing is overwritten by
	its first render. Should that ever start returning None to match its
	sibling, f2+f4 would quietly stop working for everyone not using the
	library.
	"""

	def test_it_renders_a_buffer_rather_than_nothing(self):
		from addon.brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
		from addon.presentations.braille import BraillePresentation

		display = MagicMock()
		display.physicalNumCols = 30
		display.physicalNumRows = 10
		presentation = BraillePresentation.__new__(BraillePresentation)
		presentation._buffer = MagicMock(windowBrailleCells=[0] * 30, cursorWindowPos=None)

		self.assertIsInstance(presentation.render(display), DpTactileGraphicsBuffer)


if __name__ == "__main__":
	unittest.main()
