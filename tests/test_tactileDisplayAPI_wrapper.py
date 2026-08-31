# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for TactileDisplayAPI typed wrapper.

Internals-touching tests (``_ptr``/``_vtbl``/``_dll``) were removed in
feature 011 — the wrapper now holds a single comtypes typed pointer
(``_ifacePtr``) and the declarative-shape coverage lives in
``test_wrapper_comtypes.py``. The enum tests stay because the public
``DPConnectionPreference`` / ``DPFillKind`` enums are stable contracts.
"""

import unittest


class TestEnums(unittest.TestCase):
	"""Tests for wrapper enum definitions."""

	def test_connection_preference_values(self) -> None:
		"""DPConnectionPreference enum should match COM interface values."""
		from addon.tactileDisplayAPI.wrapper import DPConnectionPreference

		self.assertEqual(DPConnectionPreference.AUTO, 0)
		self.assertEqual(DPConnectionPreference.USB, 1)
		self.assertEqual(DPConnectionPreference.BLUETOOTH, 2)
		self.assertEqual(DPConnectionPreference.BOTH, 3)

	def test_fill_kind_values(self) -> None:
		"""DPFillKind enum should match COM interface values."""
		from addon.tactileDisplayAPI.wrapper import DPFillKind

		self.assertEqual(DPFillKind.SOLID, 0)
		self.assertEqual(DPFillKind.DOTTED, 1)
		self.assertEqual(DPFillKind.HORIZONTAL_STRIPE, 2)
		self.assertEqual(DPFillKind.VERTICAL_STRIPE, 3)

	def test_connection_preference_is_int(self) -> None:
		"""Enum values should be usable as ints for COM calls."""
		from addon.tactileDisplayAPI.wrapper import DPConnectionPreference

		self.assertEqual(int(DPConnectionPreference.AUTO), 0)
		self.assertEqual(int(DPConnectionPreference.BOTH), 3)


class TestWrapperLifecycle(unittest.TestCase):
	"""Tests for the wrapper's public lifecycle surface that don't require
	a real DLL load. The internals were rewritten in feature 011; these
	tests exercise only the public method-call surface."""

	def test_can_create_wrapper(self) -> None:
		"""Should be able to create a wrapper without connecting."""
		from addon.tactileDisplayAPI.wrapper import TactileDisplayAPI

		tda = TactileDisplayAPI()
		self.assertIsNotNone(tda)

	def test_close_is_idempotent(self) -> None:
		"""Calling close() multiple times must not raise."""
		from addon.tactileDisplayAPI.wrapper import TactileDisplayAPI

		tda = TactileDisplayAPI()
		tda.close()
		tda.close()  # should not raise
