# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025 Dot Incorporated

import unittest

from addon.brailleDisplayDrivers.dotPad.driver import D3_DEVICE_NAMES


class MockDriver:
	"""Mock driver class to test supportsHardwareBasedAutoRefresh logic."""

	def __init__(self, deviceName: str | None = None):
		if deviceName is not None:
			self._deviceName = deviceName

	def _get_supportsHardwareBasedAutoRefresh(self) -> bool:
		"""Check if connected device has hardware-based auto-refresh.

		This is a copy of the actual implementation for testing.
		"""
		if not hasattr(self, "_deviceName") or not self._deviceName:
			return False
		return self._deviceName in D3_DEVICE_NAMES

	@property
	def supportsHardwareBasedAutoRefresh(self) -> bool:
		return self._get_supportsHardwareBasedAutoRefresh()


class TestD3DeviceNames(unittest.TestCase):
	"""Test the D3_DEVICE_NAMES constant."""

	def test_dotpad320x_in_d3_devices(self):
		"""DotPad320X should be in the D3 device names set."""
		self.assertIn("DotPad320X", D3_DEVICE_NAMES)

	def test_d3_device_names_is_set(self):
		"""D3_DEVICE_NAMES should be a set for O(1) lookup."""
		self.assertIsInstance(D3_DEVICE_NAMES, set)


class TestSupportsHardwareBasedAutoRefresh(unittest.TestCase):
	"""Test the supportsHardwareBasedAutoRefresh property logic."""

	def test_dotpad320x_supports_hardware_autorefresh(self):
		"""DotPad320X should support hardware-based auto-refresh."""
		driver = MockDriver("DotPad320X")
		self.assertTrue(driver.supportsHardwareBasedAutoRefresh)

	def test_dotpad300a_does_not_support_hardware_autorefresh(self):
		"""DotPad300A (D2 device) should not support hardware-based auto-refresh."""
		driver = MockDriver("DotPad300A")
		self.assertFalse(driver.supportsHardwareBasedAutoRefresh)

	def test_dotpad300b_does_not_support_hardware_autorefresh(self):
		"""DotPad300B should not support hardware-based auto-refresh."""
		driver = MockDriver("DotPad300B")
		self.assertFalse(driver.supportsHardwareBasedAutoRefresh)

	def test_empty_device_name_returns_false(self):
		"""Empty device name should return False."""
		driver = MockDriver("")
		self.assertFalse(driver.supportsHardwareBasedAutoRefresh)

	def test_no_device_name_attribute_returns_false(self):
		"""Missing _deviceName attribute should return False."""
		driver = MockDriver()  # Don't set _deviceName
		self.assertFalse(driver.supportsHardwareBasedAutoRefresh)

	def test_case_sensitive_matching(self):
		"""Device name matching should be case-sensitive."""
		driver = MockDriver("dotpad320x")  # lowercase
		self.assertFalse(driver.supportsHardwareBasedAutoRefresh)

		driver = MockDriver("DOTPAD320X")  # uppercase
		self.assertFalse(driver.supportsHardwareBasedAutoRefresh)

	def test_partial_match_returns_false(self):
		"""Partial device name should not match."""
		driver = MockDriver("DotPad320")  # missing X
		self.assertFalse(driver.supportsHardwareBasedAutoRefresh)

		driver = MockDriver("DotPad320XY")  # extra character
		self.assertFalse(driver.supportsHardwareBasedAutoRefresh)


if __name__ == "__main__":
	unittest.main()
