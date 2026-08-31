# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2026 Dot Incorporated

import time
from collections.abc import Callable, Iterator
from itertools import count, takewhile
from queue import Empty, Queue
from threading import Event, Thread
from typing import cast

from hwIo.base import _isDebug  # type: ignore
from logHandler import log

from . import BLE_AVAILABLE, coreBle

if not BLE_AVAILABLE:
	raise ImportError("BLE dependencies not available for this platform")

import bleak
from bleak.args.winrt import WinRTClientArgs

from .asyncUtils import runCoroutine, runCoroutineSync

#: Cap on the whole connect + subscribe sequence.
#: Windows' own GATT connect attempt against an unreachable peripheral runs for roughly
#: 30 seconds, and bleak does not bound it: its ``timeout`` argument only covers
#: ``find_device_by_address`` (skipped when a ``BLEDevice`` is supplied) and service
#: discovery, both of which sit outside the connect itself. NVDA constructs the display
#: on the main thread when one is chosen from the GUI, so an unbounded wait freezes the
#: interface. Cancelling does not abort Windows' attempt, so the client is closed on
#: timeout to release the session.
CONNECT_TIMEOUT_SECONDS: float = 5
#: Budget for releasing a connection attempt that already failed. Deliberately much
#: shorter than the connect itself: ``__init__`` runs on the main thread when a display
#: is chosen from the GUI, and the driver tries each candidate port in turn, so a slow
#: cleanup is paid once per unreachable candidate on top of the connect timeout.
ABANDON_TIMEOUT_SECONDS: float = 1
#: Budget for the receive side to wind down in close(). Both waits below it are
#: courtesies -- inbound data we are about to discard, and a daemon thread that exits on
#: its own -- so neither is worth holding NVDA's main thread for.
CLOSE_TIMEOUT_SECONDS: float = 1
#: How long to wait for services to be discovered once connected.
SERVICE_DISCOVERY_TIMEOUT_SECONDS: int = 2
WINRT_CLIENT_PARAMS = WinRTClientArgs(use_cached_services=True)


def queueReader(queue: Queue[bytes], onReceive: Callable[[bytes], None], stopEvent: Event) -> None:
	while True:
		try:
			if stopEvent.is_set():
				log.debug("Reader thread got stop event")
				break
			try:
				data: bytes = queue.get(timeout=0.5)
			except Empty:
				continue

			onReceive(data)
			queue.task_done()
		except Exception:
			log.error("Reader thread got exception", exc_info=True)


def sliced(data: bytes, n: int) -> Iterator[bytes]:
	"""
	Slices *data* into chunks of size *n*. The last slice may be smaller than
	*n*.
	"""
	return takewhile(len, (data[i : i + n] for i in count(0, n)))


class Ble:
	"""I/O for Bluetooth Low Energy (BLE) devices

	This implementation expects a service/characteristic pair to send raw data to as a BLE command
	and receive raw data through a BLE notify on a service/characteristic pair.
	It is compatible with the HwIO interface, but does not inherit from the IO base class,
	since we do not share any of the functionality.

	This uses the SimplePyBLE library, which has a WinRT backend for BLE communication.
	Initializing the WinRT backend on the NVDA main thread clashes with the WX event loop,
	so we take great care to run every SimpleBLE method that might
	initialize the WinRT API on a separate thread.
	"""

	_client: bleak.BleakClient
	"The Bleak client to use for BLE communication"
	_writeServiceUuid: str
	"The service UUID to use for writing data to the peripheral, this should accept BLE commands"
	_writeCharacteristicUuid: str
	"The characteristic UUID to use for writing data to the peripheral, this should accept BLE commands"
	_readServiceUuid: str
	"The service UUID to use for reading data from the peripheral, this should accept BLE notifications"
	_readCharacteristicUuid: str
	"""The characteristic UUID to use for reading data from the peripheral,
    this should accept BLE notifications"""
	_onReceive: Callable[[bytes], None] | None
	"The callback to call when data is received"
	_queuedData: Queue[bytes | bytearray]
	"A queue of received data, this is processsed by the onReceive handler"
	_readEvent: Event
	"An event that is set when data is received"
	_readerThread: Thread
	"Thread that processes the queue of rad data"
	_stopReaderEvent: Event
	"Event that is set to stop the reader thread"

	def __init__(
		self,
		device: bleak.BLEDevice,
		writeServiceUuid: str,
		writeCharacteristicUuid: str,
		readServiceUuid: str,
		readCharacteristicUuid: str,
		onReceive: Callable[[bytes], None],
	) -> None:
		log.info(f"Connecting to {device.name} ({device.address})")
		self._client = bleak.BleakClient(device, winrt=WINRT_CLIENT_PARAMS)
		self._writeServiceUuid = writeServiceUuid
		self._writeCharacteristicUuid = writeCharacteristicUuid
		self._readServiceUuid = readServiceUuid
		self._readCharacteristicUuid = readCharacteristicUuid
		self._onReceive = onReceive
		self._queuedData = Queue()
		self._readEvent = Event()
		self._stopReaderEvent = Event()
		self._readerThread = Thread(
			target=queueReader,
			args=(self._queuedData, self._onReceive, self._stopReaderEvent),
			daemon=True,
		)
		self._readerThread.start()
		try:
			runCoroutineSync(self._initAndConnect(), timeout=CONNECT_TIMEOUT_SECONDS)
		except TimeoutError:
			self._abandonConnection()
			raise RuntimeError(
				f"Timed out connecting to {device.address} after {CONNECT_TIMEOUT_SECONDS}s",
			) from None
		try:
			self.waitForConnection(SERVICE_DISCOVERY_TIMEOUT_SECONDS)
		except Exception:
			# Connected but no services: without this the reader thread and the GATT
			# session would outlive the failed attempt and could block the next one.
			self._abandonConnection()
			raise

	def _abandonConnection(self) -> None:
		"""Release a connection attempt that timed out.

		The cancelled coroutine does not stop Windows from continuing to try, so the
		client is disconnected explicitly; otherwise the GATT session can linger and
		block the next attempt. The reader thread is stopped too, since no caller will
		receive this instance.
		"""
		self._stopReaderEvent.set()
		try:
			runCoroutineSync(self._client.disconnect(), timeout=ABANDON_TIMEOUT_SECONDS)
		except Exception:
			log.debugWarning("Failed to release a timed-out BLE connection", exc_info=True)

	async def _initAndConnect(self) -> None:
		await self._client.connect()
		# Listen for notifications
		await self._client.start_notify(self._readCharacteristicUuid, self._notifyReceive)

	def waitForRead(self, timeout: float) -> bool:
		"""
		Waits for data to be received from the peripheral.
		"""
		self._readEvent.clear()
		return self._readEvent.wait(timeout)

	def write(self, data: bytes):
		"""
		Writes data to the connected peripheral. This method handles the data transmission by
		splitting it into multiple writes if the data length exceeds the peripheral's Maximum
		Transmission Unit (MTU).

		:param data: The data to be written to the peripheral.
		:type data: bytes

		:raises TypeError: If the `data` argument is not of type `bytes`.
		:raises RuntimeError: If the peripheral is not connected or the write service UUID
		                      is not found in the peripheral's offered services.
		"""
		if not self._client.is_connected:
			raise RuntimeError("Not connected to peripheral")
		service = self._client.services.get_service(self._writeServiceUuid)
		if not service:
			raise RuntimeError(f"Service {self._writeServiceUuid} not found")
		characteristic = service.get_characteristic(self._writeCharacteristicUuid)
		if not characteristic:
			raise RuntimeError(f"Characteristic {self._writeCharacteristicUuid} not found")
		if _isDebug():
			log.debug(f"Write: {data!r}")

		# Split the data into chunks that fit within the MTU. All chunks are awaited
		# inside one coroutine: a runCoroutineSync per chunk meant a separate
		# cross-thread hand-off to the event loop for each one.
		chunks = list(sliced(data, characteristic.max_write_without_response_size))
		runCoroutineSync(self._writeChunks(characteristic, chunks))

	async def _writeChunks(self, characteristic: object, chunks: list[bytes]) -> None:
		"""Write pre-split chunks to the peripheral in order."""
		for chunk in chunks:
			await self._client.write_gatt_char(characteristic, chunk, response=False)  # type: ignore[arg-type]

	def close(self) -> None:
		"""
		Disconnects the BLE peripheral and closes the receive event handle.

		This method is responsible for gracefully
		closing the connection to the BLE peripheral
		and releasing any associated resources.
		It is typically called when the BLE connection is no longer needed,
		such as when the application is shutting down or the connection is lost.
		"""
		if _isDebug():
			log.debug("Closing BLE connection")
		if self._client.is_connected:
			# Scheduled, not waited on. Cancelling a disconnect would not stop the
			# WinRT operation already in flight, and this object is about to be
			# dropped -- so a timeout here could leave the peripheral connected with
			# nothing left able to close it. Handing the coroutine to the event loop
			# instead keeps the disconnect going: the loop is process-wide and the
			# coroutine holds the only reference it needs. close() is called from
			# terminate(), which runs on NVDA's main thread, so waiting is what we
			# cannot afford -- not the disconnect itself.
			runCoroutine(self._client.disconnect())
		# Inbound data we are about to discard. Bounded because the reader dispatches
		# it through the driver, which can be holding _ackLock while a sender that
		# terminate() has stopped waiting for still owns it.
		if not self._drainReceivedData(CLOSE_TIMEOUT_SECONDS):
			log.debugWarning(f"Received data not dispatched within {CLOSE_TIMEOUT_SECONDS}s; closing anyway")
		self._stopReaderEvent.set()
		# The reader polls with its own timeout and is a daemon, so at worst it
		# outlives this call briefly and dies with the process.
		self._readerThread.join(CLOSE_TIMEOUT_SECONDS)
		if self._readerThread.is_alive():
			log.debugWarning(f"Reader thread did not exit within {CLOSE_TIMEOUT_SECONDS}s; closing anyway")

		self._onReceive = None

	def _drainReceivedData(self, timeout: float) -> bool:
		"""``Queue.join()`` with a deadline. Returns ``False`` if it expired."""
		deadline = time.monotonic() + timeout
		with self._queuedData.all_tasks_done:
			while self._queuedData.unfinished_tasks:
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					return False
				self._queuedData.all_tasks_done.wait(remaining)
		return True

	def __del__(self):
		"""
		Ensures the BLE connection is closed before the object is destroyed.

		A last-resort backstop for an instance dropped without ``close()``. Any failure
		is swallowed rather than only ``AttributeError``: this runs at arbitrary times,
		including interpreter shutdown when the event loop the disconnect needs may
		already be gone, and an exception here is unignorable noise in the log rather
		than something a caller can act on.
		"""
		try:
			self.close()
		except Exception:
			if _isDebug():
				log.debugWarning("Couldn't delete object gracefully", exc_info=True)

	def isConnected(self) -> bool:
		"""
		Returns whether the BLE peripheral is currently connected.

		Returns:
		    bool: True if the BLE peripheral is connected, False otherwise.
		"""
		return self._client.is_connected

	def waitForConnection(self, max_wait: float):
		"""
		Waits for a connection to be established and the services to be discovered, up to a maximum wait time.

		Args:
		    max_wait (int): The maximum time to wait for the connection, in seconds.

		Raises:
		    RuntimeError: If the connection is not established within the maximum wait time.
		"""
		num_tries: int = 0
		sleep_time: float = 0.1

		while (sleep_time * num_tries) < max_wait:
			if _isDebug():
				services = [
					(
						s.uuid,
						s.description,
					)
					for s in self._client.services.services.values()
				]
				log.debug(
					f"Waiting for connection, {num_tries} tries, "
					f"is connected {self.isConnected()}, services {services}",
				)
			if self._client.is_connected and len(self._client.services.services) > 0:
				return
			time.sleep(sleep_time)
			num_tries += 1
		raise RuntimeError("Connection timed out")

	def _notifyReceive(self, _char: bleak.BleakGATTCharacteristic, data: bytearray):
		if _isDebug():
			log.debug(f"Read: {data!r}")
		self._readEvent.set()
		self._queuedData.put(data)

	def read(self, num_bytes: int = 1) -> bytes:
		raise NotImplementedError


def createBle(
	device: "bleak.BLEDevice",
	writeServiceUuid: str,
	writeCharacteristicUuid: str,
	readServiceUuid: str,
	readCharacteristicUuid: str,
	onReceive: Callable[[bytes], None],
) -> "Ble":
	"""Open a BLE connection using core's implementation where available.

	NVDA 2026.3's ``hwIo.ble.Ble`` takes the same arguments and exposes the same
	methods as the local class, with one behavioural difference: it delivers
	``onReceive`` through the shared I/O thread via ``queueAsApc`` rather than a
	dedicated daemon thread. That matches how the driver's serial path already
	receives data, so both transports converge on one delivery model on 2026.3+.
	"""
	implementation = Ble if coreBle is None else coreBle.Ble
	return cast(
		"Ble",
		implementation(
			device,
			writeServiceUuid,
			writeCharacteristicUuid,
			readServiceUuid,
			readCharacteristicUuid,
			onReceive,
		),
	)
