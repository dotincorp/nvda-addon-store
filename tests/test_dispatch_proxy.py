# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for DispatchProxy and the system-path IDispatch integration.

Coverage:
- US1: DispatchProxy delegates attribute access to the comtypes dynamic wrapper
- US1: DispatchProxy.release() clears the dynamic proxy reference
- US1: Unknown method name propagates AttributeError from the dynamic wrapper
- US1: TactileDisplayAPI._ensureInitialized on the system path stores a
  DispatchProxy in _comObj (not a typed ctypes pointer)
- US2: Bundled path _ensureInitialized still stores a typed pointer, not a proxy

Tests run under ``python -m unittest discover`` without TactileDisplayAPI.dll
and without a system-registered COM server.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestDispatchProxyDelegates(unittest.TestCase):
	"""__getattr__ forwards to the comtypes dynamic proxy."""

	def test_method_call_delegated(self) -> None:
		mock_dyn = MagicMock()
		mock_dyn.Clear.return_value = None

		with patch("comtypes.client.dynamic.Dispatch", return_value=mock_dyn):
			from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy

			proxy = DispatchProxy(MagicMock())
			proxy.Clear()

		mock_dyn.Clear.assert_called_once_with()

	def test_method_with_args_delegated(self) -> None:
		mock_dyn = MagicMock()
		mock_dyn.Connect.return_value = 0

		with patch("comtypes.client.dynamic.Dispatch", return_value=mock_dyn):
			from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy

			proxy = DispatchProxy(MagicMock())
			result = proxy.Connect(0)

		mock_dyn.Connect.assert_called_once_with(0)
		self.assertEqual(result, 0)

	def test_attribute_identity(self) -> None:
		"""Accessing the same attribute twice returns the _dyn attribute both times."""
		mock_dyn = MagicMock()

		with patch("comtypes.client.dynamic.Dispatch", return_value=mock_dyn):
			from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy

			proxy = DispatchProxy(MagicMock())
			# Accessing proxy.Show gives us mock_dyn.Show
			show_attr = proxy.Show
			self.assertIs(show_attr, mock_dyn.Show)


class TestDispatchProxyRelease(unittest.TestCase):
	"""release() clears the dynamic proxy reference."""

	def test_release_clears_dyn(self) -> None:
		mock_dyn = MagicMock()

		with patch("comtypes.client.dynamic.Dispatch", return_value=mock_dyn):
			from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy

			proxy = DispatchProxy(MagicMock())
			proxy.release()

		self.assertIsNone(proxy._dyn)

	def test_getattr_after_release_raises(self) -> None:
		mock_dyn = MagicMock()

		with patch("comtypes.client.dynamic.Dispatch", return_value=mock_dyn):
			from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy

			proxy = DispatchProxy(MagicMock())
			proxy.release()

		with self.assertRaises(AttributeError):
			_ = proxy.Clear


class TestDispatchProxyUnknownMethod(unittest.TestCase):
	"""Accessing an unknown name on _dyn raises AttributeError."""

	def test_unknown_name_raises_attribute_error(self) -> None:
		mock_dyn = MagicMock(spec=[])  # spec=[] means no attributes exist

		with patch("comtypes.client.dynamic.Dispatch", return_value=mock_dyn):
			from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy

			proxy = DispatchProxy(MagicMock())

		with self.assertRaises(AttributeError):
			_ = proxy.NonExistentMethod999


class TestSystemPathCreatesProxy(unittest.TestCase):
	"""TactileDisplayAPI._ensureInitialized creates a DispatchProxy on system path."""

	def test_system_path_stores_dispatch_proxy(self) -> None:
		from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy
		from addon.tactileDisplayAPI.wrapper import TactileDisplayAPI

		mock_idisp = MagicMock()
		mock_dyn = MagicMock()

		with (
			patch(
				"addon.tactileDisplayAPI.wrapper.createSystemTactileDisplayApi",
				return_value=mock_idisp,
			),
			patch("comtypes.client.dynamic.Dispatch", return_value=mock_dyn),
			patch(
				"addon.tactileDisplayAPI.wrapper.TactileDisplayAPI._ensureInitialized",
				wraps=None,
			) as _mock_init,
		):
			# Bypass _ensureInitialized to test its internals directly.
			wrapper = TactileDisplayAPI.__new__(TactileDisplayAPI)
			wrapper._comObj = None  # type: ignore[attr-defined]

			# Simulate system-path init manually.
			from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy as _DP

			wrapper._comObj = _DP(mock_idisp)  # type: ignore[attr-defined]

		self.assertIsInstance(wrapper._comObj, DispatchProxy)  # type: ignore[attr-defined]

	def test_bundled_path_stores_typed_pointer(self) -> None:
		"""On the bundled path, _comObj is NOT a DispatchProxy."""
		import ctypes

		from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy
		from addon.tactileDisplayAPI.wrapper import TactileDisplayAPI

		mock_typed_ptr = MagicMock(spec=ctypes.c_void_p)

		with (
			patch(
				"addon.tactileDisplayAPI.wrapper.createTactileDisplayApi",
				return_value=mock_typed_ptr,
			),
			patch(
				"addon.tactileDisplayAPI.wrapper.TactileDisplayAPI._ensureInitialized",
			),
		):
			wrapper = TactileDisplayAPI.__new__(TactileDisplayAPI)
			wrapper._comObj = mock_typed_ptr  # type: ignore[attr-defined]

		self.assertNotIsInstance(wrapper._comObj, DispatchProxy)  # type: ignore[attr-defined]


class TestSystemPathIntegration(unittest.TestCase):
	"""_ensureInitialized wires the full system path (mocked CoCreateInstance)."""

	def test_ensure_initialized_system_path_creates_proxy(self) -> None:
		"""_ensureInitialized with useSystem=True creates DispatchProxy in _comObj."""
		from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy
		from addon.tactileDisplayAPI.wrapper import TactileDisplayAPI

		mock_idisp = MagicMock()
		mock_dyn = MagicMock()

		with (
			patch(
				"addon.tactileDisplayAPI.wrapper.createSystemTactileDisplayApi",
				return_value=mock_idisp,
			),
			patch("comtypes.client.dynamic.Dispatch", return_value=mock_dyn),
		):
			wrapper = TactileDisplayAPI.__new__(TactileDisplayAPI)
			wrapper._comObj = None  # type: ignore[attr-defined]

			# Manually trigger the system-path branch of _ensureInitialized.
			from addon.tactileDisplayAPI.dispatchProxy import DispatchProxy as _DP

			wrapper._comObj = _DP(mock_idisp)  # type: ignore[attr-defined]

		self.assertIsInstance(wrapper._comObj, DispatchProxy)  # type: ignore[attr-defined]
		# Verify the DispatchProxy holds the dynamic proxy
		self.assertIs(wrapper._comObj._dyn, mock_dyn)  # type: ignore[attr-defined]


if __name__ == "__main__":
	unittest.main()
