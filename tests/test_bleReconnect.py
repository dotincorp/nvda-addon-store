# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for closing and reopening a BLE link in quick succession.

Every lock and unlock of the workstation makes NVDA terminate the driver and construct a
new one, both on its main thread, so ``close()`` and the connect must not hold it.
"""

from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import Future
from queue import Queue
from unittest.mock import MagicMock, patch

from addon.ble import hwIo as bleHwIo

_MODULE = "addon.ble.hwIo"
ADDRESS = "60:8A:10:57:20:79"


def _makeBle(*, connected: bool = True, address: str = ADDRESS) -> bleHwIo.Ble:
	"""A ``Ble`` with only the state ``close()`` touches."""
	ble = bleHwIo.Ble.__new__(bleHwIo.Ble)
	ble._address = address
	ble._client = MagicMock()
	ble._client.is_connected = connected
	ble._queuedData = Queue()
	ble._stopReaderEvent = threading.Event()
	ble._readerThread = MagicMock()
	ble._readerThread.is_alive.return_value = False
	ble._onReceive = MagicMock()
	return ble


class ReconnectTestCase(unittest.TestCase):
	def setUp(self) -> None:
		bleHwIo._pendingDisconnects.clear()
		self.addCleanup(bleHwIo._pendingDisconnects.clear)


class TestCloseRunsOnce(ReconnectTestCase):
	"""``__del__`` closes again when the instance is collected, long after terminate()."""

	def test_a_second_close_does_nothing(self) -> None:
		ble = _makeBle(connected=True)

		with patch(f"{_MODULE}.runCoroutine") as runCoroutine:
			ble.close()
			ble.close()

		runCoroutine.assert_called_once()
		ble._readerThread.join.assert_called_once()

	def test_an_instance_whose_constructor_failed_can_be_collected(self) -> None:
		"""``__del__`` runs on half-built instances too."""
		ble = bleHwIo.Ble.__new__(bleHwIo.Ble)

		ble.__del__()


class TestCloseDoesNotWaitOutTheReaderPoll(ReconnectTestCase):
	def test_an_idle_reader_exits_at_once(self) -> None:
		"""The join in close() waited for the reader's 0.5s poll, on NVDA's main thread."""
		ble = _makeBle(connected=False)
		ble._readerThread = threading.Thread(
			target=bleHwIo.queueReader,
			args=(ble._queuedData, MagicMock(), ble._stopReaderEvent),
			daemon=True,
		)
		ble._readerThread.start()
		# Let the reader block in its queue wait, which is where it idles.
		time.sleep(0.05)

		start = time.monotonic()
		ble.close()

		self.assertLess(time.monotonic() - start, 0.25)
		self.assertFalse(ble._readerThread.is_alive())

	def test_data_already_received_is_still_dispatched(self) -> None:
		ble = _makeBle(connected=False)
		received: list[bytes] = []
		ble._readerThread = threading.Thread(
			target=bleHwIo.queueReader,
			args=(ble._queuedData, received.append, ble._stopReaderEvent),
			daemon=True,
		)
		ble._queuedData.put(b"late")
		ble._readerThread.start()

		ble.close()

		self.assertEqual([b"late"], received)


class TestReconnectWaitsForThePreviousDisconnect(ReconnectTestCase):
	"""close() schedules the disconnect rather than waiting for it, and NVDA constructs
	the next driver straight away -- so the new connect could race it."""

	def _closeWithDisconnect(self, future: Future[None], address: str = ADDRESS) -> None:
		with patch(f"{_MODULE}.runCoroutine", return_value=future):
			_makeBle(connected=True, address=address).close()

	def test_a_disconnect_in_flight_is_remembered_until_it_completes(self) -> None:
		future: Future[None] = Future()
		self._closeWithDisconnect(future)
		self.assertIs(future, bleHwIo._pendingDisconnects[ADDRESS])

		future.set_result(None)

		self.assertNotIn(ADDRESS, bleHwIo._pendingDisconnects)

	def test_waits_for_a_disconnect_still_in_flight(self) -> None:
		future: Future[None] = Future()
		self._closeWithDisconnect(future)
		threading.Timer(0.05, future.set_result, [None]).start()

		start = time.monotonic()
		bleHwIo._awaitPreviousDisconnect(ADDRESS)

		self.assertTrue(future.done())
		self.assertLess(time.monotonic() - start, 1)

	def test_the_wait_is_bounded(self) -> None:
		"""It runs on NVDA's main thread; a disconnect that never completes must not hold it."""
		future: Future[None] = Future()
		self._closeWithDisconnect(future)

		with patch(f"{_MODULE}.PREVIOUS_DISCONNECT_TIMEOUT_SECONDS", 0.05):
			start = time.monotonic()
			bleHwIo._awaitPreviousDisconnect(ADDRESS)

		self.assertLess(time.monotonic() - start, 0.5)

	def test_a_failed_disconnect_does_not_prevent_connecting(self) -> None:
		future: Future[None] = Future()
		self._closeWithDisconnect(future)
		future.set_exception(OSError("already gone"))

		bleHwIo._awaitPreviousDisconnect(ADDRESS)

	def test_another_device_is_not_delayed(self) -> None:
		self._closeWithDisconnect(Future(), address="00:00:00:00:00:01")

		start = time.monotonic()
		bleHwIo._awaitPreviousDisconnect(ADDRESS)

		self.assertLess(time.monotonic() - start, 0.1)

	def test_the_connect_starts_only_after_the_wait(self) -> None:
		device = MagicMock()
		device.address = ADDRESS
		calls: list[str] = []

		with (
			patch(f"{_MODULE}._awaitPreviousDisconnect", side_effect=lambda _a: calls.append("await")),
			patch(
				f"{_MODULE}.runCoroutineSync",
				side_effect=lambda coro, **_kw: (coro.close(), calls.append("connect")),
			),
			patch(f"{_MODULE}.bleak.BleakClient"),
			patch(f"{_MODULE}.Thread"),
			patch.object(bleHwIo.Ble, "waitForConnection"),
		):
			ble = bleHwIo.Ble(device, "w", "wc", "r", "rc", onReceive=MagicMock())
			ble._closed = True  # nothing real to close when it is collected

		self.assertEqual(["await", "connect"], calls)
