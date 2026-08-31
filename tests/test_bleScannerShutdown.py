# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for stopping the BLE scan inside NVDA's shutdown sequence.

NVDA closes its asyncio event loop in ``core._terminate(_asyncioEventLoop)``, which runs
after the last chance an addon gets to act and before any ``atexit`` handler. A scan
still running at that point leaves a live WinRT advertisement watcher whose callback
does ``call_soon_threadsafe`` on the closed loop, so every advertisement in radio range
raises ``RuntimeError: Event loop is closed`` on a WinRT thread-pool thread.

The scan therefore has to stop while the loop is still alive, from
``DotPadGlobalPlugin.terminate()`` -- NVDA calls that in
``_handleNVDAModuleCleanupBeforeGUIExit``, well before braille, bdDetect, hwIo and the
loop itself are torn down.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from addon.ble import scanner as bleScanner
from addon.ble.detection import Detector


async def _noop() -> None:
	"""Stand-in for ``BleakScanner.stop()``, which returns a coroutine."""


def _consume(coro, *_args) -> None:
	"""Stand in for the loop utils, closing the coroutine as a real scheduler would.

	Without this the mocked scheduler drops it and Python warns that it was never
	awaited -- noise that would mask the real thing this change removes.
	"""
	coro.close()


def _scanner(stopResult: object | None = None) -> bleScanner.Scanner:
	"""A real ``Scanner`` wrapping a mocked ``BleakScanner``."""
	with patch.object(bleScanner.bleak, "BleakScanner"):
		scanner = bleScanner.Scanner()
	scanner._scanner.stop.return_value = stopResult if stopResult is not None else _noop()
	scanner._isScanning.set()
	return scanner


class _FakeScanner:
	"""A scanner whose ``isScanning`` actually tracks start/stop.

	``MagicMock`` cannot express that, and these tests turn entirely on whether a scan
	is left running.
	"""

	def __init__(self) -> None:
		self.isScanning = False
		self.deviceDiscovered = MagicMock()

	def start(self, duration: float = 0) -> None:
		self.isScanning = True

	def stop(self, wait: bool = False) -> None:
		self.isScanning = False

	def results(self, filterFunc=None) -> list[object]:
		return []


class TestTerminateRacesAScan(unittest.TestCase):
	"""``matches()`` runs on bdDetect's polling thread, ``terminate()`` on the main one.

	Latching is not enough on its own: the polling thread can pass the latch check just
	before the main thread sets it, and start the WinRT watcher just after the main
	thread finished stopping things. Nothing would then stop that watcher before the
	event loop closes -- the exact flood this change exists to remove.
	"""

	def _detector(self) -> Detector:
		detector = Detector()
		detector.addMatcher("dotPad", lambda device: True)
		return detector

	def test_a_scan_started_after_terminate_is_stopped_again(self) -> None:
		detector = self._detector()
		scanner = _FakeScanner()

		def resolveScanner() -> _FakeScanner:
			# terminate() lands after the latch check but before the scan is started,
			# which is the window bdDetect's thread can sit in.
			detector.terminate()
			return scanner

		with (
			patch("addon.ble.detection.createScanner", side_effect=resolveScanner),
			patch.object(bleScanner, "coreBle", None),
		):
			self.assertEqual([], list(detector.matches()))

		self.assertFalse(scanner.isScanning, "a scan started during terminate() must not outlive it")

	def test_terminate_keeps_the_scanner_it_stopped(self) -> None:
		"""Dropping the reference would leave a racing scan with nothing able to stop it."""
		detector = self._detector()
		scanner = MagicMock(isScanning=True)
		detector._scanner = scanner
		with patch("addon.ble.detection.stopScanner"):
			detector.terminate()

		self.assertIs(scanner, detector._scanner)

	def test_resume_re_resolves_the_scanner(self) -> None:
		"""A reloaded plugin should not reuse a scanner NVDA may have torn down."""
		detector = self._detector()
		detector._scanner = MagicMock(isScanning=False)
		with patch("addon.ble.detection.stopScanner"):
			detector.terminate()
		detector.resume()

		self.assertIsNone(detector._scanner)


class TestDetectorTerminationLatch(unittest.TestCase):
	"""After ``terminate()`` the detector must not start scanning again.

	``_terminate(globalPluginHandler)`` runs at core.py:578 but bdDetect keeps polling
	until ``_terminate(braille)`` at core.py:1119 -- and closing NVDA's windows in
	between causes app switches, which is exactly what ``post_appSwitch ->
	pollBluetoothDevices`` turns into another background scan.
	"""

	def _detector(self) -> Detector:
		detector = Detector()
		detector.addMatcher("dotPad", lambda device: True)
		return detector

	def test_matches_yields_nothing_after_terminate(self) -> None:
		detector = self._detector()
		detector.terminate()

		with patch("addon.ble.detection.createScanner") as createScanner:
			self.assertEqual([], list(detector.matches()))

		createScanner.assert_not_called()

	def test_matches_does_not_restart_a_stopped_scan(self) -> None:
		"""The real regression: a late bdDetect scan resurrecting the WinRT watcher."""
		detector = self._detector()
		scanner = MagicMock(isScanning=False)
		detector._scanner = scanner
		with patch("addon.ble.detection.stopScanner"):
			detector.terminate()

		list(detector.matches())

		scanner.start.assert_not_called()

	def test_resume_re_enables_detection(self) -> None:
		"""NVDA+Ctrl+F3 terminates global plugins without re-importing ble.detection.

		A latch that never clears would silently kill BLE detection for the rest of the
		NVDA session.
		"""
		detector = self._detector()
		detector.terminate()
		detector.resume()

		scanner = MagicMock(isScanning=False)
		scanner.results.return_value = []
		with patch("addon.ble.detection.createScanner", return_value=scanner):
			list(detector.matches())

		scanner.start.assert_called_once()

	def test_terminate_is_idempotent(self) -> None:
		detector = self._detector()
		scanner = MagicMock(isScanning=True)
		detector._scanner = scanner
		with patch("addon.ble.detection.stopScanner") as stopScanner:
			detector.terminate()
			detector.terminate()

		stopScanner.assert_called_once()

	def test_terminate_waits_for_the_scan_to_stop(self) -> None:
		"""Fire-and-forget would race NVDA's teardown of the loop the stop needs."""
		detector = self._detector()
		detector._scanner = MagicMock(isScanning=True)
		with patch("addon.ble.detection.stopScanner") as stopScanner:
			detector.terminate()

		self.assertTrue(stopScanner.call_args.kwargs.get("wait"))


class TestScannerStop(unittest.TestCase):
	"""``Scanner.stop`` blocks only when the caller needs the watcher really gone."""

	def test_stop_is_fire_and_forget_by_default(self) -> None:
		"""bdDetect's background scan calls this; it must not pay the round trip."""
		scanner = _scanner()
		with (
			patch.object(bleScanner, "runCoroutine", side_effect=_consume) as runCoroutine,
			patch.object(bleScanner, "runCoroutineSync", side_effect=_consume) as runCoroutineSync,
		):
			scanner.stop()

		runCoroutine.assert_called_once()
		runCoroutineSync.assert_not_called()

	def test_stop_waits_when_asked(self) -> None:
		scanner = _scanner()
		with (
			patch.object(bleScanner, "runCoroutine", side_effect=_consume) as runCoroutine,
			patch.object(bleScanner, "runCoroutineSync", side_effect=_consume) as runCoroutineSync,
		):
			scanner.stop(wait=True)

		runCoroutineSync.assert_called_once()
		self.assertEqual(
			bleScanner.STOP_TIMEOUT_SECONDS,
			runCoroutineSync.call_args.args[1],
			"a shutdown stop must be bounded, not indefinite",
		)
		runCoroutine.assert_not_called()

	def test_stop_clears_isScanning_when_scheduling_fails(self) -> None:
		"""Otherwise the flag wedges and matches() never restarts the scan."""
		scanner = _scanner()
		with patch.object(bleScanner, "runCoroutine", side_effect=RuntimeError("loop gone")):
			scanner.stop()

		self.assertFalse(scanner.isScanning)

	def test_stop_does_not_raise_when_the_loop_is_gone(self) -> None:
		scanner = _scanner()
		with patch.object(bleScanner, "runCoroutineSync", side_effect=RuntimeError("loop gone")):
			scanner.stop(wait=True)  # must not raise

	def test_timed_scan_stops_through_stop(self) -> None:
		"""So the timed path gets the same failure handling as every other stop."""
		scanner = _scanner()
		scanner._isScanning.clear()
		with (
			patch.object(bleScanner, "runCoroutine", side_effect=_consume),
			patch.object(bleScanner.Scanner, "stop", autospec=True) as stop,
		):
			scanner.start(duration=0.01)

		stop.assert_called_once_with(scanner)
		# stop() is mocked out here, so nothing consumed the coroutine it would have
		# scheduled. Left alone it warns, which is the noise _consume exists to avoid.
		scanner._scanner.stop.return_value.close()

	def test_stop_survives_a_coroutine_that_refuses_to_close(self) -> None:
		"""A timed-out wait leaves the coroutine running on the loop thread.

		Closing it then raises, and that must not escape into
		``DotPadGlobalPlugin.terminate()`` and skip the rest of its cleanup.
		"""
		coro = MagicMock()
		coro.close.side_effect = RuntimeError("coroutine is already executing")
		scanner = _scanner(stopResult=coro)
		with patch.object(bleScanner, "runCoroutineSync", side_effect=TimeoutError("timed out")):
			scanner.stop(wait=True)  # must not raise

		self.assertFalse(scanner.isScanning)

	def test_stop_does_not_leak_the_coroutine(self) -> None:
		"""A discarded coroutine is what produced the 'was never awaited' warning."""
		coro = _noop()
		scanner = _scanner(stopResult=coro)
		with patch.object(bleScanner, "runCoroutine", side_effect=RuntimeError("loop gone")):
			scanner.stop()

		self.assertIsNone(coro.cr_frame, "the coroutine must be closed, not abandoned")


class TestStopScannerWaitForwarding(unittest.TestCase):
	def test_forwards_wait_to_the_scanner(self) -> None:
		scanner = MagicMock(isScanning=True)
		with patch.object(bleScanner, "coreBle", None):
			bleScanner.stopScanner(scanner, wait=True)

		scanner.stop.assert_called_once_with(wait=True)

	def test_leaves_cores_shared_scanner_alone_even_at_shutdown(self) -> None:
		"""hwIo.terminate() stops core's scanner, and it does so before the loop closes."""
		scanner = MagicMock(isScanning=True)
		with patch.object(bleScanner, "coreBle", MagicMock(name="hwIo.ble")):
			bleScanner.stopScanner(scanner, wait=True)

		scanner.stop.assert_not_called()


class TestNoAtExitTeardown(unittest.TestCase):
	"""The atexit / ``__del__`` teardown is gone; it could never do anything useful.

	On 2026.2 anything reaching ``atexit`` already passed
	``_terminate(_asyncioEventLoop)``. On 2026.1 the backport registers its own
	``terminate`` on first use -- i.e. after ``ble.detection`` was imported -- and atexit
	is LIFO, so the loop dies first there too. Either way the handler only ever produced
	the traceback this change removes.
	"""

	def test_detector_has_no_del(self) -> None:
		self.assertFalse(hasattr(Detector, "__del__"))

	def test_module_registers_no_atexit_handler(self) -> None:
		from addon.ble import detection

		self.assertFalse(
			hasattr(detection, "terminate"),
			"the module-level atexit terminate() must be gone",
		)


class TestGlobalPluginStopsTheScan(unittest.TestCase):
	"""The global plugin is the hook that runs while the event loop is still alive."""

	def _plugin(self):
		from addon.globalPlugins.dotPad import DotPadGlobalPlugin

		with patch("gui.mainFrame") as mockFrame:
			mockFrame.sysTrayIcon = MagicMock()
			mockFrame.sysTrayIcon.toolsMenu = MagicMock()
			menuItem = MagicMock()
			menuItem.Id = 42
			mockFrame.sysTrayIcon.toolsMenu.AppendCheckItem.return_value = menuItem
			return DotPadGlobalPlugin()

	def test_terminate_terminates_the_detector(self) -> None:
		import addon.globalPlugins.dotPad as pluginModule

		plugin = self._plugin()
		detector = MagicMock()
		with (
			patch.object(pluginModule, "bleDetector", detector),
			patch("gui.mainFrame") as mockFrame,
			patch("gui.settingsDialogs.NVDASettingsDialog.categoryClasses", new=MagicMock()),
		):
			mockFrame.sysTrayIcon = MagicMock()
			mockFrame.sysTrayIcon.toolsMenu = MagicMock()
			plugin.terminate()

		detector.terminate.assert_called_once_with()

	def test_init_resumes_the_detector(self) -> None:
		"""Reloading plugins must bring detection back."""
		import addon.globalPlugins.dotPad as pluginModule

		detector = MagicMock()
		with patch.object(pluginModule, "bleDetector", detector):
			self._plugin()

		detector.resume.assert_called_once_with()
