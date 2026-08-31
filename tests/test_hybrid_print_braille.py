# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for feature 031: configurable hybrid print + braille mode.

Mirrors ``tests/test_viewer_toggle.py``: the new ``hybridPrintAndBraille`` setting
defaults False and round-trips through the cache; the driver-init helper forwards the
value to the library and degrades gracefully on failure; and the on-save path re-applies
the setting to a running DotPad driver via the library worker (no-op with no driver).
"""

import unittest
from unittest.mock import MagicMock, patch

import config

from addon import configuration


class TestConfigFlag(unittest.TestCase):
	"""``[dotPad] hybridPrintAndBraille`` defaults to False and round-trips via the cache."""

	def test_config_default_is_false(self):
		"""Opt-in default (FR-007): the setting is off unless the user enables it."""
		configuration.initializeConfig()
		# Set to the spec default to observe it (AggregatedSection has no __delitem__).
		section = config.conf[configuration.CONFIG_SECTION_NAME]
		section[configuration.HYBRID_PRINT_AND_BRAILLE_SETTING_NAME] = False
		configuration.updateConfigCache()
		self.assertFalse(configuration.getHybridPrintAndBraille())

	def test_config_set_then_get_via_cache(self):
		configuration.initializeConfig()
		config.conf[configuration.CONFIG_SECTION_NAME][
			configuration.HYBRID_PRINT_AND_BRAILLE_SETTING_NAME
		] = True
		configuration.updateConfigCache()
		self.assertTrue(configuration.getHybridPrintAndBraille(fromCache=True))
		# Round-trip back to False.
		config.conf[configuration.CONFIG_SECTION_NAME][
			configuration.HYBRID_PRINT_AND_BRAILLE_SETTING_NAME
		] = False
		configuration.updateConfigCache()
		self.assertFalse(configuration.getHybridPrintAndBraille(fromCache=True))


class TestDriverInitSync(unittest.TestCase):
	"""``_setHybridModeOnWorker`` forwards the configured value to the library (US1)."""

	def test_helper_forwards_value_to_library(self):
		from addon.brailleDisplayDrivers.dotPad.driver import _setHybridModeOnWorker

		mockTda = MagicMock()
		_setHybridModeOnWorker(mockTda, True)
		mockTda.setHybridPrintAndBrailleMode.assert_called_once_with(True)
		mockTda.reset_mock()
		_setHybridModeOnWorker(mockTda, False)
		mockTda.setHybridPrintAndBrailleMode.assert_called_once_with(False)

	def test_helper_logs_on_library_failure(self):
		"""When the COM call raises, the helper logs and returns cleanly (FR-006)."""
		from addon.brailleDisplayDrivers.dotPad.driver import _setHybridModeOnWorker

		mockTda = MagicMock()
		mockTda.setHybridPrintAndBrailleMode.side_effect = OSError("HRESULT failure")
		# Must not propagate — fire-and-forget helpers swallow exceptions.
		_setHybridModeOnWorker(mockTda, True)
		mockTda.setHybridPrintAndBrailleMode.assert_called_once_with(True)


def _makePlugin():
	"""Construct a DotPadGlobalPlugin with NVDA menu wiring mocked out."""
	from addon.globalPlugins.dotPad import DotPadGlobalPlugin

	with patch("gui.mainFrame") as mockFrame:
		mockFrame.sysTrayIcon = MagicMock()
		mockFrame.sysTrayIcon.toolsMenu = MagicMock()
		mockMenuItem = MagicMock()
		mockMenuItem.Id = 42
		mockFrame.sysTrayIcon.toolsMenu.AppendCheckItem.return_value = mockMenuItem
		plugin = DotPadGlobalPlugin()
	return plugin


class TestOnSaveLiveApply(unittest.TestCase):
	"""On settings save, the setting is re-applied live to a running driver (US3/FR-008)."""

	def test_applies_saved_value_to_ready_driver(self):
		"""With a ready DotPad driver, submit setHybridPrintAndBrailleMode(savedValue)."""
		from addon.globalPlugins.dotPad import DotPadGlobalPlugin

		plugin = _makePlugin()
		config.conf[configuration.CONFIG_SECTION_NAME][
			configuration.HYBRID_PRINT_AND_BRAILLE_SETTING_NAME
		] = True
		configuration.updateConfigCache()

		mockDriver = MagicMock()
		mockDriver._libraryReady = True
		mockDriver._libraryWorker = MagicMock()
		mockDriver._tda = MagicMock()
		with patch.object(DotPadGlobalPlugin, "_getActiveDotPadDriver", return_value=mockDriver):
			plugin._applyHybridPrintAndBraille()

		self.assertTrue(mockDriver._libraryWorker.submit.called)
		submitArgs = mockDriver._libraryWorker.submit.call_args
		self.assertIs(submitArgs.args[0], mockDriver._tda.setHybridPrintAndBrailleMode)
		self.assertIs(submitArgs.args[1], True)

	def test_no_driver_makes_no_library_call(self):
		"""With no DotPad active, the live-apply path is a clean no-op."""
		from addon.globalPlugins.dotPad import DotPadGlobalPlugin

		plugin = _makePlugin()
		with patch.object(DotPadGlobalPlugin, "_getActiveDotPadDriver", return_value=None):
			# Must not raise.
			plugin._applyHybridPrintAndBraille()


if __name__ == "__main__":
	unittest.main()
