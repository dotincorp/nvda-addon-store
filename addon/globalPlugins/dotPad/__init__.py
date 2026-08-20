# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2026 Dot Incorporated

from concurrent.futures import Future
from typing import TYPE_CHECKING, Callable

import addonHandler
import api
import braille
import config
import globalPluginHandler
import gui
import wx
from gui import blockAction
from logHandler import log
from NVDAObjects import NVDAObject

from . import settingsPanel

if TYPE_CHECKING:
	from ... import configuration
	from ...ble.detection import Detector
	from ...brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver
	from ...extension_points.review_tracking import (
		navigatorObjectValueChange,
	)

	addon: addonHandler.Addon
	bleDetector: Detector
else:
	from brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver  # noqa: F401

	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	configuration = addon.loadModule("configuration")

	extension_points = addon.loadModule("extension_points.review_tracking")
	navigatorObjectValueChange = extension_points.navigatorObjectValueChange

	# Unguarded: the driver import above already pulls in bleak and ble.detection, so
	# this module cannot load at all on a platform without a bleak build.
	bleDetector = addon.loadModule("ble.detection").detector

addonHandler.initTranslation()


class DotPadGlobalPlugin(globalPluginHandler.GlobalPlugin):
	def event_valueChange(self, obj: NVDAObject, nextHandler: Callable[[], None]) -> None:
		navObj = api.getNavigatorObject()
		if obj == navObj:
			navigatorObjectValueChange.notify()
		nextHandler()

	#: The Tools-menu check item created in :meth:`_appendViewerMenuItem`. Held so
	#: :meth:`terminate` can ``Remove`` it cleanly. ``None`` until ``__init__``
	#: completes and again after ``terminate``.
	_showBrailleOnScreenItem: "wx.MenuItem | None" = None

	def __init__(self):
		super().__init__()
		# A new plugin instance means NVDA is running, not shutting down. Clears the
		# latch terminate() sets, so reloading plugins (NVDA+Ctrl+F3) does not leave BLE
		# detection switched off for the rest of the session.
		bleDetector.resume()
		configuration.initializeConfig()
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(settingsPanel.DotPadSettingsPanel)
		settingsPanel.DotPadSettingsPanel.post_onSave.register(self.onAutoRefreshChange)
		config.post_configProfileSwitch.register(self.onAutoRefreshChange)
		self._appendViewerMenuItem()

	def terminate(self):
		# First, and before any of the GUI cleanup that could raise: this is the only
		# hook that runs while NVDA's asyncio event loop is still alive. NVDA calls it
		# from core._handleNVDAModuleCleanupBeforeGUIExit(), whereas the loop closes much
		# later in _terminate(_asyncioEventLoop). A BLE scan left running past that point
		# keeps a WinRT advertisement watcher posting to a closed loop, which floods the
		# log with "RuntimeError: Event loop is closed" for every advertisement in range.
		bleDetector.terminate()
		super().terminate()
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(settingsPanel.DotPadSettingsPanel)
		settingsPanel.DotPadSettingsPanel.post_onSave.unregister(self.onAutoRefreshChange)
		config.post_configProfileSwitch.unregister(self.onAutoRefreshChange)
		if self._showBrailleOnScreenItem is not None:
			assert gui.mainFrame is not None  # NVDA startup invariant.
			toolsMenu = gui.mainFrame.sysTrayIcon.toolsMenu
			toolsMenu.Remove(self._showBrailleOnScreenItem.Id)
			self._showBrailleOnScreenItem.Destroy()
			self._showBrailleOnScreenItem = None

	def _appendViewerMenuItem(self) -> None:
		"""Append the "Dot Pad display viewer" check item to NVDA's Tools menu.

		Pattern matches NVDA's own Braille Viewer entry: ``AppendCheckItem``
		on ``gui.mainFrame.sysTrayIcon.toolsMenu``, bound via the tray icon's
		``EVT_MENU`` event. Initial check state syncs to the persisted
		``viewerOnScreen`` config flag so the menu reflects state from
		prior NVDA sessions.
		"""
		assert gui.mainFrame is not None  # NVDA startup invariant.
		sysTrayIcon = gui.mainFrame.sysTrayIcon
		toolsMenu = sysTrayIcon.toolsMenu
		self._showBrailleOnScreenItem = toolsMenu.AppendCheckItem(
			wx.ID_ANY,
			# Translators: Tools-menu item to toggle the bundled library's on-screen viewer.
			_("&Dot Pad display viewer"),
		)
		self._showBrailleOnScreenItem.Check(configuration.getViewerOnScreen())
		sysTrayIcon.Bind(
			wx.EVT_MENU,
			self.onToggleShowBrailleOnScreen,
			self._showBrailleOnScreenItem,
		)

	def _getActiveDotPadDriver(self) -> "BrailleDisplayDriver | None":
		"""Return the active DotPad driver, or None if a different display is active."""
		if not braille.handler:
			return None
		display = braille.handler.display
		if isinstance(display, BrailleDisplayDriver):
			return display
		return None

	@blockAction.when(blockAction.Context.SECURE_MODE)
	def onToggleShowBrailleOnScreen(self, event: wx.CommandEvent) -> None:
		"""Handle the Tools-menu toggle click.

		Reads the new check state from the wx event, persists it to config,
		and refreshes the cache. If a DotPad driver is active and its library
		worker is ready, submits the library call as fire-and-forget.

		When no DotPad driver is active, the config write is the only side
		effect — the library will be synced when a DotPad next initializes.
		"""
		newChecked = event.IsChecked()
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.VIEWER_ON_SCREEN_SETTING_NAME
		] = newChecked
		configuration.updateConfigCache()
		driver = self._getActiveDotPadDriver()
		if driver is None:
			return
		if not driver._libraryReady:  # pyright: ignore[reportPrivateUsage]
			return
		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			log.debugWarning("dotPad: library ready but worker / wrapper missing; viewer call skipped")
			return
		future = worker.submit(tda.showBrailleOnScreen, newChecked)
		future.add_done_callback(self._onShowViewerComplete)

	def _onShowViewerComplete(self, future: "Future[None]") -> None:
		"""Report a failed fire-and-forget library viewer toggle.

		Runs on the library worker thread. Silence means the call landed.
		"""
		exc = future.exception()
		if exc is not None:
			log.warning(f"dotPad: library viewer toggle failed: {exc}")

	def _applyLineSpacing(self) -> None:
		"""Re-apply the line spacing setting to the running display and library.

		Updates ``graphicDisplay.verticalCellSpacing`` (our renderer) immediately,
		then submits the library calls as fire-and-forget. Reads the freshly-cached
		value, so callers must ``updateConfigCache()`` first. No-op when no DotPad
		driver is active or the library is not ready.
		"""
		option = configuration.getMultilineBrailleSpacing(fromCache=True)
		paddingDots, forceSixDot = configuration.LINE_SPACING_PAYLOADS[option]

		driver = self._getActiveDotPadDriver()
		if driver is not None and driver.graphicDisplay is not None:
			driver.graphicDisplay.verticalCellSpacing = paddingDots

		if driver is None:
			return
		if not driver._libraryReady:  # pyright: ignore[reportPrivateUsage]
			return
		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			log.debugWarning(
				"dotPad: library ready but worker / wrapper missing; line-spacing call skipped",
			)
			return
		worker.submit(tda.setBrailleLinePadding, paddingDots)
		worker.submit(tda.forceSixDotBraille, forceSixDot)

	def _applyHybridPrintAndBraille(self) -> None:
		"""Re-apply the persisted hybrid print+braille setting to the running library.

		Fire-and-forget on the library worker (no main-thread block), guarded like
		``onToggleShowBrailleOnScreen``. No-op when no DotPad driver is active or the
		library is not ready — the value is applied on the next driver init instead.
		Reads the freshly-cached value, so callers must ``updateConfigCache()`` first.
		"""
		driver = self._getActiveDotPadDriver()
		if driver is None:
			return
		if not driver._libraryReady:  # pyright: ignore[reportPrivateUsage]
			return
		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			log.debugWarning("dotPad: library ready but worker / wrapper missing; hybrid mode call skipped")
			return
		enable = configuration.getHybridPrintAndBraille(fromCache=True)
		worker.submit(tda.setHybridPrintAndBrailleMode, enable)

	def onAutoRefreshChange(self):
		# Update configuration cache when settings are saved
		configuration.updateConfigCache()

		# Re-apply the hybrid print+braille setting to the running library (live on save).
		self._applyHybridPrintAndBraille()
		# Re-apply the line spacing setting (live on save).
		self._applyLineSpacing()

		if not braille.handler or not isinstance(braille.handler.display, BrailleDisplayDriver):
			return
		driver = braille.handler.display
		if driver.textDisplay:
			driver.textDisplay.autoRefresh = bool(
				configuration.getAutoRefresh() & configuration.AutoRefresh.TEXT,
			)
		if driver.graphicDisplay:
			driver.graphicDisplay.autoRefresh = bool(
				configuration.getAutoRefresh() & configuration.AutoRefresh.GRAPHIC,
			)


GlobalPlugin = DotPadGlobalPlugin
