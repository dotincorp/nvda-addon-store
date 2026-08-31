# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for ``Ble.close()`` being bounded without abandoning the disconnect.

``close()`` is called from ``terminate()``'s ``finally``, which runs on NVDA's main
thread, so nothing in it may wait indefinitely. That matters more since the sender
thread's join became bounded: the sender can still hold ``_ackLock`` while the reader
blocks on it dispatching a packet, so waiting on the reader here can deadlock on a
thread we deliberately stopped waiting for.

The disconnect is the exception to "just bound it". Cancelling it would not stop the
WinRT operation already in flight, and this object is about to be dropped, so a timeout
could leave the peripheral connected with nothing able to close it. It is handed to the
event loop instead: bounded waiting, unbounded operation.
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from addon.ble import hwIo as bleHwIo

_MODULE = "addon.ble.hwIo"


class BleCloseTestCase(unittest.TestCase):
	"""Base fixture. ``Ble.__del__`` calls ``close()`` when the object is collected, so
	each instance is left looking disconnected -- otherwise that runs outside the test's
	patches and schedules a disconnect against a mock."""

	def makeBle(self, *, connected: bool = True) -> bleHwIo.Ble:
		"""An ``Ble`` with only the state ``close()`` touches."""
		ble = bleHwIo.Ble.__new__(bleHwIo.Ble)
		ble._client = MagicMock()
		ble._client.is_connected = connected
		ble._queuedData = bleHwIo.Queue()
		ble._stopReaderEvent = threading.Event()
		ble._readerThread = MagicMock()
		ble._readerThread.is_alive.return_value = False
		ble._onReceive = MagicMock()
		self.addCleanup(setattr, ble._client, "is_connected", False)
		return ble


class TestDisconnectIsScheduledNotAbandoned(BleCloseTestCase):
	def test_the_disconnect_is_handed_to_the_event_loop(self) -> None:
		"""The operation must outlive close(), or the device is left open."""
		ble = self.makeBle(connected=True)

		with (
			patch(f"{_MODULE}.runCoroutine") as runCoroutine,
			patch(f"{_MODULE}.runCoroutineSync") as runCoroutineSync,
		):
			ble.close()

		runCoroutine.assert_called_once()
		runCoroutineSync.assert_not_called()

	def test_close_does_not_wait_for_the_disconnect(self) -> None:
		"""Waiting is what close() cannot afford; it runs on NVDA's main thread."""
		ble = self.makeBle(connected=True)

		with patch(f"{_MODULE}.runCoroutine") as runCoroutine:
			ble.close()

		# A future is returned but never waited on.
		runCoroutine.return_value.result.assert_not_called()

	def test_nothing_is_scheduled_when_already_disconnected(self) -> None:
		ble = self.makeBle(connected=False)

		with patch(f"{_MODULE}.runCoroutine") as runCoroutine:
			ble.close()

		runCoroutine.assert_not_called()


class TestCloseIsBounded(BleCloseTestCase):
	def test_returns_even_if_received_data_is_never_dispatched(self) -> None:
		"""The reader can be blocked on _ackLock, held by a sender we stopped joining."""
		ble = self.makeBle()
		ble._queuedData.put(b"never dispatched")  # no task_done() will follow

		with (
			patch(f"{_MODULE}.runCoroutine"),
			patch(f"{_MODULE}.CLOSE_TIMEOUT_SECONDS", 0.05),
		):
			start = time.monotonic()
			ble.close()

		self.assertLess(time.monotonic() - start, 1)

	def test_returns_even_if_the_reader_thread_never_exits(self) -> None:
		ble = self.makeBle()
		ble._readerThread.is_alive.return_value = True

		with (
			patch(f"{_MODULE}.runCoroutine"),
			patch(f"{_MODULE}.CLOSE_TIMEOUT_SECONDS", 0.05),
		):
			ble.close()

		ble._readerThread.join.assert_called_once_with(0.05)

	def test_the_reader_is_told_to_stop(self) -> None:
		ble = self.makeBle()

		with patch(f"{_MODULE}.runCoroutine"):
			ble.close()

		self.assertTrue(ble._stopReaderEvent.is_set())

	def test_drain_returns_once_the_reader_catches_up(self) -> None:
		"""The bound is a backstop; a reader that keeps up is still waited for."""
		ble = self.makeBle()
		ble._queuedData.put(b"dispatched shortly")

		def dispatch() -> None:
			ble._queuedData.get()
			ble._queuedData.task_done()

		threading.Timer(0.02, dispatch).start()

		self.assertTrue(ble._drainReceivedData(2))
