# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for waiting on the board information response while probing a port."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from addon.brailleDisplayDrivers.dotPad import driver as dotpad_driver
from addon.brailleDisplayDrivers.dotPad.driver import Packet, PacketType

BOARD_INFORMATION = Packet.makePacket(
	PacketType.RSP_BOARD_INFORMATION,
	args=bytes([0, 1, 0x1A, 0, 0, 0, 0, 0, 10, 30, 0, 1]),
)


class _ByteAtATimeSerial:
	"""Delivers one byte of ``data`` per ``waitForRead``, as ``hwIo.Serial`` does."""

	def __init__(self, driver: dotpad_driver.BrailleDisplayDriver, data: bytes) -> None:
		self._driver = driver
		self._pending = list(data)
		self.reads = 0

	def waitForRead(self, timeout: float) -> bool:
		if not self._pending:
			return False
		self.reads += 1
		self._driver._onReceive(bytes([self._pending.pop(0)]))
		return True


def _makeDriver() -> dotpad_driver.BrailleDisplayDriver:
	driver = dotpad_driver.BrailleDisplayDriver.__new__(dotpad_driver.BrailleDisplayDriver)
	driver._initSendState()
	driver._resetReceiveBuffer()
	driver._boardInformation = None

	def handleResponse(packet: Packet) -> None:
		if packet.packetType == PacketType.RSP_BOARD_INFORMATION:
			driver._boardInformation = MagicMock(name="boardInformation")

	driver._handleResponse = handleResponse  # type: ignore[method-assign]
	return driver


class TestAwaitBoardInformation(unittest.TestCase):
	def test_the_fixture_is_a_valid_frame(self) -> None:
		self.assertTrue(Packet(BOARD_INFORMATION).isValid)

	def test_a_response_delivered_byte_at_a_time_is_awaited(self) -> None:
		driver = _makeDriver()
		driver._dev = serial = _ByteAtATimeSerial(driver, BOARD_INFORMATION)

		self.assertTrue(driver._awaitBoardInformation(timeout=5))
		self.assertEqual(len(BOARD_INFORMATION), serial.reads)

	def test_gives_up_when_nothing_answers(self) -> None:
		driver = _makeDriver()
		driver._dev = _ByteAtATimeSerial(driver, b"")

		self.assertFalse(driver._awaitBoardInformation(timeout=0.05))
		self.assertIsNone(driver._boardInformation)

	def test_a_response_parsed_after_the_read_signal_is_still_seen(self) -> None:
		"""BLE sets its read event before the reader thread parses the notification."""
		driver = _makeDriver()
		dev = MagicMock()
		calls = 0

		def waitForRead(timeout: float) -> bool:
			nonlocal calls
			calls += 1
			if calls == 2:
				driver._onReceive(BOARD_INFORMATION)
			return True

		dev.waitForRead.side_effect = waitForRead
		driver._dev = dev

		self.assertTrue(driver._awaitBoardInformation(timeout=5))
		for call in dev.waitForRead.call_args_list:
			self.assertLessEqual(call.args[0], dotpad_driver.BOARD_INFORMATION_POLL_SECONDS)
