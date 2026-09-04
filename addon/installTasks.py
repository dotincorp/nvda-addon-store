# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Install tasks for the Dot Pad add-on.

NVDA excludes the ``dotPad`` driver from automatic braille display detection by
default, so a user who selects the "Automatic" display never gets a Dot Pad
detected until they find the "Displays to detect automatically" list in NVDA's
braille settings. On install we offer to enable it for them, once.

NVDA also blinks the braille cursor by default. Dot Pad cells refresh slowly, and
not reliably at all while they are being touched, so a blinking cursor is of
little use on one. Blinking is a single global setting rather than a per-display
one, so this too can only be offered as a question, once.
"""

from typing import Any, cast

import addonHandler
import config
from configobj.validate import Validator, VdtTypeError
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
CURSOR_BLINK_PROMPT_SHOWN_SETTING_NAME = "cursorBlinkPromptShown"

_VALIDATOR = Validator()


def _isTrue(value: Any) -> bool:
	"""Interpret a value read straight out of a profile as a boolean.

	Values in our own config section are still the raw strings ConfigObj parsed: the
	spec that would coerce them is only registered once the add-on loads, which has
	not happened yet during ``onInstall``. Since ``bool("False")`` is ``True``, they
	cannot be taken at face value. The interpreting is left to ConfigObj's own
	validator, so the spellings accepted here are the ones accepted everywhere else
	in the configuration.
	"""
	try:
		return bool(_VALIDATOR.check("boolean", value))
	except VdtTypeError:
		return False


def _promptAlreadyShown(baseProfile: Any, settingName: str) -> bool:
	"""Whether the question recorded under the given setting has been asked before."""
	try:
		return _isTrue(baseProfile[CONFIG_SECTION_NAME][settingName])
	except KeyError:
		return False


def _markPromptShown(baseProfile: Any, settingName: str) -> None:
	"""Record that a question has been asked, creating the section if needed."""
	if CONFIG_SECTION_NAME not in baseProfile:
		baseProfile[CONFIG_SECTION_NAME] = {}
	baseProfile[CONFIG_SECTION_NAME][settingName] = True


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


def _getSpecDefault(*path: str) -> Any:
	"""The value NVDA's config spec defaults the setting at the given path to.

	``None`` if the spec carries no such setting, which only happens if NVDA renames
	or drops it; callers decide what that should mean for them.
	"""
	try:
		spec = cast(Any, config.conf.spec)
		for key in path:
			spec = spec[key]
		return cast("Any", config.conf.validator.get_default_value(spec))
	except KeyError:
		return None


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
		default = _getSpecDefault("braille", "auto", "excludedDisplays")
		return [] if default is None else _asList(default)


def _getCursorBlink(baseProfile: Any) -> bool:
	"""Whether the base profile has NVDA blinking the braille cursor.

	The base profile is read rather than ``config.conf`` for the same reason as in
	:func:`_getExcludedDisplays`: it is where the answer is written.
	"""
	try:
		return _isTrue(baseProfile["braille"]["cursorBlink"])
	except KeyError:
		# The base profile leaves the setting at its default. A spec that no longer
		# carries the setting must not read as "already off", because that would
		# silently skip the question, and it is only asked once.
		default = _getSpecDefault("braille", "cursorBlink")
		return True if default is None else _isTrue(default)


def _enableAutomaticDetection(baseProfile: Any, excludedDisplays: list[str]) -> None:
	"""Remove our driver from the base profile's list of excluded displays.

	The base profile is written rather than ``config.conf`` so the change applies
	regardless of which configuration profile happens to be active during install.
	"""
	brailleSection = baseProfile.setdefault("braille", {})
	autoSection = brailleSection.setdefault("auto", {})
	autoSection["excludedDisplays"] = _withoutDriver(excludedDisplays)


def _disableCursorBlink(baseProfile: Any) -> None:
	"""Stop NVDA blinking the braille cursor, on every braille display.

	Written to the base profile for the same reason as
	:func:`_enableAutomaticDetection`.
	"""
	brailleSection = baseProfile.setdefault("braille", {})
	brailleSection["cursorBlink"] = False


def _refreshAggregatedConfig() -> None:
	"""Make the running session see a value written straight into a profile.

	``config.conf`` caches the values it aggregates from the active profiles, and a
	write that bypasses it leaves that cache stale. Anything re-saving the setting
	before NVDA restarts — the braille settings dialog does exactly that on OK —
	would otherwise write the old value straight back.
	"""
	# Rebuilding the aggregated config is what NVDA itself does after a profile
	# change; nothing is notified, because no profile was actually switched.
	config.conf._handleProfileSwitch(shouldNotify=False)  # type: ignore[reportPrivateUsage]


def _ask(message: str, title: str) -> bool:
	"""Put a yes/no question to the user, returning whether they answered yes."""
	# Imported here so this module stays importable outside a running NVDA.
	from gui.guiHelper import wxCallOnMain
	from gui.message import DefaultButton, MessageDialog, ReturnCode

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


def _askEnableAutomaticDetection() -> bool:
	"""Ask whether automatic detection of the Dot Pad should be enabled."""
	message = _(
		# Translators: Message of the dialog shown when installing the add-on,
		# asking whether NVDA should detect Dot Pad displays automatically.
		"NVDA does not detect Dot Pad displays automatically by default. "
		"Do you want to enable automatic detection of the Dot Pad?\n"
		"You can change this later in NVDA's braille settings.",
	)
	# Translators: Title of the dialog shown when installing the add-on, asking
	# whether NVDA should detect Dot Pad displays automatically.
	title = _("Dot Pad: automatic detection")
	return _ask(message, title)


def _askDisableCursorBlink() -> bool:
	"""Ask whether NVDA's blinking braille cursor should be turned off."""
	message = _(
		# Translators: Message of the dialog shown when installing the add-on,
		# asking whether NVDA should stop blinking the braille cursor.
		"Dot Pad cells refresh slowly, so a blinking braille cursor does not work well. "
		"Do you want to turn the blinking cursor off?\n"
		"This applies to all braille displays. "
		"You can change this later in NVDA's braille settings.",
	)
	# Translators: Title of the dialog shown when installing the add-on, asking
	# whether NVDA should stop blinking the braille cursor.
	title = _("Dot Pad: blinking cursor")
	return _ask(message, title)


def _offerAutomaticDetection(baseProfile: Any) -> None:
	"""Ask, once, whether to enable automatic detection of the Dot Pad."""
	if _promptAlreadyShown(baseProfile, AUTO_DETECT_PROMPT_SHOWN_SETTING_NAME):
		return
	excludedDisplays = _getExcludedDisplays(baseProfile)
	if DRIVER_NAME in excludedDisplays and _askEnableAutomaticDetection():
		_enableAutomaticDetection(baseProfile, excludedDisplays)
	# If our driver was not excluded to begin with, automatic detection is already
	# enabled and the user was not asked; either way the question is now settled.
	_markPromptShown(baseProfile, AUTO_DETECT_PROMPT_SHOWN_SETTING_NAME)


def _offerDisableCursorBlink(baseProfile: Any) -> None:
	"""Ask, once, whether to turn NVDA's blinking braille cursor off."""
	if _promptAlreadyShown(baseProfile, CURSOR_BLINK_PROMPT_SHOWN_SETTING_NAME):
		return
	if _getCursorBlink(baseProfile) and _askDisableCursorBlink():
		_disableCursorBlink(baseProfile)
	# If the cursor was not blinking to begin with, the user was not asked; either
	# way the question is now settled.
	_markPromptShown(baseProfile, CURSOR_BLINK_PROMPT_SHOWN_SETTING_NAME)


def onInstall() -> None:
	# An exception raised here aborts and rolls back the installation, so nothing
	# in this task may propagate.
	try:
		baseProfile = config.conf.profiles[0]
		_offerAutomaticDetection(baseProfile)
		_offerDisableCursorBlink(baseProfile)
		_refreshAggregatedConfig()
		# Not saved here on purpose: NVDA writes the configuration on exit, or when
		# the user saves it manually.
	except Exception:
		log.exception("Error asking the Dot Pad installation questions")
