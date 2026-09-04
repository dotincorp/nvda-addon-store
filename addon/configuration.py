# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

from enum import unique
from threading import RLock
from typing import Any

import addonHandler
import config
from utils.displayString import DisplayStringIntEnum, DisplayStringIntFlag

try:
	from .utils.testing import IS_UNDER_UNITTEST
except ImportError:
	IS_UNDER_UNITTEST = False  # type: ignore

if not IS_UNDER_UNITTEST:
	addonHandler.initTranslation()

_cachedConfig: dict[str, Any] = {}
_configLock = RLock()
"Lock for accessing the config"


@unique
class AutoRefresh(DisplayStringIntFlag):
	TEXT = 0x1
	GRAPHIC = 0x2

	@property
	def _displayStringLabels(self):  # type: ignore
		return {
			AutoRefresh.TEXT: _("Single Line Text Display"),
			AutoRefresh.GRAPHIC: _("Graphic/Multi Line Text Display"),
		}


@unique
class TableNavigatorAfterScroll(DisplayStringIntEnum):
	"""Defines behavior for navigator object after table scroll."""

	DO_NOTHING = 0
	FIRST_CELL = 1
	CENTER_CELL = 2

	@property
	def _displayStringLabels(self):  # type: ignore
		return {
			# Translators: Choice option for not moving navigator after scroll
			TableNavigatorAfterScroll.DO_NOTHING: _("Do nothing"),
			# Translators: Choice option for moving to first visible cell
			TableNavigatorAfterScroll.FIRST_CELL: _("Move to first visible cell"),
			# Translators: Choice option for moving to center cell
			TableNavigatorAfterScroll.CENTER_CELL: _("Move to center cell"),
		}


@unique
class BrailleSource(DisplayStringIntEnum):
	"""Selects the source that drives the multi-line braille area.

	``NVDA`` is the existing behaviour — the addon's ``BraillePresentation``
	reads NVDA's review/navigator state and writes braille cells via liblouis.
	Follows the navigator, supports review-mode exploration.

	``LIBRARY`` opts into the bundled TactileDisplayAPI's autonomous rendering
	path — the library tracks UIA/MSAA events via ``RegisterEvents(true)`` and
	emits braille bytes via the ``TactileDisplayUpdated`` callback. Library
	mode follows the focused control only; review-mode exploration is not
	supported. The 20-cell text strip stays NVDA-driven in both modes.
	"""

	NVDA = 0
	LIBRARY = 1

	@property
	def _displayStringLabels(self):  # type: ignore
		return {
			# Translators: Choice option for the existing NVDA-driven braille rendering.
			BrailleSource.NVDA: _("NVDA review cursor (multi-line follows navigator)"),
			# Translators: Choice option for the TactileDisplayAPI library-driven braille rendering.
			BrailleSource.LIBRARY: _("TactileDisplayAPI library (follows focused control)"),
		}


@unique
class LineSpacingOption(DisplayStringIntEnum):
	"""Line spacing option for the multi-line tactile braille area.

	Each option maps to a ``(paddingDots, forceSixDot)`` pair; see
	``LINE_SPACING_PAYLOADS``. ``ForceSixDotBraille`` is library-only —
	our own renderer always uses 8-dot cells regardless of this setting.
	"""

	AUTO = 0
	MAX_LINE_COUNT = 1
	DOUBLE_LINE_SPACING = 2

	@property
	def _displayStringLabels(self):  # type: ignore
		return {
			# Translators: Line spacing option — maximum lines, 8-dot braille.
			LineSpacingOption.AUTO: _("Auto (maximum lines, 8-dot braille)"),
			# Translators: Line spacing option — force six-dot braille for more lines (library mode only).
			LineSpacingOption.MAX_LINE_COUNT: _("Max Line Count (six-dot braille, library mode only)"),
			# Translators: Line spacing option — wider gaps between braille lines.
			LineSpacingOption.DOUBLE_LINE_SPACING: _("Double Line Spacing (8-dot braille)"),
		}


LINE_SPACING_PAYLOADS: dict["LineSpacingOption", tuple[int, bool]] = {
	LineSpacingOption.AUTO: (1, False),
	LineSpacingOption.MAX_LINE_COUNT: (1, True),
	LineSpacingOption.DOUBLE_LINE_SPACING: (3, False),
}
"""Maps each :class:`LineSpacingOption` to ``(paddingDots, forceSixDot)``."""


CONFIG_SECTION_NAME: str = addonHandler.getCodeAddon().name  # type: ignore
AUTO_REFRESH_SETTING_NAME = "autoRefresh"
AUTO_REFRESH_IDLE_TIMEOUT_SETTING_NAME = "autoRefreshIdleTimeout"
AUTO_REFRESH_INTERVAL_SETTING_NAME = "autoRefreshInterval"
SCREEN_CAPTURE_MAX_LINES_PER_OBJECT_SETTING_NAME = "screenCaptureMaxLinesPerObject"
SCREEN_CAPTURE_SHOW_OBJECT_NUMBERS_SETTING_NAME = "screenCaptureShowObjectNumbers"
TABLE_NAVIGATOR_AFTER_SCROLL_SETTING_NAME = "tableNavigatorAfterScroll"
BRAILLE_SOURCE_SETTING_NAME = "brailleSource"
VIEWER_ON_SCREEN_SETTING_NAME = "viewerOnScreen"
USE_SYSTEM_LIBRARY_SETTING_NAME = "useSystemLibrary"
HYBRID_PRINT_AND_BRAILLE_SETTING_NAME = "hybridPrintAndBraille"
MULTILINE_BRAILLE_SPACING_SETTING_NAME = "multilineBrailleSpacing"
# Written by installTasks.onInstall; see addon/installTasks.py.
AUTO_DETECT_PROMPT_SHOWN_SETTING_NAME = "autoDetectPromptShown"
CURSOR_BLINK_PROMPT_SHOWN_SETTING_NAME = "cursorBlinkPromptShown"

CONFIG_SPEC = {
	AUTO_REFRESH_SETTING_NAME: "integer(default=3, min=0, max=3)",
	AUTO_REFRESH_IDLE_TIMEOUT_SETTING_NAME: "float(default=2.0, min=0.5, max=10.0)",
	AUTO_REFRESH_INTERVAL_SETTING_NAME: "float(default=2.0, min=0.5, max=10.0)",
	SCREEN_CAPTURE_MAX_LINES_PER_OBJECT_SETTING_NAME: "integer(default=1, min=1, max=5)",
	SCREEN_CAPTURE_SHOW_OBJECT_NUMBERS_SETTING_NAME: "boolean(default=True)",
	TABLE_NAVIGATOR_AFTER_SCROLL_SETTING_NAME: "integer(default=0, min=0, max=2)",
	BRAILLE_SOURCE_SETTING_NAME: "integer(default=1, min=0, max=1)",
	VIEWER_ON_SCREEN_SETTING_NAME: "boolean(default=False)",
	USE_SYSTEM_LIBRARY_SETTING_NAME: "boolean(default=False)",
	HYBRID_PRINT_AND_BRAILLE_SETTING_NAME: "boolean(default=False)",
	MULTILINE_BRAILLE_SPACING_SETTING_NAME: "integer(default=0, min=0, max=2)",
	AUTO_DETECT_PROMPT_SHOWN_SETTING_NAME: "boolean(default=False)",
	CURSOR_BLINK_PROMPT_SHOWN_SETTING_NAME: "boolean(default=False)",
}


def _getSetting(setting: str, fromCache: bool) -> Any:
	with _configLock:
		if not initialized:
			initializeConfig()

		section: dict[str, Any] = _cachedConfig if fromCache else config.conf[CONFIG_SECTION_NAME]  # type: ignore
		return section[setting]


def getAutoRefresh(fromCache: bool = False) -> AutoRefresh:
	return AutoRefresh(int(_getSetting(AUTO_REFRESH_SETTING_NAME, fromCache)))


def getAutoRefreshIdleTimeout(fromCache: bool = False) -> float:
	return float(_getSetting(AUTO_REFRESH_IDLE_TIMEOUT_SETTING_NAME, fromCache))


def getAutoRefreshInterval(fromCache: bool = False) -> float:
	return float(_getSetting(AUTO_REFRESH_INTERVAL_SETTING_NAME, fromCache))


def getScreenCaptureMaxLinesPerObject(fromCache: bool = False) -> int:
	return int(_getSetting(SCREEN_CAPTURE_MAX_LINES_PER_OBJECT_SETTING_NAME, fromCache))


def getScreenCaptureShowObjectNumbers(fromCache: bool = False) -> bool:
	return bool(_getSetting(SCREEN_CAPTURE_SHOW_OBJECT_NUMBERS_SETTING_NAME, fromCache))


def getTableNavigatorAfterScroll(fromCache: bool = False) -> TableNavigatorAfterScroll:
	return TableNavigatorAfterScroll(int(_getSetting(TABLE_NAVIGATOR_AFTER_SCROLL_SETTING_NAME, fromCache)))


def getBrailleSource(fromCache: bool = False) -> BrailleSource:
	return BrailleSource(int(_getSetting(BRAILLE_SOURCE_SETTING_NAME, fromCache)))


def getViewerOnScreen(fromCache: bool = False) -> bool:
	return bool(_getSetting(VIEWER_ON_SCREEN_SETTING_NAME, fromCache))


def getUseSystemLibrary(fromCache: bool = False) -> bool:
	return bool(_getSetting(USE_SYSTEM_LIBRARY_SETTING_NAME, fromCache))


def getHybridPrintAndBraille(fromCache: bool = False) -> bool:
	return bool(_getSetting(HYBRID_PRINT_AND_BRAILLE_SETTING_NAME, fromCache))


def getMultilineBrailleSpacing(fromCache: bool = False) -> LineSpacingOption:
	try:
		return LineSpacingOption(int(_getSetting(MULTILINE_BRAILLE_SPACING_SETTING_NAME, fromCache)))
	except ValueError:
		return LineSpacingOption.AUTO


initialized: bool = False


def initializeConfig():
	with _configLock:
		global initialized

		if initialized:
			return
		if CONFIG_SECTION_NAME not in config.conf:
			config.conf[CONFIG_SECTION_NAME] = {}
		config.conf[CONFIG_SECTION_NAME].spec.update(CONFIG_SPEC)  # type: ignore
		updateConfigCache()
		initialized = True


def updateConfigCache():
	global _cachedConfig
	_cachedConfig = config.conf[CONFIG_SECTION_NAME].copy()  # type: ignore
