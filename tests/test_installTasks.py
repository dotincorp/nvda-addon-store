# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

import unittest
from unittest.mock import patch

import config
from configobj import ConfigObj

from addon import installTasks


def _makeConf() -> config.ConfigManager:
	"""A config manager whose base profile holds none of the settings under test.

	``ConfigManager`` loads the on-disk test configuration, which is generated and
	survives between runs, so anything a previous run left there would otherwise
	decide what these tests see.
	"""
	conf = config.ConfigManager()
	for section in ("braille", installTasks.CONFIG_SECTION_NAME):
		conf.profiles[0].pop(section, None)
	conf._handleProfileSwitch(shouldNotify=False)
	return conf


def _activateProfile(conf: config.ConfigManager, values: dict) -> None:
	"""Push an extra configuration profile holding the given values."""
	profile = ConfigObj(values, indent_type="	", encoding="UTF-8")
	profile.name = "test"
	profile.manual = True
	profile.triggered = False
	conf.profiles.append(profile)
	conf._handleProfileSwitch(shouldNotify=False)


class TestHelpers(unittest.TestCase):
	def test_withoutDriver_removesDotPad(self) -> None:
		self.assertEqual(
			installTasks._withoutDriver(["hidBrailleStandard", "dotPad"]),
			["hidBrailleStandard"],
		)

	def test_withoutDriver_noOpWhenAbsent(self) -> None:
		self.assertEqual(installTasks._withoutDriver(["hidBrailleStandard"]), ["hidBrailleStandard"])

	def test_withoutDriver_preservesOrder(self) -> None:
		self.assertEqual(installTasks._withoutDriver(["a", "dotPad", "b"]), ["a", "b"])

	def test_withoutDriver_emptyList(self) -> None:
		self.assertEqual(installTasks._withoutDriver([]), [])

	def test_isTrue(self) -> None:
		for value in (True, "True", "true", "yes", "1", "on"):
			with self.subTest(value=value):
				self.assertTrue(installTasks._isTrue(value))
		for value in (False, "False", "false", "no", "0", "", None):
			with self.subTest(value=value):
				self.assertFalse(installTasks._isTrue(value))

	def test_promptAlreadyShown_missingSection(self) -> None:
		self.assertFalse(installTasks._promptAlreadyShown({}))

	def test_promptAlreadyShown_missingKey(self) -> None:
		self.assertFalse(installTasks._promptAlreadyShown({"dotPad": {}}))

	def test_promptAlreadyShown_rawStringValues(self) -> None:
		self.assertTrue(installTasks._promptAlreadyShown({"dotPad": {"autoDetectPromptShown": "True"}}))
		self.assertFalse(installTasks._promptAlreadyShown({"dotPad": {"autoDetectPromptShown": "False"}}))

	def test_markPromptShown_createsSection(self) -> None:
		profile: dict = {}
		installTasks._markPromptShown(profile)
		self.assertTrue(profile["dotPad"]["autoDetectPromptShown"])

	def test_markPromptShown_keepsOtherSettings(self) -> None:
		profile = {"dotPad": {"autoRefresh": 3}}
		installTasks._markPromptShown(profile)
		self.assertEqual(profile["dotPad"]["autoRefresh"], 3)
		self.assertTrue(profile["dotPad"]["autoDetectPromptShown"])


class TestGetExcludedDisplays(unittest.TestCase):
	@patch("addon.installTasks.config")
	def test_readsBaseProfile(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]
		baseProfile["braille"] = {"auto": {"excludedDisplays": ["dotPad", "baseOnly"]}}

		self.assertEqual(installTasks._getExcludedDisplays(baseProfile), ["dotPad", "baseOnly"])

	@patch("addon.installTasks.config")
	def test_fallsBackToSpecDefaultRatherThanActiveProfile(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]
		_activateProfile(mockConfig.conf, {"braille": {"auto": {"excludedDisplays": ["brailliantB"]}}})

		# The base profile has no value of its own, so NVDA's default applies to it —
		# not whatever the active profile happens to exclude.
		self.assertEqual(installTasks._getExcludedDisplays(baseProfile), ["dotPad"])

	@patch("addon.installTasks.config")
	def test_coercesSingleValueWrittenWithoutTrailingComma(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]
		baseProfile["braille"] = {"auto": {"excludedDisplays": "dotPad"}}

		self.assertEqual(installTasks._getExcludedDisplays(baseProfile), ["dotPad"])


class TestEnableAutomaticDetection(unittest.TestCase):
	@patch("addon.installTasks.config")
	def test_createsMissingSections(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]

		installTasks._enableAutomaticDetection(baseProfile, ["dotPad", "someOtherDisplay"])

		self.assertEqual(baseProfile["braille"]["auto"]["excludedDisplays"], ["someOtherDisplay"])

	@patch("addon.installTasks.config")
	def test_leavesOtherBrailleSettingsAlone(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]
		baseProfile["braille"] = {"translationTable": "en-ueb-g2", "auto": {"excludedDisplays": ["dotPad"]}}

		installTasks._enableAutomaticDetection(baseProfile, ["dotPad"])

		self.assertEqual(baseProfile["braille"]["translationTable"], "en-ueb-g2")
		self.assertEqual(baseProfile["braille"]["auto"]["excludedDisplays"], [])


class TestOnInstall(unittest.TestCase):
	def _run(self, askResult, baseExcluded=("dotPad",), activeProfile=None):
		"""Run onInstall with a stubbed dialog, returning the config manager."""
		with patch("addon.installTasks.config") as mockConfig:
			mockConfig.conf = _makeConf()
			if baseExcluded is not None:
				mockConfig.conf.profiles[0]["braille"] = {"auto": {"excludedDisplays": list(baseExcluded)}}
			if activeProfile is not None:
				_activateProfile(mockConfig.conf, activeProfile)
			with patch("addon.installTasks._askUser") as mockAsk:
				mockAsk.side_effect = askResult if callable(askResult) else lambda: askResult
				installTasks.onInstall()
				self.mockAsk = mockAsk
			return mockConfig.conf

	def test_yes_enablesDetectionAndMarksPromptShown(self) -> None:
		conf = self._run(True, baseExcluded=["dotPad", "someOtherDisplay"])
		baseProfile = conf.profiles[0]
		self.assertEqual(baseProfile["braille"]["auto"]["excludedDisplays"], ["someOtherDisplay"])
		self.assertTrue(baseProfile["dotPad"]["autoDetectPromptShown"])

	def test_yes_isVisibleToTheRunningSession(self) -> None:
		# The braille settings dialog re-saves this list on OK, so a stale aggregated
		# value would write the exclusion straight back before NVDA restarts.
		conf = self._run(True)
		self.assertEqual(conf["braille"]["auto"]["excludedDisplays"], [])

	def test_no_leavesExclusionListAloneButMarksPromptShown(self) -> None:
		conf = self._run(False)
		self.assertEqual(conf.profiles[0]["braille"]["auto"]["excludedDisplays"], ["dotPad"])
		self.assertTrue(conf.profiles[0]["dotPad"]["autoDetectPromptShown"])

	def test_doesNotAskAgainOncePromptShown(self) -> None:
		with patch("addon.installTasks.config") as mockConfig:
			mockConfig.conf = _makeConf()
			mockConfig.conf.profiles[0]["dotPad"] = {"autoDetectPromptShown": "True"}
			with patch("addon.installTasks._askUser") as mockAsk:
				installTasks.onInstall()
			mockAsk.assert_not_called()
			self.assertNotIn("braille", mockConfig.conf.profiles[0])

	def test_doesNotAskWhenDetectionAlreadyEnabled(self) -> None:
		conf = self._run(True, baseExcluded=["someOtherDisplay"])
		self.mockAsk.assert_not_called()
		self.assertEqual(conf.profiles[0]["braille"]["auto"]["excludedDisplays"], ["someOtherDisplay"])
		self.assertTrue(conf.profiles[0]["dotPad"]["autoDetectPromptShown"])

	def test_asksEvenIfAnActiveProfileAlreadyEnabledDetection(self) -> None:
		# Detection being enabled in one profile says nothing about the base profile,
		# which is where the answer is stored.
		conf = self._run(True, activeProfile={"braille": {"auto": {"excludedDisplays": []}}})
		self.mockAsk.assert_called_once()
		self.assertEqual(conf.profiles[0]["braille"]["auto"]["excludedDisplays"], [])

	def test_doesNotCopyActiveProfileExclusionsIntoBaseProfile(self) -> None:
		conf = self._run(
			True,
			baseExcluded=None,
			activeProfile={"braille": {"auto": {"excludedDisplays": ["brailliantB", "dotPad"]}}},
		)
		self.assertEqual(conf.profiles[0]["braille"]["auto"]["excludedDisplays"], [])

	def test_dialogFailureIsSwallowed(self) -> None:
		def boom():
			raise RuntimeError("no gui")

		# Must not propagate: an exception from onInstall rolls back the installation.
		conf = self._run(boom)
		self.assertNotIn("dotPad", conf.profiles[0])


if __name__ == "__main__":
	unittest.main()
