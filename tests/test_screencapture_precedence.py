# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Regression tests for feature 032: Screen Capture mode must take precedence over a
forced presentation.

Root cause (reproduced): a forced library-bytes view (e.g. forced library braille) is
permanently valid and `PresentationManager.update()` reuses a forced presentation before
consulting providers, so the screen-capture toggle was silently shadowed — the library's
autonomous braille kept showing. The fix clears the forced presentation when Screen Capture
is enabled, so the highest-priority screen-capture provider is selected.

These tests drive the real `PresentationManager` + real `ScreenCaptureProvider` through the
renderer's enable path (renderer built via `__new__` with only the needed attributes set, so
no full driver/display is required — mirrors tests/test_renderer_autoTrigger.py).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from addon.presentations.manager import PresentationManager
from addon.presentations.screenCapture import ScreenCaptureProvider


class _StubProvider:
	"""Minimal always-available fallback provider yielding a named presentation."""

	name = "stub"

	def canProvide(self, obj) -> bool:
		return True

	def createPresentation(self, obj, display):
		presentation = MagicMock(name="stubPresentation")
		presentation.name = "stub"
		presentation.isStillValid.return_value = True
		return presentation

	def forceForObject(self, obj, display):
		return None

	def terminate(self) -> None:
		pass


def _makeForced(name: str = "libraryBraille"):
	"""A sticky forced presentation (always valid), like forced library braille."""
	forced = MagicMock(name=f"forced-{name}")
	forced.name = name
	forced.isStillValid.return_value = True
	forced.provider = MagicMock(name="forcedProvider")
	return forced


def _makeRenderer(manager: PresentationManager, scProvider: ScreenCaptureProvider):
	"""Build a bare PresentationRenderer with just the attributes the toggle path uses."""
	from addon.presentations.renderer import PresentationRenderer

	renderer = PresentationRenderer.__new__(PresentationRenderer)
	renderer._presentationManager = manager
	renderer._screenCaptureProvider = scProvider
	renderer._isTerminating = False
	renderer.forceRefresh = False
	renderer._needsRender = False
	return renderer


class TestScreenCapturePrecedence(unittest.TestCase):
	def _setup(self):
		display = MagicMock(name="display")
		manager = PresentationManager(display)
		scProvider = ScreenCaptureProvider()
		manager.registerProvider(scProvider, moveToStart=True)
		manager.registerProvider(_StubProvider())  # fallback for the disabled case
		renderer = _makeRenderer(manager, scProvider)
		return manager, scProvider, renderer

	def test_set_enable_overrides_forced_view(self):
		"""FR-001: enabling Screen Capture over a sticky forced view makes SC active."""
		manager, _sc, renderer = self._setup()
		manager._forcedPresentation = _makeForced("libraryBraille")
		with patch("api.getNavigatorObject", return_value=MagicMock(), create=True):
			renderer.setScreenCaptureMode(True)
		self.assertEqual(manager.activePresentation.name, "screenCapture")
		self.assertIsNone(manager.forcedPresentation)

	def test_toggle_enable_overrides_forced_view(self):
		"""FR-001 via the toggle entry point."""
		manager, _sc, renderer = self._setup()
		manager._forcedPresentation = _makeForced("libraryBraille")
		with patch("api.getNavigatorObject", return_value=MagicMock(), create=True):
			newState = renderer.toggleScreenCaptureMode()
		self.assertTrue(newState)
		self.assertEqual(manager.activePresentation.name, "screenCapture")
		self.assertIsNone(manager.forcedPresentation)

	def test_precedence_over_any_forced_view(self):
		"""FR-004: precedence holds regardless of which view was forced."""
		for forcedName in ("braille", "libraryBraille", "graphic", "table"):
			with self.subTest(forced=forcedName):
				manager, _sc, renderer = self._setup()
				manager._forcedPresentation = _makeForced(forcedName)
				with patch("api.getNavigatorObject", return_value=MagicMock(), create=True):
					renderer.setScreenCaptureMode(True)
				self.assertEqual(manager.activePresentation.name, "screenCapture")

	def test_no_forced_enable_still_selects_screen_capture(self):
		"""FR-005: with nothing forced, enabling Screen Capture works as before."""
		manager, _sc, renderer = self._setup()
		with patch("api.getNavigatorObject", return_value=MagicMock(), create=True):
			renderer.setScreenCaptureMode(True)
		self.assertEqual(manager.activePresentation.name, "screenCapture")

	def test_disable_returns_to_provider_selection_and_forgets_force(self):
		"""FR-003/FR-006: disabling resumes provider selection; forced view not restored."""
		manager, _sc, renderer = self._setup()
		manager._forcedPresentation = _makeForced("libraryBraille")
		with patch("api.getNavigatorObject", return_value=MagicMock(), create=True):
			renderer.setScreenCaptureMode(True)
			self.assertEqual(manager.activePresentation.name, "screenCapture")
			renderer.setScreenCaptureMode(False)
		# Falls back to the provider chain (stub), NOT the previously-forced view.
		self.assertEqual(manager.activePresentation.name, "stub")
		self.assertIsNone(manager.forcedPresentation)


if __name__ == "__main__":
	unittest.main()
