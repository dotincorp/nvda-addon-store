# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

import unittest
from unittest.mock import patch

import config
from configobj import ConfigObj

from addon import installTasks

AUTO_DETECT_FLAG = installTasks.AUTO_DETECT_PROMPT_SHOWN_SETTING_NAME
CURSOR_BLINK_FLAG = installTasks.CURSOR_BLINK_PROMPT_SHOWN_SETTING_NAME


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
		self.assertFalse(installTasks._promptAlreadyShown({}, AUTO_DETECT_FLAG))

	def test_promptAlreadyShown_missingKey(self) -> None:
		self.assertFalse(installTasks._promptAlreadyShown({"dotPad": {}}, AUTO_DETECT_FLAG))

	def test_promptAlreadyShown_rawStringValues(self) -> None:
		self.assertTrue(
			installTasks._promptAlreadyShown({"dotPad": {AUTO_DETECT_FLAG: "True"}}, AUTO_DETECT_FLAG),
		)
		self.assertFalse(
			installTasks._promptAlreadyShown({"dotPad": {AUTO_DETECT_FLAG: "False"}}, AUTO_DETECT_FLAG),
		)

	def test_promptAlreadyShown_isPerQuestion(self) -> None:
		# Each question carries its own flag; answering one says nothing about the other.
		profile = {"dotPad": {AUTO_DETECT_FLAG: "True"}}
		self.assertTrue(installTasks._promptAlreadyShown(profile, AUTO_DETECT_FLAG))
		self.assertFalse(installTasks._promptAlreadyShown(profile, CURSOR_BLINK_FLAG))

	def test_markPromptShown_createsSection(self) -> None:
		profile: dict = {}
		installTasks._markPromptShown(profile, AUTO_DETECT_FLAG)
		self.assertTrue(profile["dotPad"][AUTO_DETECT_FLAG])

	def test_markPromptShown_keepsOtherSettings(self) -> None:
		profile = {"dotPad": {"autoRefresh": 3}}
		installTasks._markPromptShown(profile, AUTO_DETECT_FLAG)
		self.assertEqual(profile["dotPad"]["autoRefresh"], 3)
		self.assertTrue(profile["dotPad"][AUTO_DETECT_FLAG])

	def test_markPromptShown_keepsTheOtherQuestionsFlag(self) -> None:
		profile = {"dotPad": {AUTO_DETECT_FLAG: True}}
		installTasks._markPromptShown(profile, CURSOR_BLINK_FLAG)
		self.assertTrue(profile["dotPad"][AUTO_DETECT_FLAG])
		self.assertTrue(profile["dotPad"][CURSOR_BLINK_FLAG])


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


class TestGetCursorBlink(unittest.TestCase):
	@patch("addon.installTasks.config")
	def test_readsBaseProfile(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]
		baseProfile["braille"] = {"cursorBlink": "False"}

		# Values written straight into a profile are unvalidated strings.
		self.assertFalse(installTasks._getCursorBlink(baseProfile))

	@patch("addon.installTasks.config")
	def test_fallsBackToSpecDefaultRatherThanActiveProfile(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]
		_activateProfile(mockConfig.conf, {"braille": {"cursorBlink": "False"}})

		# The base profile has no value of its own, so NVDA's default applies to it —
		# blinking is on — regardless of what the active profile says.
		self.assertTrue(installTasks._getCursorBlink(baseProfile))


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


class TestDisableCursorBlink(unittest.TestCase):
	@patch("addon.installTasks.config")
	def test_createsMissingSection(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]

		installTasks._disableCursorBlink(baseProfile)

		self.assertFalse(baseProfile["braille"]["cursorBlink"])

	@patch("addon.installTasks.config")
	def test_leavesOtherBrailleSettingsAlone(self, mockConfig) -> None:
		mockConfig.conf = _makeConf()
		baseProfile = mockConfig.conf.profiles[0]
		baseProfile["braille"] = {"translationTable": "en-ueb-g2", "cursorBlinkRate": 500}

		installTasks._disableCursorBlink(baseProfile)

		self.assertEqual(baseProfile["braille"]["translationTable"], "en-ueb-g2")
		self.assertEqual(baseProfile["braille"]["cursorBlinkRate"], 500)
		self.assertFalse(baseProfile["braille"]["cursorBlink"])


class TestOnInstall(unittest.TestCase):
	def _run(
		self,
		detectAnswer=True,
		blinkAnswer=False,
		baseExcluded=("dotPad",),
		baseBraille=None,
		promptsShown=None,
		activeProfile=None,
	):
		"""Run onInstall with both dialogs stubbed, returning the config manager."""
		with patch("addon.installTasks.config") as mockConfig:
			mockConfig.conf = _makeConf()
			baseProfile = mockConfig.conf.profiles[0]
			brailleSection = dict(baseBraille) if baseBraille else {}
			if baseExcluded is not None:
				brailleSection["auto"] = {"excludedDisplays": list(baseExcluded)}
			if brailleSection:
				baseProfile["braille"] = brailleSection
			if promptsShown is not None:
				baseProfile[installTasks.CONFIG_SECTION_NAME] = dict(promptsShown)
			if activeProfile is not None:
				_activateProfile(mockConfig.conf, activeProfile)
			with (
				patch("addon.installTasks._askEnableAutomaticDetection") as mockAskDetect,
				patch("addon.installTasks._askDisableCursorBlink") as mockAskBlink,
			):
				mockAskDetect.side_effect = detectAnswer if callable(detectAnswer) else lambda: detectAnswer
				mockAskBlink.side_effect = blinkAnswer if callable(blinkAnswer) else lambda: blinkAnswer
				installTasks.onInstall()
				self.mockAskDetect = mockAskDetect
				self.mockAskBlink = mockAskBlink
			return mockConfig.conf

	# Automatic detection

	def test_yes_enablesDetectionAndMarksPromptShown(self) -> None:
		conf = self._run(baseExcluded=["dotPad", "someOtherDisplay"])
		baseProfile = conf.profiles[0]
		self.assertEqual(baseProfile["braille"]["auto"]["excludedDisplays"], ["someOtherDisplay"])
		self.assertTrue(baseProfile["dotPad"][AUTO_DETECT_FLAG])

	def test_yes_isVisibleToTheRunningSession(self) -> None:
		# The braille settings dialog re-saves this list on OK, so a stale aggregated
		# value would write the exclusion straight back before NVDA restarts.
		conf = self._run()
		self.assertEqual(conf["braille"]["auto"]["excludedDisplays"], [])

	def test_no_leavesExclusionListAloneButMarksPromptShown(self) -> None:
		conf = self._run(detectAnswer=False)
		self.assertEqual(conf.profiles[0]["braille"]["auto"]["excludedDisplays"], ["dotPad"])
		self.assertTrue(conf.profiles[0]["dotPad"][AUTO_DETECT_FLAG])

	def test_doesNotAskWhenDetectionAlreadyEnabled(self) -> None:
		conf = self._run(baseExcluded=["someOtherDisplay"])
		self.mockAskDetect.assert_not_called()
		self.assertEqual(conf.profiles[0]["braille"]["auto"]["excludedDisplays"], ["someOtherDisplay"])
		self.assertTrue(conf.profiles[0]["dotPad"][AUTO_DETECT_FLAG])

	def test_asksEvenIfAnActiveProfileAlreadyEnabledDetection(self) -> None:
		# Detection being enabled in one profile says nothing about the base profile,
		# which is where the answer is stored.
		conf = self._run(activeProfile={"braille": {"auto": {"excludedDisplays": []}}})
		self.mockAskDetect.assert_called_once()
		self.assertEqual(conf.profiles[0]["braille"]["auto"]["excludedDisplays"], [])

	def test_doesNotCopyActiveProfileExclusionsIntoBaseProfile(self) -> None:
		conf = self._run(
			baseExcluded=None,
			activeProfile={"braille": {"auto": {"excludedDisplays": ["brailliantB", "dotPad"]}}},
		)
		self.assertEqual(conf.profiles[0]["braille"]["auto"]["excludedDisplays"], [])

	# Cursor blinking

	def test_yes_stopsTheCursorBlinkingAndMarksPromptShown(self) -> None:
		conf = self._run(blinkAnswer=True)
		baseProfile = conf.profiles[0]
		self.assertFalse(baseProfile["braille"]["cursorBlink"])
		self.assertTrue(baseProfile["dotPad"][CURSOR_BLINK_FLAG])

	def test_yes_blinkIsVisibleToTheRunningSession(self) -> None:
		# As with the exclusion list, the braille settings dialog re-saves this on OK.
		conf = self._run(blinkAnswer=True)
		self.assertFalse(conf["braille"]["cursorBlink"])

	def test_no_leavesBlinkingAloneButMarksPromptShown(self) -> None:
		conf = self._run(blinkAnswer=False)
		self.assertNotIn("cursorBlink", conf.profiles[0]["braille"])
		self.assertTrue(conf.profiles[0]["dotPad"][CURSOR_BLINK_FLAG])

	def test_doesNotAskWhenBlinkingAlreadyOff(self) -> None:
		conf = self._run(blinkAnswer=True, baseBraille={"cursorBlink": "False"})
		self.mockAskBlink.assert_not_called()
		self.assertFalse(installTasks._isTrue(conf.profiles[0]["braille"]["cursorBlink"]))
		self.assertTrue(conf.profiles[0]["dotPad"][CURSOR_BLINK_FLAG])

	def test_asksEvenIfAnActiveProfileAlreadyStoppedBlinking(self) -> None:
		# Blinking being off in one profile says nothing about the base profile, which
		# is where the answer is stored.
		conf = self._run(blinkAnswer=True, activeProfile={"braille": {"cursorBlink": False}})
		self.mockAskBlink.assert_called_once()
		self.assertFalse(conf.profiles[0]["braille"]["cursorBlink"])

	# Both questions

	def test_bothQuestionsAreAskedOnAFreshInstall(self) -> None:
		self._run()
		self.mockAskDetect.assert_called_once()
		self.mockAskBlink.assert_called_once()

	def test_doesNotAskEitherQuestionAgainOnceBothShown(self) -> None:
		conf = self._run(
			baseExcluded=None,
			promptsShown={AUTO_DETECT_FLAG: "True", CURSOR_BLINK_FLAG: "True"},
		)
		self.mockAskDetect.assert_not_called()
		self.mockAskBlink.assert_not_called()
		self.assertNotIn("braille", conf.profiles[0])

	def test_theQuestionsAreIndependent(self) -> None:
		# An add-on installed before the blinking question existed has only the
		# detection flag, so that question stays settled while this one is asked.
		conf = self._run(
			blinkAnswer=True,
			baseExcluded=None,
			promptsShown={AUTO_DETECT_FLAG: "True"},
		)
		self.mockAskDetect.assert_not_called()
		self.mockAskBlink.assert_called_once()
		self.assertFalse(conf.profiles[0]["braille"]["cursorBlink"])
		self.assertNotIn("auto", conf.profiles[0]["braille"])

	def test_dialogFailureIsSwallowed(self) -> None:
		def boom():
			raise RuntimeError("no gui")

		# Must not propagate: an exception from onInstall rolls back the installation.
		conf = self._run(detectAnswer=boom)
		self.assertNotIn("dotPad", conf.profiles[0])

	def test_blinkDialogFailureIsSwallowed(self) -> None:
		def boom():
			raise RuntimeError("no gui")

		conf = self._run(blinkAnswer=boom)
		# The question that was answered first still stands; only the failed one is
		# left unsettled, to be asked again on the next install.
		self.assertTrue(conf.profiles[0]["dotPad"][AUTO_DETECT_FLAG])
		self.assertNotIn(CURSOR_BLINK_FLAG, conf.profiles[0]["dotPad"])


if __name__ == "__main__":
	unittest.main()
