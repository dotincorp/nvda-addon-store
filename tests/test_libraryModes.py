# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the driver asking the library which mode it is drawing in."""

from __future__ import annotations

import threading
import unittest
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any
from unittest.mock import MagicMock, patch

import comtypes

from addon.brailleDisplayDrivers.dotPad import driver as driverModule
from addon.brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver
from addon.extension_points.review_tracking import TriggerReason
from addon.tactileDisplayAPI.libraryModes import LibraryModes


class _Worker:
	"""Runs submissions only when told to, so a test controls what is outstanding."""

	def __init__(self) -> None:
		self.queued: list[tuple[Future[Any], Callable[..., Any], tuple[Any, ...]]] = []

	def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
		future: Future[Any] = Future()
		self.queued.append((future, fn, args))
		return future

	def runAll(self) -> None:
		while self.queued:
			future, fn, args = self.queued.pop(0)
			try:
				future.set_result(fn(*args))
			except BaseException as e:  # noqa: BLE001
				future.set_exception(e)


def _makeDriver(graphics: bool = False, hybrid: bool = False) -> Any:
	driver: Any = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
	driver._libraryReady = True
	driver._libraryWorker = _Worker()
	tda = MagicMock(name="tda")
	tda.getGraphicsMode.return_value = graphics
	tda.getHybridPrintAndBrailleMode.return_value = hybrid
	driver._tda = tda
	driver._renderer = MagicMock(name="renderer")
	driver._libraryModeLock = threading.Lock()
	return driver


class TestLibraryModeRefresh(unittest.TestCase):
	def setUp(self) -> None:
		patches = [
			patch.object(
				driverModule._libraryWorkerModule,
				"_dispatchToMain",
				side_effect=lambda fn, *args: fn(*args),
			),
			patch.object(driverModule._simulatedDisplay, "onLibraryModes"),
		]
		self.onLibraryModes = patches[1].start()
		patches[0].start()
		for p in patches:
			self.addCleanup(p.stop)

	def _refresh(self, driver: Any) -> None:
		driver.requestLibraryModeRefresh()
		driver._libraryWorker.runAll()

	def test_a_braille_report_changes_nothing(self) -> None:
		driver = _makeDriver()
		self._refresh(driver)
		self.assertEqual(driver.libraryModes, LibraryModes(graphics=False, hybrid=False, serial=1))
		driver._renderer.onReviewMove.assert_not_called()
		self.onLibraryModes.assert_called_once_with(driver.libraryModes)

	def test_a_hybrid_report_picks_the_presentation_again(self) -> None:
		driver = _makeDriver(hybrid=True)
		self._refresh(driver)
		driver._renderer.onReviewMove.assert_called_once_with(TriggerReason.LIBRARY_MODE_CHANGE)

	def test_the_same_report_again_only_advances_the_serial(self) -> None:
		driver = _makeDriver(graphics=True)
		self._refresh(driver)
		self._refresh(driver)
		driver._renderer.onReviewMove.assert_called_once()
		self.assertEqual(driver.libraryModes.serial, 2)

	def test_leaving_a_mode_picks_the_presentation_again(self) -> None:
		driver = _makeDriver(hybrid=True)
		self._refresh(driver)
		driver._tda.getHybridPrintAndBrailleMode.return_value = False
		self._refresh(driver)
		self.assertEqual(driver._renderer.onReviewMove.call_count, 2)

	def test_requests_while_outstanding_become_one_more_query(self) -> None:
		driver = _makeDriver()
		driver.requestLibraryModeRefresh()
		driver.requestLibraryModeRefresh()
		driver.requestLibraryModeRefresh()
		self.assertEqual(len(driver._libraryWorker.queued), 1)
		driver._libraryWorker.runAll()
		self.assertEqual(driver._tda.getGraphicsMode.call_count, 2)

	def test_a_library_without_the_getters_is_not_asked_again(self) -> None:
		driver = _makeDriver()
		driver._tda.getGraphicsMode.side_effect = AttributeError("GetGraphicsMode")
		self._refresh(driver)
		self.assertIsNone(driver.libraryModes)
		self.onLibraryModes.assert_called_once_with(None)
		driver.requestLibraryModeRefresh()
		self.assertEqual(driver._libraryWorker.queued, [])
		driver._renderer.onReviewMove.assert_not_called()

	def test_a_com_error_counts_as_no_getters(self) -> None:
		driver = _makeDriver()
		driver._tda.getGraphicsMode.side_effect = comtypes.COMError(-2147352570, "Unknown name", None)
		self._refresh(driver)
		self.assertIsNone(driver.libraryModes)
		driver.requestLibraryModeRefresh()
		self.assertEqual(driver._libraryWorker.queued, [])

	def test_any_other_com_error_is_tried_again_next_time(self) -> None:
		"""On a library that has the getters, a COM error is a real failure, and may pass."""
		driver = _makeDriver()
		driver._tda.getGraphicsMode.side_effect = comtypes.COMError(-2147467259, "Unspecified error", None)
		self._refresh(driver)
		self.assertIsNone(driver.libraryModes)
		self.onLibraryModes.assert_not_called()
		driver._tda.getGraphicsMode.side_effect = None
		driver._tda.getGraphicsMode.return_value = True
		self._refresh(driver)
		self.assertEqual(driver.libraryModes, LibraryModes(graphics=True, hybrid=False, serial=1))

	def test_a_failed_query_is_tried_again_next_time(self) -> None:
		driver = _makeDriver()
		driver._tda.getGraphicsMode.side_effect = RuntimeError("busy")
		self._refresh(driver)
		self.assertIsNone(driver.libraryModes)
		driver.requestLibraryModeRefresh()
		self.assertEqual(len(driver._libraryWorker.queued), 1)

	def test_nothing_is_asked_before_the_library_is_ready(self) -> None:
		driver = _makeDriver()
		driver._libraryReady = False
		driver.requestLibraryModeRefresh()
		self.assertEqual(driver._libraryWorker.queued, [])
		self.assertIsNone(driver.libraryModes)


if __name__ == "__main__":
	unittest.main()
