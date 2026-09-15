# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the hybrid print presentation and its provider."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from addon.extension_points.review_tracking import TriggerReason
from addon.presentations import graphic
from addon.presentations.base import Presentation, PresentationProvider
from addon.presentations.graphic import GraphicPresentation, HybridPrintPresentation, HybridPrintProvider
from addon.presentations.manager import PresentationManager
from addon.tactileDisplayAPI.libraryModes import LibraryModes
from tests.test_graphic_presentation_scripts import _EXPECTED_BINDINGS

_HYBRID = LibraryModes(graphics=True, hybrid=True, serial=1)
_HYBRID_BRAILLE = LibraryModes(graphics=False, hybrid=True, serial=1)
_BRAILLE = LibraryModes(graphics=False, hybrid=False, serial=1)
_GRAPHICS = LibraryModes(graphics=True, hybrid=False, serial=1)


class TestHybridPrintProvider(unittest.TestCase):
	def _canProvide(self, modes: LibraryModes | None, source: Any = None) -> bool:
		BrailleSource = graphic.configuration.BrailleSource
		with (
			patch.object(
				graphic.configuration,
				"getBrailleSource",
				return_value=source if source is not None else BrailleSource.LIBRARY,
			),
			patch.object(graphic, "_getLibraryModes", return_value=modes),
		):
			return HybridPrintProvider().canProvide(MagicMock(name="navigator"))

	def test_library_drawing_print(self) -> None:
		self.assertTrue(self._canProvide(_HYBRID))

	def test_library_drawing_braille(self) -> None:
		self.assertFalse(self._canProvide(_BRAILLE))

	def test_hybrid_enabled_while_braille_is_shown(self) -> None:
		"""The hybrid getter follows the setting, so it alone does not mean print."""
		self.assertFalse(self._canProvide(_HYBRID_BRAILLE))

	def test_library_drawing_an_image(self) -> None:
		self.assertFalse(self._canProvide(_GRAPHICS))

	def test_no_report(self) -> None:
		self.assertFalse(self._canProvide(None))

	def test_nvda_source(self) -> None:
		self.assertFalse(self._canProvide(_HYBRID, source=graphic.configuration.BrailleSource.NVDA))


class TestHybridPrintPresentation(unittest.TestCase):
	def setUp(self) -> None:
		self.presentation = HybridPrintPresentation(MagicMock(name="obj"), MagicMock(name="display"))

	def test_is_a_graphic_presentation_by_another_name(self) -> None:
		"""The subclass is what opens the byte gate and keeps print out of the replay."""
		self.assertIsInstance(self.presentation, GraphicPresentation)
		self.assertEqual(self.presentation.name, "hybridPrint")

	def test_stays_valid_on_caret_move(self) -> None:
		self.assertTrue(self.presentation.isStillValid(TriggerReason.CARET_MOVE))

	def test_render_and_terminate_submit_nothing(self) -> None:
		driver = MagicMock(name="driver")
		driver._libraryReady = True
		with patch.object(self.presentation, "_getActiveDriver", return_value=driver):
			self.assertIsNone(self.presentation.render(MagicMock()))
			self.presentation.terminate()
		driver._libraryWorker.submitAndReport.assert_not_called()
		driver._libraryWorker.submit.assert_not_called()

	def test_dismiss_chord_is_swallowed(self) -> None:
		script = self.presentation._gestureMap["br(dotpad):f2+f4"]
		self.assertEqual(script.__name__, "script_suppressDismissal")

	def test_keeps_graphic_bindings(self) -> None:
		for gestureId, _operation in _EXPECTED_BINDINGS:
			self.assertIn(gestureId, self.presentation._gestureMap)


class _StubBraillePresentation(Presentation):
	@property
	def name(self) -> str:
		return "braille"

	def render(self, display: Any) -> None:
		return None

	def scrollForward(self) -> bool:
		return False

	def scrollBack(self) -> bool:
		return False


class _StubBrailleProvider(PresentationProvider):
	isFallback = True

	@property
	def name(self) -> str:
		return "braille"

	def canProvide(self, obj: Any) -> bool:
		return True

	def _doCreatePresentation(self, obj: Any, display: Any) -> Presentation:
		return _StubBraillePresentation()


class TestManagerFollowsTheLibrary(unittest.TestCase):
	def setUp(self) -> None:
		self.manager = PresentationManager(MagicMock(name="display"))  # type: ignore[arg-type]
		self.manager.registerProvider(HybridPrintProvider())
		self.manager.registerProvider(_StubBrailleProvider())
		self.modes: LibraryModes | None = _HYBRID
		patches = [
			patch.object(
				graphic.configuration,
				"getBrailleSource",
				return_value=graphic.configuration.BrailleSource.LIBRARY,
			),
			patch.object(graphic, "_getLibraryModes", side_effect=lambda: self.modes),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_print_then_braille(self) -> None:
		navigator = MagicMock(name="navigator")
		self.manager.update(navigator, TriggerReason.LIBRARY_MODE_CHANGE)
		hybrid = self.manager.activePresentation
		self.assertIsInstance(hybrid, HybridPrintPresentation)

		self.manager.update(navigator, TriggerReason.CARET_MOVE)
		self.assertIs(self.manager.activePresentation, hybrid)

		self.modes = _HYBRID_BRAILLE
		self.manager.update(navigator, TriggerReason.LIBRARY_MODE_CHANGE)
		self.assertIsInstance(self.manager.activePresentation, _StubBraillePresentation)


if __name__ == "__main__":
	unittest.main()
