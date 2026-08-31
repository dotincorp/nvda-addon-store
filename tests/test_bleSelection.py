# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for choosing between NVDA's hwIo.ble and the addon's own BLE code.

NVDA 2026.3 provides ``hwIo.ble``; 2026.1 and 2026.2 do not. The factories in
``addon.ble.scanner`` and ``addon.ble.hwIo`` pick per version, and ownership of the
scanner's lifecycle follows that choice: core owns its shared singleton via
``hwIo.initialize()``/``terminate()``, so the addon must not stop it.

The 2026.3 path cannot be exercised on hardware yet, which is precisely why the
selection logic is pinned down here.
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from addon.ble import detection
from addon.ble import hwIo as bleHwIo
from addon.ble import scanner as bleScanner
from addon.ble.detection import Detector


class TestScannerSelection(unittest.TestCase):
	def test_uses_core_shared_scanner_when_available(self) -> None:
		coreScanner = MagicMock(name="hwIo.ble.scanner")
		coreModule = MagicMock(name="hwIo.ble", scanner=coreScanner)
		with patch.object(bleScanner, "coreBle", coreModule):
			self.assertIs(bleScanner.createScanner(), coreScanner)

	def test_builds_own_scanner_without_core(self) -> None:
		with (
			patch.object(bleScanner, "coreBle", None),
			patch.object(bleScanner, "Scanner") as scannerCls,
		):
			self.assertIs(bleScanner.createScanner(), scannerCls.return_value)

	def test_raises_when_core_scanner_not_initialised_yet(self) -> None:
		"""hwIo.ble.scanner is None until NVDA initialises hwIo."""
		coreModule = MagicMock(name="hwIo.ble", scanner=None)
		with patch.object(bleScanner, "coreBle", coreModule), self.assertRaises(RuntimeError):
			bleScanner.createScanner()


class TestStopScanner(unittest.TestCase):
	"""Ownership of the scanner's lifecycle follows which implementation supplied it."""

	def test_leaves_core_shared_scanner_running(self) -> None:
		"""hwIo owns core's singleton, and core itself leaves it scanning."""
		scanner = MagicMock(isScanning=True)
		with patch.object(bleScanner, "coreBle", MagicMock(name="hwIo.ble")):
			bleScanner.stopScanner(scanner)

		scanner.stop.assert_not_called()

	def test_stops_own_scanner(self) -> None:
		scanner = MagicMock(isScanning=True)
		with patch.object(bleScanner, "coreBle", None):
			bleScanner.stopScanner(scanner)

		scanner.stop.assert_called_once_with(wait=False)

	def test_does_not_stop_an_idle_scanner(self) -> None:
		scanner = MagicMock(isScanning=False)
		with patch.object(bleScanner, "coreBle", None):
			bleScanner.stopScanner(scanner)

		scanner.stop.assert_not_called()


class TestBleSelection(unittest.TestCase):
	_ARGS = ("device", "writeSvc", "writeChar", "readSvc", "readChar")

	def test_uses_core_ble_when_available(self) -> None:
		coreModule = MagicMock(name="hwIo.ble")
		onReceive = MagicMock()
		with patch.object(bleHwIo, "coreBle", coreModule):
			result = bleHwIo.createBle(*self._ARGS, onReceive)  # type: ignore[arg-type]

		coreModule.Ble.assert_called_once_with(*self._ARGS, onReceive)
		self.assertIs(result, coreModule.Ble.return_value)

	def test_uses_own_ble_without_core(self) -> None:
		onReceive = MagicMock()
		with patch.object(bleHwIo, "coreBle", None), patch.object(bleHwIo, "Ble") as bleCls:
			result = bleHwIo.createBle(*self._ARGS, onReceive)  # type: ignore[arg-type]

		bleCls.assert_called_once_with(*self._ARGS, onReceive)
		self.assertIs(result, bleCls.return_value)


class TestDetectorScannerLifecycle(unittest.TestCase):
	def test_scanner_is_not_resolved_at_construction(self) -> None:
		"""Constructing Detector must not touch the scanner or the event loop."""
		with patch.object(bleScanner, "createScanner") as createScanner:
			Detector()

		createScanner.assert_not_called()

	def test_terminate_delegates_to_stopScanner(self) -> None:
		detector = Detector()
		scanner = MagicMock(isScanning=True)
		detector._scanner = scanner
		with patch("addon.ble.detection.stopScanner") as stopScanner:
			detector.terminate()

		stopScanner.assert_called_once_with(scanner, wait=True)

	def test_terminate_is_safe_before_any_scan(self) -> None:
		"""No scanner was ever resolved, so there is nothing to stop."""
		detector = Detector()
		with patch("addon.ble.detection.stopScanner") as stopScanner:
			detector.terminate()  # must not raise

		stopScanner.assert_not_called()


class TestDiscoveryWait(unittest.TestCase):
	"""matches() waits on the scanner's deviceDiscovered action, not a fixed sleep."""

	def _detectorWithMatcher(self, matches: bool = True) -> Detector:
		detector = Detector()
		detector.addMatcher("dotPad", lambda device: matches)
		return detector

	def _scanner(self, results: list[object] | None = None) -> MagicMock:
		"""A scanner whose deviceDiscovered action records the registered handler."""
		scanner = MagicMock(isScanning=False)
		scanner.results.return_value = results or []
		scanner.deviceDiscovered.register.side_effect = lambda h: handlers.append(h)
		handlers: list[object] = []
		scanner.handlers = handlers
		return scanner

	def test_returns_immediately_when_device_already_seen(self) -> None:
		"""A device from an earlier scan means there is nothing to wait for."""
		detector = self._detectorWithMatcher()
		scanner = self._scanner(results=[MagicMock(name="dotpad")])

		start = time.monotonic()
		detector._waitForMatchingDevice(scanner, None)
		elapsed = time.monotonic() - start

		self.assertLess(elapsed, detection.DISCOVERY_TIMEOUT_SECONDS / 2)
		scanner.deviceDiscovered.unregister.assert_called_once()

	def test_returns_as_soon_as_a_matching_device_advertises(self) -> None:
		detector = self._detectorWithMatcher()
		scanner = self._scanner()

		def advertise() -> None:
			# Fire the action the way the scanner would, from another thread.
			for handler in scanner.handlers:
				handler(device=MagicMock(name="dotpad"), advertisementData=None, isNew=True)

		threading.Timer(0.02, advertise).start()
		start = time.monotonic()
		detector._waitForMatchingDevice(scanner, None)
		elapsed = time.monotonic() - start

		self.assertLess(elapsed, detection.DISCOVERY_TIMEOUT_SECONDS / 2)

	def test_waits_out_the_timeout_when_nothing_matches(self) -> None:
		detector = self._detectorWithMatcher(matches=False)
		scanner = self._scanner()

		start = time.monotonic()
		detector._waitForMatchingDevice(scanner, None)
		elapsed = time.monotonic() - start

		self.assertGreaterEqual(elapsed, detection.DISCOVERY_TIMEOUT_SECONDS * 0.8)

	def test_handler_is_always_unregistered(self) -> None:
		"""Handlers are held weakly, but leaving them registered would still leak matches."""
		detector = self._detectorWithMatcher()
		scanner = self._scanner(results=[MagicMock()])
		detector._waitForMatchingDevice(scanner, None)

		scanner.deviceDiscovered.unregister.assert_called_once_with(
			scanner.deviceDiscovered.register.call_args.args[0],
		)

	def test_limitToDevices_excludes_other_drivers(self) -> None:
		detector = self._detectorWithMatcher()
		scanner = self._scanner(results=[MagicMock()])

		start = time.monotonic()
		detector._waitForMatchingDevice(scanner, ["someOtherDriver"])
		elapsed = time.monotonic() - start

		# Our only matcher is out of scope, so the existing result must not count.
		self.assertGreaterEqual(elapsed, detection.DISCOVERY_TIMEOUT_SECONDS * 0.8)


class TestScannerDeviceDiscovered(unittest.TestCase):
	"""The backported extension point is wired to the real Scanner, not just mocked."""

	def _scanner(self) -> object:
		with patch.object(bleScanner.bleak, "BleakScanner"):
			return bleScanner.Scanner()

	def test_notifies_handlers_on_advertisement(self) -> None:
		scanner = self._scanner()
		seen: list[tuple[object, bool]] = []

		def onDeviceDiscovered(device, advertisementData, isNew):
			seen.append((device, isNew))

		scanner.deviceDiscovered.register(onDeviceDiscovered)
		try:
			device = MagicMock(address="AA:BB:CC:DD:EE:FF", name="DotPad320")
			scanner._onDeviceAdvertised(device, MagicMock())
			scanner._onDeviceAdvertised(device, MagicMock())
		finally:
			scanner.deviceDiscovered.unregister(onDeviceDiscovered)

		self.assertEqual(2, len(seen), "every advertisement notifies, not only new devices")
		self.assertTrue(seen[0][1], "first sighting is new")
		self.assertFalse(seen[1][1], "re-advertisement is not new")
		self.assertEqual([device], scanner.results())


class TestDeviceMatchProvider(unittest.TestCase):
	"""The match must look like Bluetooth to NVDA, or auto-detection is switched off.

	NVDA only keeps a USB-only detector running for the current driver when the
	connected match reports Bluetooth; otherwise it calls _disableDetection(), and
	plugging in USB while connected over BLE is never noticed.
	"""

	def _match(self):
		detector = Detector()
		detector.addMatcher("dotPad", lambda device: True)
		scanner = MagicMock(isScanning=True)
		device = MagicMock(address="AA:BB:CC:DD:EE:FF")
		device.name = "DotPad320"
		scanner.results.return_value = [device]
		detector._scanner = scanner
		((_driverName, match),) = list(detector.matches())
		return match

	def test_reports_a_bluetooth_provider(self) -> None:
		# "bluetooth", not "ble": released NVDA compares against CommunicationType,
		# which has no BLE member until nvaccess/nvda#19122 lands.
		self.assertEqual("bluetooth", self._match().deviceInfo["provider"])

	def test_still_carries_the_peripheral(self) -> None:
		"""The driver opens the connection from this, so it must survive."""
		self.assertIn("peripheral", self._match().deviceInfo)

	def test_type_is_unchanged(self) -> None:
		"""type identifies saved ports and selects the transport -- it must not move."""
		match = self._match()
		self.assertEqual(detection.KEY_BLE, match.type)
		# The port identifier the driver persists and parses back.
		self.assertEqual("BLE_DotPad320", f"{match.type}_{match.id}")


class TestBluetoothFlagIsHonoured(unittest.TestCase):
	"""matches(bluetooth=False) must yield nothing.

	NVDA uses that scan to look for a USB display while one is already connected over
	Bluetooth. Reporting the connected BLE device there made NVDA reconnect to it,
	which triggered another such scan, which reported it again -- an endless reconnect
	loop in which the driver never lived long enough for the library to start.
	"""

	def _detectorWithResults(self) -> Detector:
		detector = Detector()
		detector.addMatcher("dotPad", lambda device: True)
		scanner = MagicMock(isScanning=True)
		device = MagicMock(address="AA:BB:CC:DD:EE:FF")
		device.name = "DotPad320"
		scanner.results.return_value = [device]
		detector._scanner = scanner
		return detector

	def test_yields_nothing_when_bluetooth_is_not_wanted(self) -> None:
		detector = self._detectorWithResults()

		self.assertEqual([], list(detector.matches(bluetooth=False)))

	def test_still_yields_when_bluetooth_is_wanted(self) -> None:
		detector = self._detectorWithResults()

		self.assertEqual(1, len(list(detector.matches(bluetooth=True))))

	def test_stops_scanning_when_bluetooth_is_not_wanted(self) -> None:
		detector = self._detectorWithResults()
		with patch("addon.ble.detection.stopScanner") as stopScanner:
			list(detector.matches(bluetooth=False))

		stopScanner.assert_called_once_with(detector._scanner)

	def test_is_safe_before_a_scanner_exists(self) -> None:
		detector = Detector()

		self.assertEqual([], list(detector.matches(bluetooth=False)))
