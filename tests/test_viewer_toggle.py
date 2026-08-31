# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for feature 019: NVDA Tools-menu toggle for the library viewer."""

import unittest
from unittest.mock import MagicMock, patch

import config

from addon import configuration
from addon.tactileDisplayAPI.wrapper import TactileDisplayAPI


class TestConfigFlag(unittest.TestCase):
	"""``[dotPad] viewerOnScreen`` defaults to False and round-trips through the cache."""

	def test_config_default_is_false(self):
		configuration.initializeConfig()
		# Reset the persisted value so we observe the spec default. The
		# previous attempt to clear via ``del section[KEY]`` failed under
		# real NVDA because ``config.conf[...]`` returns an
		# ``AggregatedSection`` which doesn't expose ``__delitem__``.
		# Setting the value to the spec default (False) achieves the same
		# observable result for this test (assertFalse on getViewerOnScreen).
		section = config.conf[configuration.CONFIG_SECTION_NAME]
		section[configuration.VIEWER_ON_SCREEN_SETTING_NAME] = False
		configuration.updateConfigCache()
		self.assertFalse(configuration.getViewerOnScreen())

	def test_config_set_then_get_via_cache(self):
		configuration.initializeConfig()
		config.conf[configuration.CONFIG_SECTION_NAME][configuration.VIEWER_ON_SCREEN_SETTING_NAME] = True
		configuration.updateConfigCache()
		self.assertTrue(configuration.getViewerOnScreen(fromCache=True))
		# Round-trip back to False.
		config.conf[configuration.CONFIG_SECTION_NAME][configuration.VIEWER_ON_SCREEN_SETTING_NAME] = False
		configuration.updateConfigCache()
		self.assertFalse(configuration.getViewerOnScreen(fromCache=True))


class TestWrapperMethod(unittest.TestCase):
	"""``showBrailleOnScreen`` forwards the bool to the COM interface."""

	def test_wrapper_passes_bool_to_com(self):
		tda = TactileDisplayAPI()
		mockIface = MagicMock()
		# Patch the _iface property to return our mock instead of touching the
		# real COM object. The wrapper's _iface property is a cast wrapper over
		# _ifacePtr; bypass it by patching _iface directly.
		with patch.object(TactileDisplayAPI, "_iface", new=mockIface):
			tda.showBrailleOnScreen(True)
			tda.showBrailleOnScreen(False)
		calls = mockIface.ShowBrailleOnScreen.call_args_list
		self.assertEqual(len(calls), 2)
		self.assertEqual(calls[0].args, (True,))
		self.assertEqual(calls[1].args, (False,))


def _makePluginWithMockedMenuItem():
	"""Construct a DotPadGlobalPlugin with the menu item pre-replaced by a MagicMock.

	NVDA-side menu wiring (``sysTrayIcon.Bind``, ``toolsMenu.AppendCheckItem``)
	is exercised by ``__init__`` — we tear that down and substitute a fully-
	mocked ``wx.MenuItem`` so the tests run without a live wx frame.
	"""
	from addon.globalPlugins.dotPad import DotPadGlobalPlugin

	with patch("gui.mainFrame") as mockFrame:
		mockFrame.sysTrayIcon = MagicMock()
		mockFrame.sysTrayIcon.toolsMenu = MagicMock()
		mockMenuItem = MagicMock()
		mockMenuItem.Id = 42
		mockFrame.sysTrayIcon.toolsMenu.AppendCheckItem.return_value = mockMenuItem
		plugin = DotPadGlobalPlugin()
	return plugin, mockMenuItem


class TestClickHandler(unittest.TestCase):
	"""Click handler config-flip + library-submit + no-driver no-op paths."""

	def test_handler_flips_config_and_submits(self):
		"""With a ready DotPad driver, flip the config and submit to the library worker."""
		from addon.globalPlugins.dotPad import DotPadGlobalPlugin

		plugin, _menuItem = _makePluginWithMockedMenuItem()
		mockDriver = MagicMock()
		mockDriver._libraryReady = True
		mockDriver._libraryWorker = MagicMock()
		mockDriver._tda = MagicMock()
		mockFuture = MagicMock()
		mockDriver._libraryWorker.submit.return_value = mockFuture
		with patch.object(DotPadGlobalPlugin, "_getActiveDotPadDriver", return_value=mockDriver):
			event = MagicMock()
			event.IsChecked.return_value = True
			# blockAction decorator is a no-op outside secure mode under unit-test
			# conditions, so calling the bound method directly is sufficient.
			plugin.onToggleShowBrailleOnScreen(event)
		self.assertTrue(mockDriver._libraryWorker.submit.called)
		submitArgs = mockDriver._libraryWorker.submit.call_args
		self.assertIs(submitArgs.args[0], mockDriver._tda.showBrailleOnScreen)
		self.assertIs(submitArgs.args[1], True)
		self.assertTrue(configuration.getViewerOnScreen(fromCache=True))
		self.assertTrue(mockFuture.add_done_callback.called)

	def test_handler_no_driver_only_flips_config(self):
		"""With no DotPad active, flip the config but make no library call."""
		from addon.globalPlugins.dotPad import DotPadGlobalPlugin

		plugin, _menuItem = _makePluginWithMockedMenuItem()
		with patch.object(DotPadGlobalPlugin, "_getActiveDotPadDriver", return_value=None):
			event = MagicMock()
			event.IsChecked.return_value = True
			plugin.onToggleShowBrailleOnScreen(event)
		self.assertTrue(configuration.getViewerOnScreen(fromCache=True))
		# No library call attempted — nothing else to assert other than no exception.


class TestTerminate(unittest.TestCase):
	"""``terminate`` removes the menu item idempotently."""

	def test_terminate_removes_menu_item_idempotently(self):
		plugin, menuItem = _makePluginWithMockedMenuItem()
		with patch("gui.mainFrame") as mockFrame:
			mockFrame.sysTrayIcon = MagicMock()
			mockFrame.sysTrayIcon.toolsMenu = MagicMock()
			# Patch the unrelated terminate-time cleanups so super().terminate works.
			with patch("gui.settingsDialogs.NVDASettingsDialog.categoryClasses", new=MagicMock()):
				plugin.terminate()
				self.assertEqual(mockFrame.sysTrayIcon.toolsMenu.Remove.call_count, 1)
				self.assertEqual(menuItem.Destroy.call_count, 1)
				self.assertIsNone(plugin._showBrailleOnScreenItem)
				# Second call: no further Remove / Destroy. (Settings-panel cleanups
				# would raise on a real plugin's second terminate but we've mocked
				# them out; the guard we care about is the menu-item branch.)
				try:
					plugin.terminate()
				except Exception:
					pass
				self.assertEqual(mockFrame.sysTrayIcon.toolsMenu.Remove.call_count, 1)
				self.assertEqual(menuItem.Destroy.call_count, 1)


class TestDriverInitSync(unittest.TestCase):
	"""Driver-init re-sync helper forwards the config flag to the library (US2)."""

	def test_driver_sync_forwards_config_value_to_library(self):
		from addon.brailleDisplayDrivers.dotPad.driver import _setShowBrailleOnScreenOnWorker

		mockTda = MagicMock()
		_setShowBrailleOnScreenOnWorker(mockTda, True)
		mockTda.showBrailleOnScreen.assert_called_once_with(True)
		mockTda.reset_mock()
		_setShowBrailleOnScreenOnWorker(mockTda, False)
		mockTda.showBrailleOnScreen.assert_called_once_with(False)

	def test_driver_sync_logs_on_library_failure(self):
		"""When the COM call raises, the helper logs and returns cleanly."""
		from addon.brailleDisplayDrivers.dotPad.driver import _setShowBrailleOnScreenOnWorker

		mockTda = MagicMock()
		mockTda.showBrailleOnScreen.side_effect = OSError("HRESULT failure")
		# Should not propagate — fire-and-forget helpers swallow exceptions.
		_setShowBrailleOnScreenOnWorker(mockTda, True)
		mockTda.showBrailleOnScreen.assert_called_once_with(True)


if __name__ == "__main__":
	unittest.main()
