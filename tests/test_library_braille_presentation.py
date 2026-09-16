# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for ``LibraryBraillePresentation`` (feature 017).

The library-driven multi-line braille presentation is a near-passive
marker: ``render()`` returns ``None``, ``terminate()`` clears the
library's display, and ``scrollBack/Forward()`` submit
``ExecuteOperation(PanLeft / PanRight)``. The library does the
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
	driver.libraryModes = None
	return driver


class TestLibraryBraillePresentationBasics(unittest.TestCase):
	"""Construction, name, and render contract."""

	def test_init_calls_super(self) -> None:
		"""``super().__init__()`` runs so ``_gestureMap`` is populated."""
		presentation = _makePresentation()
		self.assertTrue(hasattr(presentation, "_gestureMap"))
		self.assertIsInstance(presentation._gestureMap, dict)

	def test_init_switches_the_library_to_braille_and_restores_hybrid(self) -> None:
		"""``__init__`` has the driver switch to braille with hybrid restored; nothing else."""
		from addon.presentations.braille import LibraryBraillePresentation

		driver = _makeReadyDriver()
		with patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver):
			LibraryBraillePresentation(MagicMock(name="display"))

		driver.showLibraryBraille.assert_called_once_with(restoreHybrid=True)
		driver._libraryWorker.submit.assert_not_called()
		driver._libraryWorker.submitAndReport.assert_not_called()

	def test_init_without_driver_does_nothing(self) -> None:
		from addon.presentations.braille import LibraryBraillePresentation

		with patch("addon.presentations.braille._getActiveDotPadDriver", return_value=None):
			LibraryBraillePresentation(MagicMock(name="display"))  # must not raise

	def test_name_is_libraryBraille(self) -> None:
		"""Distinct name so the renderer's transition hooks can tell presentations apart."""
		presentation = _makePresentation()
		self.assertEqual(presentation.name, "libraryBraille")

	def test_render_returns_none(self) -> None:
		"""``render()`` returns ``None`` — the library writes the area autonomously."""
		presentation = _makePresentation()
		result = presentation.render(MagicMock(name="display"))
		self.assertIsNone(result)


class TestLibraryBraillePresentationHybridHold(unittest.TestCase):
	"""Leaving hybrid print keeps braille on that field and gives hybrid back on the next one."""

	def _leaveHybridPrint(self, field: object):
		from addon.presentations.braille import LibraryBraillePresentation
		from addon.tactileDisplayAPI.libraryModes import LibraryModes

		driver = _makeReadyDriver()
		driver.libraryModes = LibraryModes(graphics=True, hybrid=True, serial=3)
		with (
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
			patch("api.getNavigatorObject", return_value=field),
		):
			presentation = LibraryBraillePresentation(MagicMock(name="display"))
		return presentation, driver

	def _cycle(self, presentation, driver, navigator: object) -> None:
		with (
			patch.object(presentation, "_getActiveDriver", return_value=driver),
			patch("api.getNavigatorObject", return_value=navigator),
		):
			self.assertFalse(presentation.handleCoreCycle())

	def test_leaving_print_switches_without_restoring_hybrid(self) -> None:
		_presentation, driver = self._leaveHybridPrint(MagicMock(name="field"))
		driver.showLibraryBraille.assert_called_once_with(restoreHybrid=False)

	def test_hybrid_is_held_while_on_the_field(self) -> None:
		field = MagicMock(name="field")
		presentation, driver = self._leaveHybridPrint(field)
		self._cycle(presentation, driver, field)
		# NVDA mints a new object per event; an equal one is still the same field.
		sameField = MagicMock(name="sameField")
		sameField.__eq__.return_value = True
		self._cycle(presentation, driver, sameField)
		driver.applyHybridSetting.assert_not_called()

	def test_hybrid_returns_on_the_next_field(self) -> None:
		presentation, driver = self._leaveHybridPrint(MagicMock(name="field"))
		nextField = MagicMock(name="nextField")
		self._cycle(presentation, driver, nextField)
		self._cycle(presentation, driver, nextField)
		driver.applyHybridSetting.assert_called_once_with()


class TestLibraryBraillePresentationTerminate(unittest.TestCase):
	"""``terminate()`` clears the library's content."""

	def test_terminate_submits_clear(self) -> None:
		"""Submits ``tda.clear`` on the worker so leftover library content goes away."""
		presentation = _makePresentation()
		driver = _makeReadyDriver()
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			presentation.terminate()
		driver._libraryWorker.submit.assert_called_once_with(driver._tda.clear)

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
	"""FR-003a: F1/F4 scrolling via ``ExecuteOperation(PanLeft/PanRight)``.

	The braille-text pan, not the ``PanViewport*`` family: the shipped
	``[DotPad320X Keys]`` map gives f1-f4 the tactile-graphic viewport and the pan keys
	``PanLeft``/``PanRight``.
	"""

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

	def test_scrollBack_submits_pan_left(self) -> None:
		self._assertScrollSubmits("scrollBack", "PAN_LEFT")

	def test_scrollForward_submits_pan_right(self) -> None:
		self._assertScrollSubmits("scrollForward", "PAN_RIGHT")

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
