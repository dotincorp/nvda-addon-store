# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2025 Dot Incorporated

import unittest

# from unittest.mock import MagicMock, patch
from addon.brailleDisplayDrivers.dotPad.driver import Packet, PacketType


class TestPacketType(unittest.TestCase):
	def test_fromCode(self):
		self.assertEqual(PacketType.fromCode(PacketType.NTF_ERROR.code), PacketType.NTF_ERROR)
		self.assertEqual(
			PacketType.fromCode(PacketType.REQ_BOARD_INFORMATION.code),
			PacketType.REQ_BOARD_INFORMATION,
		)


class TestPacket(unittest.TestCase):
	def test_calculateChecksum(self):
		self.assertEqual(Packet.calculateChecksum(b"abcdef"), 0xA2)
		self.assertEqual(Packet.calculateChecksum(b"\x01\x00\x00\x00"), 0xA4)

	def test_emptyPacket(self):
		p = Packet()
		self.assertEqual(p, b"")
		self.assertEqual(p.sync, b"")
		self.assertEqual(p.length, 0)
		self.assertIsNone(p.packetType)
		self.assertEqual(p.destination, 0)
		self.assertEqual(p.seq, 0)
		self.assertEqual(p.args, b"")
		self.assertEqual(p.checksum, 0)

	def test_setField(self):
		p = Packet(b"abcdef" + PacketType.NTF_ERROR.code)
		p._setField("sync", 0)
		self.assertEqual(p.sync, ord("a"))

		p._setField("sync", 1, 1)
		self.assertEqual(p.sync, b"")

		p._setField("sync", 2, 3)
		self.assertEqual(p.sync, b"c")

		p._setField("sync", 6, 8, PacketType.fromCode)
		self.assertEqual(p.sync, PacketType.NTF_ERROR)

	def test_packetWithValidFields(self):
		# A typical request for firmware version
		p = Packet(b"\xaa\x55\x00\x05\x01\x00\x00\x00\xa4")
		self.assertEqual(p.sync, b"\xaa\x55")
		self.assertEqual(p.length, 5)
		self.assertEqual(p.packetType, PacketType.REQ_FIRMWARE_VERSION)
		self.assertEqual(p.destination, 1)
		self.assertEqual(p.seq, 0)
		self.assertEqual(p.args, b"")
		self.assertEqual(p.checksum, 164)
		self.assertEqual(p.isComplete, True)
		self.assertEqual(p.isValid, True)

		# Firmware version response
		p = Packet(b"\xaa\x55\x00\x0d\x01\x00\x01\x00\x76\x41\x2e\x31\x2e\x30\x2e\x30\x8d")
		self.assertEqual(p.sync, b"\xaa\x55")
		self.assertEqual(p.length, 13)
		self.assertEqual(p.packetType, PacketType.RSP_FIRMWARE_VERSION)
		self.assertEqual(p.destination, 1)
		self.assertEqual(p.seq, 0)
		self.assertEqual(p.args, b"vA.1.0.0")
		self.assertEqual(p.checksum, 141)
		self.assertEqual(p.isComplete, True)
		self.assertEqual(p.isValid, True)


if __name__ == "__main__":
	unittest.main()
