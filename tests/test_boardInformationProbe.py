# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for waiting on the board information response while probing a port."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

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
	"""A bare driver whose fake handler mimics the real one's order: displays first, then
	the board information the probe waits on."""
	driver = dotpad_driver.BrailleDisplayDriver.__new__(dotpad_driver.BrailleDisplayDriver)
	driver._initSendState()
	driver._resetReceiveBuffer()
	driver._boardInformation = None
	driver.graphicDisplay = None

	def handleResponse(packet: Packet) -> None:
		if packet.packetType == PacketType.RSP_BOARD_INFORMATION:
			driver.graphicDisplay = MagicMock(name="graphicDisplay")
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
		# The caller sets the library up from the graphic display, so returning before the
		# handler has built it would hand out a driver that has none.
		self.assertIsNotNone(driver.graphicDisplay)

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


def _makeHandlerDriver() -> dotpad_driver.BrailleDisplayDriver:
	"""A bare driver that runs the real ``_handleResponse``."""
	driver = dotpad_driver.BrailleDisplayDriver.__new__(dotpad_driver.BrailleDisplayDriver)
	driver._initSendState()
	driver._boardInformation = None
	driver.textDisplay = None
	driver.graphicDisplay = None
	driver._renderer = None
	return driver


def _boardInformationPacket() -> MagicMock:
	"""A board information packet reporting both a 20-cell text and a 10×30 tactile area.

	Args are features, dotsPerCell, distanceBetweenPins and functionKeyCount, then the
	text and graphic descriptors as rowCount, columnCount, dividedLine, refreshTime.
	"""
	packet = MagicMock(name="boardInfoPacket")
	packet.packetType = dotpad_driver.PacketType.RSP_BOARD_INFORMATION
	packet.args = bytes([0, 1, 0x1A, 0, 1, 20, 0, 1, 10, 30, 0, 1])
	return packet


class TestBoardInformationPublishedLast(unittest.TestCase):
	"""``_boardInformation`` appearing means the handler finished, displays included."""

	def test_it_is_published_only_after_the_displays_are_built(self) -> None:
		driver = _makeHandlerDriver()
		publishedWhileBuilding: list[bool] = []

		def fakeCreate(descriptor, dotsPerCell, **kwargs):
			publishedWhileBuilding.append(driver._boardInformation is not None)
			display = MagicMock(name="display")
			display.numCols = descriptor.columnCount
			display.numRows = descriptor.rowCount
			return display

		driver._createDisplay = MagicMock(side_effect=fakeCreate)

		with (
			patch("addon.presentations.PresentationRenderer", MagicMock()),
			patch.object(dotpad_driver.configuration, "getAutoRefresh", return_value=0),
		):
			driver._handleResponse(_boardInformationPacket())

		self.assertFalse(any(publishedWhileBuilding))
		self.assertIsNotNone(driver._boardInformation)
		self.assertIsNotNone(driver.graphicDisplay)

	def test_the_handler_does_not_build_the_renderer(self) -> None:
		"""It is built at the end of ``__init__`` instead: it loads the presentations
		package and picks a first presentation, which is slower than the probe's deadline
		and would run on the I/O thread with the send gate shut."""
		driver = _makeHandlerDriver()
		driver._createDisplay = MagicMock()

		with (
			patch("addon.presentations.PresentationRenderer") as renderer,
			patch.object(dotpad_driver.configuration, "getAutoRefresh", return_value=0),
		):
			driver._handleResponse(_boardInformationPacket())

		renderer.assert_not_called()
		self.assertIsNone(driver._renderer)
		self.assertIsNotNone(driver._boardInformation)

	def test_it_is_published_even_when_a_display_cannot_be_built(self) -> None:
		"""A probe that waited out its deadline here would report no display found at all."""
		driver = _makeHandlerDriver()
		driver._createDisplay = MagicMock(side_effect=RuntimeError("no display for you"))

		with (
			patch("addon.presentations.PresentationRenderer", MagicMock()),
			patch.object(dotpad_driver.configuration, "getAutoRefresh", return_value=0),
			self.assertRaises(RuntimeError),
		):
			driver._handleResponse(_boardInformationPacket())

		self.assertIsNotNone(driver._boardInformation)
