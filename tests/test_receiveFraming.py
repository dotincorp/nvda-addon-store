# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for splitting received bytes into frames.

A BLE notification has no message boundaries: it can carry several frames, or part of one.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from addon.brailleDisplayDrivers.dotPad import driver as dotpad_driver
from addon.brailleDisplayDrivers.dotPad.driver import Packet, PacketType

#: NTF_DISPLAY_LINE for row 1 and RSP_FIRMWARE_VERSION, as the display sends them in one notification.
MERGED_NOTIFICATION = b"\xaaU\x00\x06\x01\x02\x02\x00\x00\xa4\xaaU\x00\r\x00\x00\x01\x00vA.0.2.6\x89"
RENDERED = b"\xaaU\x00\x06\x01\x02\x02\x00\x00\xa4"
FIRMWARE = b"\xaaU\x00\r\x00\x00\x01\x00vA.0.2.6\x89"


def _makeDriver() -> dotpad_driver.BrailleDisplayDriver:
	driver = dotpad_driver.BrailleDisplayDriver.__new__(dotpad_driver.BrailleDisplayDriver)
	driver._initSendState()
	driver._resetReceiveBuffer()
	driver._dev = MagicMock()
	# BLE has no synchronous read; parsing must never depend on one.
	driver._dev.read.side_effect = NotImplementedError
	return driver


class FramingTestCase(unittest.TestCase):
	def setUp(self) -> None:
		self.driver = _makeDriver()
		self.received: list[Packet] = []
		self.driver._handleResponse = self.received.append  # type: ignore[method-assign]

	def feed(self, *chunks: bytes) -> None:
		for chunk in chunks:
			self.driver._onReceive(chunk)


class TestFrameBoundaries(FramingTestCase):
	def test_the_fixtures_are_valid_frames(self) -> None:
		"""A typo here would make the tests below meaningless."""
		self.assertEqual(RENDERED + FIRMWARE, MERGED_NOTIFICATION)
		for frame in (RENDERED, FIRMWARE):
			with self.subTest(frame=frame):
				self.assertTrue(Packet(frame).isValid)

	def test_two_frames_in_one_notification(self) -> None:
		self.feed(MERGED_NOTIFICATION)

		self.assertEqual(
			[(PacketType.NTF_DISPLAY_LINE, 1), (PacketType.RSP_FIRMWARE_VERSION, 0)],
			[(p.packetType, p.destination) for p in self.received],
		)
		self.assertEqual(b"vA.0.2.6", self.received[1].args)

	def test_one_frame_split_across_notifications(self) -> None:
		self.feed(FIRMWARE[:5], FIRMWARE[5:])

		self.assertEqual([FIRMWARE], self.received)

	def test_a_notification_ending_part_way_into_the_next_frame(self) -> None:
		self.feed(RENDERED + FIRMWARE[:6], FIRMWARE[6:])

		self.assertEqual([RENDERED, FIRMWARE], self.received)

	def test_byte_at_a_time_as_serial_delivers_it(self) -> None:
		self.feed(*(bytes([b]) for b in MERGED_NOTIFICATION))

		self.assertEqual([RENDERED, FIRMWARE], self.received)

	def test_a_partial_frame_is_kept_not_dispatched(self) -> None:
		self.feed(FIRMWARE[:-1])

		self.assertEqual([], self.received)
		self.assertEqual(len(FIRMWARE) - 1, len(self.driver._receiveBuffer))


class TestResynchronisation(FramingTestCase):
	def test_leading_garbage_is_skipped(self) -> None:
		self.feed(b"\x00\x11\xaa\x22" + RENDERED)

		self.assertEqual([RENDERED], self.received)

	def test_a_bad_checksum_drops_only_that_frame(self) -> None:
		corrupt = RENDERED[:-1] + b"\x00"
		self.feed(corrupt + FIRMWARE)

		self.assertEqual([FIRMWARE], self.received)

	def test_an_implausibly_long_header_does_not_stall_the_stream(self) -> None:
		"""A false sync word must not make the parser wait for a length that never comes."""
		bogus = dotpad_driver.DP_SYNC + dotpad_driver.DP_MAX_PACKET_SIZE.to_bytes(2, "big")
		self.feed(bogus + RENDERED)

		self.assertEqual([RENDERED], self.received)

	def test_a_runt_length_is_not_treated_as_a_frame(self) -> None:
		runt = dotpad_driver.DP_SYNC + (dotpad_driver.DP_MIN_PACKET_SIZE - 4 - 1).to_bytes(2, "big")
		self.feed(runt + RENDERED)

		self.assertEqual([RENDERED], self.received)

	def test_reset_discards_a_previous_port_s_partial_frame(self) -> None:
		self.feed(FIRMWARE[:7])
		self.driver._resetReceiveBuffer()
		self.feed(RENDERED)

		self.assertEqual([RENDERED], self.received)


class TestMergedNotificationOpensTheSendGate(unittest.TestCase):
	"""Through the real response handler: the render notification opens the send gate."""

	def test_the_render_notification_is_not_lost(self) -> None:
		driver = _makeDriver()
		driver._readyToSend.clear()

		driver._onReceive(MERGED_NOTIFICATION)

		self.assertTrue(driver._readyToSend.is_set())
		self.assertEqual("vA.0.2.6", driver._firmwareVersion)
