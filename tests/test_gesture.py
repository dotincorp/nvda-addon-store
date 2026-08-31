# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025 Dot Incorporated

import unittest

from addon.brailleDisplayDrivers.dotPad.driver import InputGesture, KeyGroup


class TestInputGesture(unittest.TestCase):
	def test_simpleGesture(self):
		"""Test a simple single key gesture."""
		keys = [(KeyGroup.FUNCTION, 0)]  # f1
		gesture = InputGesture(keys, isLongPress=False)
		self.assertEqual(gesture.id, "f1")
		self.assertFalse(gesture.isLongPress)

	def test_combinationGesture(self):
		"""Test a combination gesture with multiple keys."""
		keys = [(KeyGroup.FUNCTION, 0), (KeyGroup.FUNCTION, 1)]  # f1+f2
		gesture = InputGesture(keys, isLongPress=False)
		self.assertEqual(gesture.id, "f1+f2")
		self.assertFalse(gesture.isLongPress)

	def test_simpleLongPressGesture(self):
		"""Test a simple single key long press gesture."""
		keys = [(KeyGroup.FUNCTION, 0)]  # f1
		gesture = InputGesture(keys, isLongPress=True)
		self.assertEqual(gesture.id, "longPress(f1)")
		self.assertTrue(gesture.isLongPress)

	def test_combinationLongPressGesture(self):
		"""Test a combination long press gesture with multiple keys."""
		keys = [(KeyGroup.FUNCTION, 0), (KeyGroup.FUNCTION, 1)]  # f1+f2
		gesture = InputGesture(keys, isLongPress=True)
		self.assertEqual(gesture.id, "longPress(f1+f2)")
		self.assertTrue(gesture.isLongPress)

	def test_perkinsKeyGesture(self):
		"""Test a Perkins key gesture."""
		keys = [(KeyGroup.PERKINS, 8)]  # space
		gesture = InputGesture(keys, isLongPress=False)
		self.assertEqual(gesture.id, "space")
		self.assertFalse(gesture.isLongPress)

	def test_perkinsKeyLongPressGesture(self):
		"""Test a Perkins key long press gesture."""
		keys = [(KeyGroup.PERKINS, 8)]  # space
		gesture = InputGesture(keys, isLongPress=True)
		self.assertEqual(gesture.id, "longPress(space)")
		self.assertTrue(gesture.isLongPress)

	def test_mixedKeyGroupsGesture(self):
		"""Test a gesture combining different key groups."""
		keys = [(KeyGroup.FUNCTION, 0), (KeyGroup.PERKINS, 8)]  # f1+space
		gesture = InputGesture(keys, isLongPress=False)
		self.assertEqual(gesture.id, "f1+space")
		self.assertFalse(gesture.isLongPress)

	def test_mixedKeyGroupsLongPressGesture(self):
		"""Test a long press gesture combining different key groups."""
		keys = [(KeyGroup.FUNCTION, 0), (KeyGroup.PERKINS, 8)]  # f1+space
		gesture = InputGesture(keys, isLongPress=True)
		self.assertEqual(gesture.id, "longPress(f1+space)")
		self.assertTrue(gesture.isLongPress)

	def test_formatLongPressId(self):
		"""Test the format function directly."""
		keys = [(KeyGroup.FUNCTION, 0)]
		gesture = InputGesture(keys, isLongPress=False)
		formatted = gesture._formatLongPressId("f1+f2")
		self.assertEqual(formatted, "longPress(f1+f2)")


if __name__ == "__main__":
	unittest.main()
