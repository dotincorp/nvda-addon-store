# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2026 Dot Incorporated

from collections.abc import Callable, Iterable
from threading import Event
from typing import Any, cast

from bdDetect import DeviceMatch, DriverRegistrar, ProtocolType
from logHandler import log

from . import BLE_AVAILABLE

if not BLE_AVAILABLE:
	raise ImportError("BLE dependencies not available for this platform")

from bleak import BLEDevice

from .scanner import Scanner, createScanner, stopScanner

#: Protocol type for BLE devices. ``bdDetect.ProtocolType`` is a ``StrEnum`` with no BLE
#: member, so this smuggles a custom value through ``DeviceMatch.type``. Equality still
#: works at runtime because ``StrEnum`` members compare by string value, and declaring the
#: type here keeps comparisons against it type-checking at the call sites.
KEY_BLE: ProtocolType = cast(ProtocolType, "BLE")

MatcherT = Callable[[BLEDevice], bool]

#: How long ``matches()`` will wait for a matching device to advertise before giving up.
#: BLE advertising intervals are typically well under this, so a present device is
#: normally reported far sooner; this is only the ceiling for "nothing is out there".
DISCOVERY_TIMEOUT_SECONDS: float = 0.5


def _bleDeviceInfo(peripheral: BLEDevice) -> dict[str, str]:
	"""Build the ``DeviceMatch.deviceInfo`` payload for a discovered peripheral.

	``provider`` is what makes NVDA keep a USB-only detector running for this driver
	after connecting, so it can switch to USB later ("USB devices have priority over
	Bluetooth" in ``braille``). Without it the match looks wired, NVDA calls
	``_disableDetection()``, and plugging in USB while connected over BLE goes
	unnoticed -- which matters because the display accepts a BLE connection while USB
	is plugged in but outputs nothing over it.

	Deliberately ``"bluetooth"`` rather than ``"ble"``: released NVDA compares against
	``CommunicationType``, which gains a ``BLE`` member only with nvaccess/nvda#19122,
	so ``"ble"`` fails the test on 2026.1 and 2026.2. That PR widens the check to accept
	both, so this keeps working there too.

	Only ``deviceInfo`` carries this. ``DeviceMatch.type`` stays :data:`KEY_BLE`, since
	it identifies saved ports as ``f"{match.type}_{match.id}"`` in the user's
	configuration and selects the transport in the driver.

	The cast mirrors :data:`KEY_BLE`: bdDetect types this as ``dict[str, str]``, but the
	live ``BLEDevice`` has to reach the driver somehow.
	"""
	return cast(
		"dict[str, str]",
		{"peripheral": peripheral, "provider": "bluetooth"},
	)


class Detector:
	"""
	The `Detector` class is responsible for detecting Bluetooth Low Energy (BLE)
	devices and matching them to registered drivers.

	The class maintains a set of matchers, which are functions that take a BLE peripheral
	and return a boolean indicating whether the peripheral matches the driver.
	The `addMatcher` and `removeMatcher` methods allow adding and removing matchers.

	The `matches` method scans for BLE devices and yields a tuple of the driver name
	and a `DeviceMatch` object for each device that matches a registered matcher.
	The `matches` method can be limited to specific drivers using the `limitToDevices` parameter.

	The `register` method adds the `matches` method as a scanner in NVDA's bdDetect
	framework, allowing the autodetection of BLE braille display devices.
	"""

	_scanner: Scanner | None
	_matchers: set[tuple[str, MatcherT]]
	_isRegistered: bool
	_isTerminated: bool

	def __init__(self):
		self._isRegistered = False
		self._isTerminated = False
		self._matchers = set()
		# The scanner is resolved lazily, not here. Constructing this class must not
		# schedule coroutines (addon/ble/asyncUtils picks a loop on first use, and the
		# addon is imported before NVDA starts one), and on NVDA 2026.3+ core's shared
		# scanner does not exist until hwIo is initialised. Scanning therefore starts
		# on demand in matches().
		self._scanner = None

	def _getScanner(self) -> Scanner:
		"""Resolve the scanner on first use and remember it."""
		if self._scanner is None:
			self._scanner = createScanner()
		return self._scanner

	def addMatcher(self, driver: str, func: MatcherT):
		"""
		Adds a new matcher function for the specified driver.

		The matcher function will be called during the BLE device scanning
		process to determine if a scanned device matches the driver.

		Parameters:
		- `driver`: The name of the driver that the matcher function is being registered for.
		- `func`: The matcher function that will be called to determine if a scanned
		  device matches the driver. The function should take a `BLEDevice` object
		  as input and return `True` if the device matches the driver, `False` otherwise.
		"""
		self._matchers.add((driver, func))

	def removeMatcher(self, driver: str, func: MatcherT):
		"""
		Removes a matcher function for the specified driver from the list of matchers.

		Parameters:
		- `driver`: The name of the driver to remove the matcher for.
		- `func`: The matcher function to remove.
		"""
		self._matchers.remove((driver, func))

	def _matchersInScope(
		self,
		limitToDevices: list[str] | None,
	) -> Iterable[tuple[str, MatcherT]]:
		"""Yield the registered matchers that ``limitToDevices`` allows."""
		for driverName, matcher in self._matchers:
			if limitToDevices and driverName not in limitToDevices:
				continue
			yield driverName, matcher

	def _hasMatch(self, peripheral: BLEDevice, limitToDevices: list[str] | None) -> bool:
		return any(matcher(peripheral) for _driverName, matcher in self._matchersInScope(limitToDevices))

	def _waitForMatchingDevice(self, scanner: Scanner, limitToDevices: list[str] | None) -> None:
		"""Block until a device we care about advertises, or the timeout expires.

		A freshly started scan has no results yet, so ``matches()`` used to sleep for a
		fixed interval before reading them -- a delay every caller paid in full, including
		the braille display list in NVDA's settings. Waiting on the scanner's
		``deviceDiscovered`` action instead returns as soon as a matching device is seen,
		and only falls back to the full timeout when there is nothing to find.
		"""
		found = Event()

		def onDeviceDiscovered(device: BLEDevice, **_kwargs: Any) -> None:
			if self._hasMatch(device, limitToDevices):
				found.set()

		# extensionPoints holds handlers weakly, so onDeviceDiscovered must stay
		# referenced for as long as it is registered -- the local name does that.
		scanner.deviceDiscovered.register(onDeviceDiscovered)
		try:
			# A previous scan may already have seen the device, in which case don't wait.
			if any(self._hasMatch(peripheral, limitToDevices) for peripheral in scanner.results()):
				return
			found.wait(DISCOVERY_TIMEOUT_SECONDS)
		finally:
			scanner.deviceDiscovered.unregister(onDeviceDiscovered)

	def terminate(self):
		"""Stop scanning and refuse to scan again until :meth:`resume`.

		Called from ``DotPadGlobalPlugin.terminate()``, which NVDA runs in
		``core._handleNVDAModuleCleanupBeforeGUIExit()`` -- while the asyncio event loop
		the stop needs is still alive, and before ``_terminate(_asyncioEventLoop)``
		closes it out from under the WinRT advertisement watcher.

		The latch matters because that is not the last chance for a scan to start.
		bdDetect keeps polling until ``_terminate(braille)``, several teardown steps
		later, and closing NVDA's windows in between produces the app switches that
		``post_appSwitch -> pollBluetoothDevices`` turns into another background scan.
		Without the latch that scan would re-enter :meth:`matches` and start the watcher
		back up, putting us right back where we started.
		"""
		if self._isTerminated:
			return
		log.debug("dotPad: terminating BLE detection")
		self._isTerminated = True
		if self._scanner is not None:
			stopScanner(self._scanner, wait=True)
			# Kept, not dropped: matches() may be starting a scan on bdDetect's thread
			# right now, and its own post-start latch check needs something to stop.
			# resume() clears it instead.

	def resume(self):
		"""Undo :meth:`terminate`, so a reloaded global plugin detects again.

		``terminate()`` also runs when global plugins are reloaded -- NVDA+Ctrl+F3, or
		Tools -> Reload plugins -- which re-imports ``globalPlugins.*`` but not this
		module, so the singleton below survives. A latch that only ever set would
		therefore kill BLE detection for the rest of the NVDA session. A new
		``DotPadGlobalPlugin`` means we are running again, so it clears the latch; at a
		real shutdown no new plugin is constructed and the latch holds.
		"""
		# Re-resolved on next use, since NVDA may have torn the old one down meanwhile.
		# Deferred to here rather than terminate(), which has a racing scan to stop.
		self._scanner = None
		self._isTerminated = False

	def matches(
		self,
		_usb: bool = False,
		bluetooth: bool = True,
		limitToDevices: list[str] | None = None,
	) -> Iterable[tuple[str, DeviceMatch]]:
		if self._isTerminated:
			# NVDA is shutting down (or plugins are reloading). Starting a scan now
			# would outlive the event loop it depends on. See terminate().
			return
		if not bluetooth:
			# Yield nothing: the caller has asked not to be given Bluetooth devices.
			#
			# This path is how NVDA looks for a USB display while one is already
			# connected over Bluetooth, so that it can switch. Reporting the connected
			# BLE device here made NVDA reconnect to it, which triggered another such
			# scan, which reported it again -- a reconnect every few seconds for as long
			# as the display stayed on, with the driver never living long enough for the
			# TactileDisplayAPI library to finish starting.
			#
			# Stop scanning while we are at it: nobody wants results right now, and the
			# next Bluetooth scan restarts it.
			if self._scanner is not None:
				stopScanner(self._scanner)
			return
		scanner = self._getScanner()
		if not scanner.isScanning:
			scanner.start()
			if self._isTerminated:
				# terminate() ran on NVDA's main thread while we were getting here, so
				# it either found no scanner or stopped one we have since restarted.
				# Either way this scan is ours to undo, and nothing else will.
				stopScanner(scanner, wait=True)
				return
			self._waitForMatchingDevice(scanner, limitToDevices)
		scanResults = scanner.results()
		for peripheral in scanResults:
			for driverName, matcher in self._matchersInScope(limitToDevices):
				if matcher(peripheral):
					yield (
						driverName,
						DeviceMatch(
							type=KEY_BLE,
							id=peripheral.name or peripheral.address,
							port=peripheral.address,
							deviceInfo=_bleDeviceInfo(peripheral),
						),
					)

	def register(self, driverRegistrar: DriverRegistrar):
		if self._isRegistered:
			return
		driverRegistrar.addDeviceScanner(self.matches)
		self._isRegistered = True


#: Singleton instance of the `Detector` class, which is responsible for detecting
#: BLE devices and matching them to registered drivers.
#:
#: Deliberately no ``atexit`` teardown for this: by the time ``atexit`` handlers run
#: the event loop a scan needs is always gone, so such a handler can never stop
#: anything -- it can only raise. On NVDA 2026.2 core closes its loop in
#: ``_terminate(_asyncioEventLoop)``, which precedes every ``atexit`` handler. On
#: 2026.1 the bundled backport registers its own ``terminate`` on first use, i.e.
#: after this module was imported, and ``atexit`` runs LIFO -- so the loop dies first
#: there too. ``DotPadGlobalPlugin.terminate()`` is the hook that runs in time.
detector = Detector()
