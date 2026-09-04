# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2026 Dot Incorporated

import time
from collections.abc import Callable
from threading import Event
from typing import cast

import extensionPoints
from logHandler import log

from . import BLE_AVAILABLE, coreBle

if not BLE_AVAILABLE:
	raise ImportError("BLE dependencies not available for this platform")

import bleak

from .asyncUtils import runCoroutine, runCoroutineSync

#: How long a blocking :meth:`Scanner.stop` waits for bleak to stop the WinRT watcher.
#: Only the shutdown path blocks, and it does so on NVDA's main thread, so this bounds
#: how long a wedged Bluetooth stack can delay NVDA's exit.
STOP_TIMEOUT_SECONDS: float = 2.0


class Scanner:
	"""Scan for BLE devices"""

	_scanner: bleak.BleakScanner
	_discoveredDevices: dict[str, bleak.BLEDevice]
	_isScanning: Event

	def __init__(self):
		self._discoveredDevices = {}
		self._scanner = bleak.BleakScanner(self._onDeviceAdvertised)
		self._isScanning = Event()
		#: Action called when a BLE device is discovered or re-advertises.
		#: Handlers receive: device (BLEDevice), advertisementData (AdvertisementData), isNew (bool)
		#: Mirrors hwIo.ble.Scanner.deviceDiscovered so callers work against either scanner.
		self.deviceDiscovered = extensionPoints.Action()

	def _onDeviceAdvertised(self, device: bleak.BLEDevice, adv: bleak.AdvertisementData) -> None:
		# Check whether this is a new device before updating the dict.
		isNew = device.address not in self._discoveredDevices
		# Unnamed devices are kept, matching hwIo.ble.Scanner: they can still be
		# resolved by address, and the driver's own matcher is the real filter.
		self._discoveredDevices[device.address] = device
		self.deviceDiscovered.notify(device=device, advertisementData=adv, isNew=isNew)
		if isNew:
			log.debug("Discovered BLE device: %s", device.name or device.address)

	def start(self, duration: float = 0):
		"""Start scanning for devices for the given duration in seconds.

		If no duration is given, this will scan in the background until stopped.
		Seconds rather than milliseconds to match ``hwIo.ble.Scanner.start``.
		"""
		log.debug("Scanning for devices")
		# Clear the cache only on the first start, so multiple callers share results.
		if not self._isScanning.is_set():
			self._discoveredDevices.clear()
		self._isScanning.set()
		runCoroutine(self._scanner.start())
		if duration > 0:
			time.sleep(duration)
			self.stop()

	def stop(self, wait: bool = False):
		"""Stop scanning.

		:param wait: Block until bleak has stopped the WinRT watcher and removed its
			advertisement handlers, rather than only scheduling that work.

		``wait`` matters at NVDA shutdown and nowhere else. The watcher delivers
		advertisements on WinRT thread-pool threads and its handler does
		``call_soon_threadsafe`` on the event loop, so a watcher outliving the loop
		raises ``RuntimeError: Event loop is closed`` for every advertisement in radio
		range. Scheduling the stop is not enough there -- NVDA closes the loop shortly
		after, and the stop needs that same loop to run on.

		The default stays fire-and-forget because the other caller is bdDetect's
		background scan during normal operation, which should not pay a round trip to
		the loop thread just to switch scanning off.
		"""
		# Built before scheduling so a dead loop can be handled without discarding an
		# un-awaited coroutine, which is its own warning in the log.
		coro = self._scanner.stop()
		try:
			if wait:
				runCoroutineSync(coro, STOP_TIMEOUT_SECONDS)
			else:
				runCoroutine(coro)
		except Exception:
			try:
				coro.close()
			except Exception:
				# A timed-out wait leaves it running on the loop thread, where closing
				# it is both impossible and no longer our problem.
				pass
			log.exception("Failed to stop the BLE scan")
		finally:
			# Cleared even on failure: leaving it set would make matches() believe a
			# scan is still running and never start another one.
			self._isScanning.clear()

	def results(self, filterFunc: Callable[[bleak.BLEDevice], bool] | None = None) -> list[bleak.BLEDevice]:
		"""
		Get the results of the BLE scan.

		Args:
		    filterFunc (Callable[[simplepyble.Peripheral], bool] | None): An optional
		        function to filter the scan results. If provided, only peripherals
		        for which the function returns True will be included in the results.

		Returns:
		    list[bleak.BleaDevice]: The list of BLE peripherals found during
		        the scan, optionally filtered by the provided function.
		"""
		results: list[bleak.BLEDevice] = list(self._discoveredDevices.values())
		if filterFunc:
			results = [p for p in results if filterFunc(p)]
		return results

	@property
	def isScanning(self) -> bool:
		"""Check if scanning is currently active"""
		return self._isScanning.is_set()


def createScanner() -> Scanner:
	"""Return the scanner to use on this NVDA version.

	On NVDA 2026.3+ this is core's shared singleton, so the addon does not contend
	with other drivers over the Windows BLE stack -- and must not start or stop it,
	since ``hwIo.initialize()``/``terminate()`` own its lifecycle. Otherwise it is a
	locally-owned instance.

	Must be called lazily: core's singleton is ``None`` until NVDA initialises hwIo,
	which happens after addons are imported.
	"""
	if coreBle is not None:
		if coreBle.scanner is None:
			raise RuntimeError("hwIo.ble is not initialised yet")
		# Structurally identical API: start/stop/results/isScanning.
		return cast(Scanner, coreBle.scanner)
	return Scanner()


def stopScanner(scanner: Scanner, wait: bool = False) -> None:
	"""Stop ``scanner``, unless it is core's shared singleton.

	On NVDA 2026.3+ ``hwIo.initialize()`` / ``terminate()`` own that scanner's
	lifecycle and other drivers may be using it, so the addon must leave it running --
	which is also what core itself does in ``hwIo.ble.findDeviceByAddress``. Guarding
	here rather than at the call sites keeps the rule stated once. That also covers
	shutdown: ``hwIo.terminate()`` runs before core closes the event loop, so core's
	scanner is never the one left advertising into a dead loop.

	:param wait: Block until the scan has really stopped. See :meth:`Scanner.stop`.
	"""
	if coreBle is not None:
		return
	if scanner.isScanning:
		scanner.stop(wait=wait)
