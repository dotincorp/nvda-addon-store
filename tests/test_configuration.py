# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

import unittest
from unittest.mock import patch

import config

from addon import configuration
from addon.configuration import AutoRefresh, LineSpacingOption


class TestConfiguration(unittest.TestCase):
	def setUp(self):
		# Reset the initialized state before each test
		configuration.initialized = False
		configuration._cachedConfig = {}

	@patch("addon.configuration.config")
	def test_getAutoRefresh_initializes_config(self, mock_config):
		# Create an empty conf-like structure
		mock_config.conf = config.ConfigManager()

		# Call getAutoRefresh which should trigger initialization
		result = configuration.getAutoRefresh()

		# Verify config was initialized
		self.assertTrue(configuration.initialized)
		# Verify config section was created
		self.assertIn(configuration.CONFIG_SECTION_NAME, mock_config.conf)
		# Verify default value is returned (3 = TEXT | GRAPHIC)
		self.assertEqual(result, AutoRefresh.TEXT | AutoRefresh.GRAPHIC)
		# Verify the section has a spec attribute that was updated
		self.assertTrue(hasattr(mock_config.conf[configuration.CONFIG_SECTION_NAME], "spec"))
		# Verify spec was updated
		self.assertEqual(
			mock_config.conf[configuration.CONFIG_SECTION_NAME].spec,  # type: ignore
			configuration.CONFIG_SPEC,
		)


class TestLineSpacingOption(unittest.TestCase):
	def test_enum_values(self) -> None:
		self.assertEqual(LineSpacingOption.AUTO, 0)
		self.assertEqual(LineSpacingOption.MAX_LINE_COUNT, 1)
		self.assertEqual(LineSpacingOption.DOUBLE_LINE_SPACING, 2)

	def test_payloads_auto(self) -> None:
		paddingDots, forceSixDot = configuration.LINE_SPACING_PAYLOADS[LineSpacingOption.AUTO]
		self.assertEqual(paddingDots, 1)
		self.assertFalse(forceSixDot)

	def test_payloads_max_line_count(self) -> None:
		paddingDots, forceSixDot = configuration.LINE_SPACING_PAYLOADS[LineSpacingOption.MAX_LINE_COUNT]
		self.assertEqual(paddingDots, 1)
		self.assertTrue(forceSixDot)

	def test_payloads_double_line_spacing(self) -> None:
		paddingDots, forceSixDot = configuration.LINE_SPACING_PAYLOADS[LineSpacingOption.DOUBLE_LINE_SPACING]
		self.assertEqual(paddingDots, 3)
		self.assertFalse(forceSixDot)

	def test_all_options_have_payload(self) -> None:
		for option in LineSpacingOption:
			self.assertIn(option, configuration.LINE_SPACING_PAYLOADS)

	@patch("addon.configuration.config")
	def test_getMultilineBrailleSpacing_default(self, mock_config: object) -> None:
		import config as real_config

		mock_config.conf = real_config.ConfigManager()  # type: ignore[attr-defined]
		configuration.initialized = False
		configuration._cachedConfig = {}
		result = configuration.getMultilineBrailleSpacing()
		self.assertEqual(result, LineSpacingOption.AUTO)

	@patch("addon.configuration.config")
	def test_getMultilineBrailleSpacing_round_trip(self, mock_config: object) -> None:
		import config as real_config

		for option in LineSpacingOption:
			mock_config.conf = real_config.ConfigManager()  # type: ignore[attr-defined]
			configuration.initialized = False
			configuration._cachedConfig = {}
			configuration.initializeConfig()
			mock_config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore[attr-defined]
				configuration.MULTILINE_BRAILLE_SPACING_SETTING_NAME
			] = option.value
			result = configuration.getMultilineBrailleSpacing()
			self.assertEqual(result, option, f"round-trip failed for {option!r}")

	@patch("addon.configuration.config")
	def test_getMultilineBrailleSpacing_invalid_falls_back_to_auto(self, mock_config: object) -> None:
		import config as real_config

		mock_config.conf = real_config.ConfigManager()  # type: ignore[attr-defined]
		configuration.initialized = False
		configuration._cachedConfig = {}
		configuration.initializeConfig()
		# Force an out-of-range raw value by manipulating the cache directly
		configuration._cachedConfig[configuration.MULTILINE_BRAILLE_SPACING_SETTING_NAME] = 99
		result = configuration.getMultilineBrailleSpacing(fromCache=True)
		self.assertEqual(result, LineSpacingOption.AUTO)
