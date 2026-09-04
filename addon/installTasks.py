# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Install tasks for the Dot Pad add-on.

NVDA excludes the ``dotPad`` driver from automatic braille display detection by
default, so a user who selects the "Automatic" display never gets a Dot Pad
detected until they find the "Displays to detect automatically" list in NVDA's
braille settings. On install we offer to enable it for them, once.
"""

from typing import Any, cast

import addonHandler
import config
from logHandler import log

try:
	from .utils.testing import IS_UNDER_UNITTEST
except ImportError:
	IS_UNDER_UNITTEST = False  # type: ignore

if not IS_UNDER_UNITTEST:
	addonHandler.initTranslation()

DRIVER_NAME = "dotPad"
# Duplicated rather than imported from .configuration: during onInstall this add-on
# lives at <addons>\dotPad.pendingInstall while the previous version may still be
# loaded, so importing add-on modules here risks resolving to the old copy.
CONFIG_SECTION_NAME = "dotPad"
AUTO_DETECT_PROMPT_SHOWN_SETTING_NAME = "autoDetectPromptShown"

_TRUE_VALUES = frozenset(("true", "yes", "on", "1"))


def _isTrue(value: Any) -> bool:
	"""Interpret a raw config value as a boolean.

	Values read straight from a profile are unvalidated strings, because the add-on's
	config spec is only registered once the add-on itself loads.
	"""
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.strip().lower() in _TRUE_VALUES
	return bool(value)


def _promptAlreadyShown(baseProfile: Any) -> bool:
	"""Whether the automatic detection question has been asked before."""
	try:
		return _isTrue(baseProfile[CONFIG_SECTION_NAME][AUTO_DETECT_PROMPT_SHOWN_SETTING_NAME])
	except KeyError:
		return False


def _markPromptShown(baseProfile: Any) -> None:
	"""Record that the question has been asked, creating the section if needed."""
	if CONFIG_SECTION_NAME not in baseProfile:
		baseProfile[CONFIG_SECTION_NAME] = {}
	baseProfile[CONFIG_SECTION_NAME][AUTO_DETECT_PROMPT_SHOWN_SETTING_NAME] = True


def _withoutDriver(excludedDisplays: list[str]) -> list[str]:
	"""The given exclusion list without our driver."""
	return [name for name in excludedDisplays if name != DRIVER_NAME]


def _asList(value: Any) -> list[str]:
	"""A raw config value coerced to a list of strings.

	A one-element list in an ini file reads back as a plain string if it was written
	without a trailing comma, e.g. by hand.
	"""
	if isinstance(value, str):
		return [value]
	return [str(item) for item in cast("list[Any]", value)]


def _getSpecDefaultExcludedDisplays() -> list[str]:
	"""The list of excluded displays NVDA's config spec defaults to."""
	try:
		spec = cast(Any, config.conf.spec)["braille"]["auto"]["excludedDisplays"]
		return _asList(config.conf.validator.get_default_value(spec))
	except KeyError:
		return []


def _getExcludedDisplays(baseProfile: Any) -> list[str]:
	"""The base profile's list of displays excluded from automatic detection.

	The base profile is read rather than ``config.conf`` because that is also where
	the change is written: an active configuration profile may carry its own list,
	which says nothing about what the base profile excludes.
	"""
	try:
		return _asList(baseProfile["braille"]["auto"]["excludedDisplays"])
	except KeyError:
		# The base profile leaves the setting at its default.
		return _getSpecDefaultExcludedDisplays()


def _enableAutomaticDetection(baseProfile: Any, excludedDisplays: list[str]) -> None:
	"""Remove our driver from the base profile's list of excluded displays.

	The base profile is written rather than ``config.conf`` so the change applies
	regardless of which configuration profile happens to be active during install.
	"""
	brailleSection = baseProfile.setdefault("braille", {})
	autoSection = brailleSection.setdefault("auto", {})
	autoSection["excludedDisplays"] = _withoutDriver(excludedDisplays)


def _refreshAggregatedConfig() -> None:
	"""Make the running session see a value written straight into a profile.

	``config.conf`` caches the values it aggregates from the active profiles, and a
	write that bypasses it leaves that cache stale. Anything re-saving the setting
	before NVDA restarts — the braille settings dialog does exactly that on OK —
	would otherwise write the old list straight back.
	"""
	# Rebuilding the aggregated config is what NVDA itself does after a profile
	# change; nothing is notified, because no profile was actually switched.
	config.conf._handleProfileSwitch(shouldNotify=False)  # type: ignore[reportPrivateUsage]


def _askUser() -> bool:
	"""Ask whether automatic detection of the Dot Pad should be enabled."""
	# Imported here so this module stays importable outside a running NVDA.
	from gui.guiHelper import wxCallOnMain
	from gui.message import DefaultButton, MessageDialog, ReturnCode

	message = _(
		# Translators: Message of the dialog shown when installing the add-on,
		# asking whether NVDA should detect Dot Pad displays automatically.
		"NVDA does not detect Dot Pad displays automatically by default. "
		"Do you want to enable automatic detection of the Dot Pad?\n"
		"You can change this later in NVDA's braille settings.",
	)
	# Translators: Title of the dialog shown when installing the add-on.
	title = _("Dot Pad")

	def showDialog() -> int:
		# MessageDialog must be created as well as shown on the main thread, so both
		# happen inside this callable.
		return MessageDialog(
			None,
			message,
			title,
			buttons=(DefaultButton.YES, DefaultButton.NO),
		).ShowModal()

	return wxCallOnMain(showDialog) == ReturnCode.YES


def onInstall() -> None:
	# An exception raised here aborts and rolls back the installation, so nothing
	# in this task may propagate.
	try:
		baseProfile = config.conf.profiles[0]
		if _promptAlreadyShown(baseProfile):
			return
		excludedDisplays = _getExcludedDisplays(baseProfile)
		if DRIVER_NAME in excludedDisplays and _askUser():
			_enableAutomaticDetection(baseProfile, excludedDisplays)
		# If our driver was not excluded to begin with, automatic detection is already
		# enabled and the user was not asked; either way the question is now settled.
		_markPromptShown(baseProfile)
		_refreshAggregatedConfig()
		# Not saved here on purpose: NVDA writes the configuration on exit, or when
		# the user saves it manually.
	except Exception:
		log.exception("Error asking whether to enable automatic detection of the Dot Pad")
