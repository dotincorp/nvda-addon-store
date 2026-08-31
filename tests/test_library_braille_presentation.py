# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for ``LibraryBraillePresentation`` (feature 017).

The library-driven multi-line braille presentation is a near-passive
marker: ``render()`` returns ``None``, ``terminate()`` clears the
library's display, and ``scrollBack/Forward()`` submit
``ExecuteOperation(PAN_VIEWPORT_UP / DOWN)``. The library does the
actual rendering autonomously via ``RegisterEvents(true)``.

"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _makePresentation():
	"""Construct a ``LibraryBraillePresentation`` with a mocked display."""
	from addon.presentations.braille import LibraryBraillePresentation

	display = MagicMock(name="display")
	return LibraryBraillePresentation(display)


def _makeReadyDriver():
	driver = MagicMock(name="driver")
	driver._libraryReady = True
	driver._libraryWorker = MagicMock(name="worker")
	driver._tda = MagicMock(name="tda")
	return driver


class TestLibraryBraillePresentationBasics(unittest.TestCase):
	"""Construction, name, and render contract."""

	def test_init_calls_super(self) -> None:
		"""``super().__init__()`` runs so ``_gestureMap`` is populated."""
		presentation = _makePresentation()
		self.assertTrue(hasattr(presentation, "_gestureMap"))
		self.assertIsInstance(presentation._gestureMap, dict)

	def test_init_bootstraps_text_mode_then_enables_events(self) -> None:
		"""``__init__`` submits just the text-mode switch, then enables events:

		1. ``ExecuteOperation(SHOW_OBJECT_AT_CURSOR_AS_BRAILLE)`` — switch
		   to text mode (defensive; defaults to graphics on some libraries),
		   which may also render the object at the cursor.

		The explicit ``AddFocusedControl`` kick-start and the older
		``ShowMultilineText`` warm-up are both currently disabled — we're
		testing whether the text-mode switch alone is sufficient.
		"""
		from addon.presentations.braille import LibraryBraillePresentation
		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		display = MagicMock(name="display")
		driver = _makeReadyDriver()
		with patch(
			"addon.presentations.braille._getActiveDotPadDriver",
			return_value=driver,
		):
			LibraryBraillePresentation(display)

		# One submission: the text-mode switch.
		self.assertEqual(driver._libraryWorker.submitAndReport.call_count, 1)
		calls = driver._libraryWorker.submitAndReport.call_args_list
		self.assertIs(calls[0].args[0], driver._tda.executeOperation)
		self.assertEqual(
			calls[0].args[1],
			BrailleInputOperation.SHOW_OBJECT_AT_CURSOR_AS_BRAILLE,
		)
		# addFocusedControl and the ShowMultilineText warm-up are disabled.
		submittedFns = [c.args[0] for c in calls]
		self.assertNotIn(driver._tda.addFocusedControl, submittedFns)
		self.assertNotIn(driver._tda.showMultilineText, submittedFns)
		# The library's autonomous UIA subscription is enabled only AFTER the
		# blocking bootstrap (events-off bootstrap avoids the STA-pump-starve
		# heap-corruption crash).
		driver.enableLibraryUiaEvents.assert_called_once_with()

	def test_init_skips_bootstrap_when_library_not_ready(self) -> None:
		"""Bootstrap is a defensive no-op when the driver / library aren't ready."""
		from addon.presentations.braille import LibraryBraillePresentation

		display = MagicMock(name="display")
		driver = _makeReadyDriver()
		driver._libraryReady = False
		with patch(
			"addon.presentations.braille._getActiveDotPadDriver",
			return_value=driver,
		):
			LibraryBraillePresentation(display)
		driver._libraryWorker.submit.assert_not_called()
		driver._libraryWorker.submitAndReport.assert_not_called()

	def test_name_is_libraryBraille(self) -> None:
		"""Distinct name so the renderer's transition hooks can tell presentations apart."""
		presentation = _makePresentation()
		self.assertEqual(presentation.name, "libraryBraille")

	def test_render_returns_none(self) -> None:
		"""``render()`` returns ``None`` — the library writes the area autonomously."""
		presentation = _makePresentation()
		result = presentation.render(MagicMock(name="display"))
		self.assertIsNone(result)


class TestLibraryBraillePresentationTerminate(unittest.TestCase):
	"""``terminate()`` clears the library's content."""

	def test_terminate_submits_clear(self) -> None:
		"""Submits ``tda.clear`` on the worker so leftover library content goes away."""
		presentation = _makePresentation()
		driver = _makeReadyDriver()
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			presentation.terminate()
		driver._libraryWorker.submit.assert_called_once_with(driver._tda.clear)
		# Leaving library-braille mode turns the autonomous UIA subscription off
		# so later explicit blocking ExecuteOperation calls run events-off.
		driver.disableLibraryUiaEvents.assert_called_once_with()

	def test_terminate_noop_when_driver_unavailable(self) -> None:
		"""No driver → silent return, no exception."""
		presentation = _makePresentation()
		with patch.object(presentation, "_getActiveDriver", return_value=None):
			presentation.terminate()  # must not raise

	def test_terminate_noop_when_library_not_ready(self) -> None:
		"""``_libraryReady = False`` → silent return."""
		presentation = _makePresentation()
		driver = _makeReadyDriver()
		driver._libraryReady = False
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			presentation.terminate()
		driver._libraryWorker.submit.assert_not_called()


class TestLibraryBraillePresentationScroll(unittest.TestCase):
	"""FR-003a: F1/F4 scrolling via ``ExecuteOperation(PAN_VIEWPORT_UP/DOWN)``."""

	def _assertScrollSubmits(self, scrollMethodName: str, expectedOpName: str) -> None:
		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		presentation = _makePresentation()
		driver = _makeReadyDriver()
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			getattr(presentation, scrollMethodName)()

		# The worker received exactly one submission.
		driver._libraryWorker.submitAndReport.assert_called_once()
		args, _kwargs = driver._libraryWorker.submitAndReport.call_args
		# args[0] is the callable, args[1] is the operation.
		self.assertIs(args[0], driver._tda.executeOperation)
		self.assertEqual(args[1], getattr(BrailleInputOperation, expectedOpName))

	def test_scrollBack_submits_pan_viewport_up(self) -> None:
		self._assertScrollSubmits("scrollBack", "PAN_VIEWPORT_UP")

	def test_scrollForward_submits_pan_viewport_down(self) -> None:
		self._assertScrollSubmits("scrollForward", "PAN_VIEWPORT_DOWN")

	def test_scroll_noop_when_driver_unavailable(self) -> None:
		"""No driver → no worker submission."""
		presentation = _makePresentation()
		with patch.object(presentation, "_getActiveDriver", return_value=None):
			presentation.scrollBack()
			presentation.scrollForward()

	def test_scroll_noop_when_library_not_ready(self) -> None:
		"""Library not ready → no worker submission."""
		presentation = _makePresentation()
		driver = _makeReadyDriver()
		driver._libraryReady = False
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			presentation.scrollBack()
			presentation.scrollForward()
		driver._libraryWorker.submitAndReport.assert_not_called()

	def test_scroll_noop_when_worker_none(self) -> None:
		"""Worker missing → no submission."""
		presentation = _makePresentation()
		driver = _makeReadyDriver()
		driver._libraryWorker = None
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			presentation.scrollBack()  # must not raise

	def test_scroll_noop_when_tda_none(self) -> None:
		"""``_tda`` missing → no submission."""
		presentation = _makePresentation()
		driver = _makeReadyDriver()
		driver._tda = None
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			presentation.scrollBack()
		driver._libraryWorker.submitAndReport.assert_not_called()


if __name__ == "__main__":
	unittest.main()
