# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

import functools
import operator
from typing import TYPE_CHECKING, Callable, cast

import addonHandler
import braille
import config
import wx
from extensionPoints import Action
from gui.settingsDialogs import SettingsPanel, guiHelper, nvdaControls

if TYPE_CHECKING:
	from ... import configuration

	_: Callable[[str], str]
else:
	addon = addonHandler.getCodeAddon()
	configuration = addon.loadModule("configuration")

addonHandler.initTranslation()


def _isDotPadWithHardwareAutoRefresh() -> bool:
	"""Check if connected display is a DotPad with hardware auto-refresh.

	:returns: True if a DotPad with D3 hardware is connected, False otherwise.
	"""
	handler = braille.handler
	if handler is None or handler.display is None:
		return False
	# Check if it's our driver and has the property
	if hasattr(handler.display, "supportsHardwareBasedAutoRefresh"):
		return handler.display.supportsHardwareBasedAutoRefresh  # type: ignore
	return False


class DotPadSettingsPanel(SettingsPanel):
	# Translators: The label for the Dot Pad settings panel.
	title = _("Dot Pad")
	post_onSave = Action()

	def makeSettings(self, sizer: wx.BoxSizer | wx.StaticBoxSizer) -> None:
		sizerHelper = guiHelper.BoxSizerHelper(self, sizer=sizer)  # type: ignore

		# Translators: The label for the auto refresh settings group.
		autoRefreshGroupText = _("Auto Refresh")
		autoRefreshGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=autoRefreshGroupText)
		# autoRefreshGroupBox = autoRefreshGroupSizer.GetStaticBox()
		autoRefreshGroup = guiHelper.BoxSizerHelper(self, sizer=autoRefreshGroupSizer)  # type: ignore
		sizerHelper.addItem(autoRefreshGroup)

		# Add note for D3 hardware (shown conditionally)
		self._hasHardwareAutoRefresh = _isDotPadWithHardwareAutoRefresh()
		if self._hasHardwareAutoRefresh:
			# Translators: Note shown in settings when D3 hardware with auto-refresh is connected
			hardwareNoteText = _("Auto-refresh is handled by hardware on this device")
			hardwareNote = wx.StaticText(self, label=hardwareNoteText)
			autoRefreshGroup.addItem(hardwareNote)

		# Translators: The label for a list of check boxes in Dot Pad settings to enable auto refresh.
		autoRefreshText = _("Enable auto refresh for")
		autoRefreshChoices = [i.displayString for i in configuration.AutoRefresh]
		self.autoRefresh = list(configuration.AutoRefresh)
		self.autoRefreshList = autoRefreshGroup.addLabeledControl(
			autoRefreshText,
			nvdaControls.CustomCheckListBox,
			choices=autoRefreshChoices,
		)
		self.autoRefreshList.CheckedItems = [
			n for n, e in enumerate(configuration.AutoRefresh) if configuration.getAutoRefresh() & e
		]
		self.autoRefreshList.Select(0)

		# Translators: The label for the auto refresh idle timeout text box.
		idleTimeoutText = _("Auto refresh idle timeout (seconds)")
		self.idleTimeoutTextCtrl = autoRefreshGroup.addLabeledControl(
			idleTimeoutText,
			wx.TextCtrl,
			value=str(configuration.getAutoRefreshIdleTimeout()),
		)

		# Translators: The label for the auto refresh interval text box.
		refreshIntervalText = _("Auto refresh interval (seconds)")
		self.refreshIntervalTextCtrl = autoRefreshGroup.addLabeledControl(
			refreshIntervalText,
			wx.TextCtrl,
			value=str(configuration.getAutoRefreshInterval()),
		)

		# Translators: The label for the screen capture settings group.
		screenCaptureGroupText = _("Screen Capture Mode")
		screenCaptureGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=screenCaptureGroupText)
		screenCaptureGroupBox = screenCaptureGroupSizer.GetStaticBox()
		screenCaptureGroup = guiHelper.BoxSizerHelper(self, sizer=screenCaptureGroupSizer)  # type: ignore
		sizerHelper.addItem(screenCaptureGroup)

		# Translators: The label for the max lines per object spin control.
		maxLinesText = _("Maximum lines per object")
		self.maxLinesPerObjectSpin = screenCaptureGroup.addLabeledControl(
			maxLinesText,
			nvdaControls.SelectOnFocusSpinCtrl,
			min=1,
			max=5,
			initial=configuration.getScreenCaptureMaxLinesPerObject(),
		)

		# Translators: The label for the show object numbers checkbox.
		showObjectNumbersText = _("Show object numbers")
		self.showObjectNumbersCheckBox = screenCaptureGroup.addItem(
			wx.CheckBox(screenCaptureGroupBox, label=showObjectNumbersText),
		)
		self.showObjectNumbersCheckBox.SetValue(configuration.getScreenCaptureShowObjectNumbers())

		# Translators: The label for the table mode settings group.
		tableModeGroupText = _("Table Mode")
		tableModeGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=tableModeGroupText)
		tableModeGroup = guiHelper.BoxSizerHelper(self, sizer=tableModeGroupSizer)  # type: ignore
		sizerHelper.addItem(tableModeGroup)

		# Translators: The label for the table navigator after scroll choice.
		tableNavigatorText = _("&Move navigator after table scroll")
		tableNavigatorChoices = [e.displayString for e in configuration.TableNavigatorAfterScroll]
		self.tableNavigatorChoice = tableModeGroup.addLabeledControl(
			tableNavigatorText,
			wx.Choice,
			choices=tableNavigatorChoices,
		)
		self.tableNavigatorChoice.SetSelection(configuration.getTableNavigatorAfterScroll())

		# Translators: The label for the multi-line braille settings group.
		brailleSourceGroupText = _("Multi-line braille")
		brailleSourceGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=brailleSourceGroupText)
		brailleSourceGroupBox = brailleSourceGroupSizer.GetStaticBox()
		brailleSourceGroup = guiHelper.BoxSizerHelper(self, sizer=brailleSourceGroupSizer)  # type: ignore
		sizerHelper.addItem(brailleSourceGroup)

		# Translators: The label for the multi-line braille source choice.
		brailleSourceText = _("&Source for multi-line braille content")
		brailleSourceChoices = [e.displayString for e in configuration.BrailleSource]
		self.brailleSourceChoice = brailleSourceGroup.addLabeledControl(
			brailleSourceText,
			wx.Choice,
			choices=brailleSourceChoices,
		)
		self.brailleSourceChoice.SetSelection(configuration.getBrailleSource())
		# Translators: Tooltip describing the multi-line braille source trade-off.
		brailleSourceHelp = _(
			"Library mode follows the focused control only; review-mode "
			"exploration via the navigator is not supported in library mode. "
			"The 20-cell text strip is unchanged in both modes. Changes take "
			"effect on the next focus change or NVDA restart.",
		)
		self.brailleSourceChoice.SetToolTip(brailleSourceHelp)

		# Translators: The label for the multi-line braille line spacing choice.
		lineSpacingText = _("Multi-line braille &line spacing")
		lineSpacingChoices = [e.displayString for e in configuration.LineSpacingOption]
		self.lineSpacingChoice = brailleSourceGroup.addLabeledControl(
			lineSpacingText,
			wx.Choice,
			choices=lineSpacingChoices,
		)
		self.lineSpacingChoice.SetSelection(configuration.getMultilineBrailleSpacing())

		# Translators: The label for the hybrid print + braille checkbox.
		hybridPrintAndBrailleText = _("Show print and braille together (hybrid mode)")
		self.hybridPrintAndBrailleCheckBox = brailleSourceGroup.addItem(
			wx.CheckBox(brailleSourceGroupBox, label=hybridPrintAndBrailleText),
		)
		self.hybridPrintAndBrailleCheckBox.SetValue(configuration.getHybridPrintAndBraille())

		# Translators: The label for the advanced settings group.
		advancedGroupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Advanced"))
		advancedGroupBox = advancedGroupSizer.GetStaticBox()
		advancedGroup = guiHelper.BoxSizerHelper(self, sizer=advancedGroupSizer)  # type: ignore
		sizerHelper.addItem(advancedGroup)

		# Translators: Label for the system-library checkbox in the Advanced group.
		self.useSystemLibraryCheckBox = advancedGroup.addItem(
			wx.CheckBox(
				advancedGroupBox,
				label=_(
					"Use &system-installed TactileDisplayAPI library "
					"(falls back to bundled library if not found)",
				),
			),
		)
		self.useSystemLibraryCheckBox.SetValue(configuration.getUseSystemLibrary())

		# Disable auto-refresh controls if D3 hardware is connected
		if self._hasHardwareAutoRefresh:
			self.autoRefreshList.Enable(False)
			self.idleTimeoutTextCtrl.Enable(False)
			self.refreshIntervalTextCtrl.Enable(False)

	def isValid(self) -> bool:
		# Validate idle timeout
		try:
			idleTimeout = float(self.idleTimeoutTextCtrl.GetValue())
			if not (0.5 <= idleTimeout <= 10.0):
				wx.MessageBox(
					# Translators: This message is shown when the user enters an invalid value for the auto refresh idle timeout setting.
					_(
						"Auto refresh idle timeout must be between 0.5 and 10.0 seconds.\nYou entered: {value}",
					).format(value=idleTimeout),
					# Translators: The title of the message box shown when the user enters an invalid value for the auto refresh idle timeout setting.
					_("Invalid Setting Value"),
					wx.OK | wx.ICON_ERROR,
					self,
				)
				self.idleTimeoutTextCtrl.SetFocus()
				return False
		except ValueError:
			wx.MessageBox(
				# Translators: This message is shown when the user enters an invalid value for the auto refresh idle timeout setting.
				_("Auto refresh idle timeout must be a valid number.\nYou entered: {value}").format(
					value=self.idleTimeoutTextCtrl.GetValue(),
				),
				# Translators: The title of the message box shown when the user enters an invalid value for the auto refresh idle timeout setting.
				_("Invalid Setting Value"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			self.idleTimeoutTextCtrl.SetFocus()
			return False

		# Validate refresh interval
		try:
			refreshInterval = float(self.refreshIntervalTextCtrl.GetValue())
			if not (0.5 <= refreshInterval <= 10.0):
				wx.MessageBox(
					# Translators: This message is shown when the user enters an invalid value for the auto refresh interval setting.
					_(
						"Auto refresh interval must be between 0.5 and 10.0 seconds.\nYou entered: {value}",
					).format(value=refreshInterval),
					# Translators: The title of the message box shown when the user enters an invalid value for the auto refresh interval setting.
					_("Invalid Setting Value"),
					wx.OK | wx.ICON_ERROR,
					self,
				)
				self.refreshIntervalTextCtrl.SetFocus()
				return False
		except ValueError:
			wx.MessageBox(
				# Translators: This message is shown when the user enters an invalid value for the auto refresh interval setting.
				_("Auto refresh interval must be a valid number.\nYou entered: {value}").format(
					value=self.refreshIntervalTextCtrl.GetValue(),
				),
				# Translators: The title of the message box shown when the user enters an invalid value for the auto refresh interval setting.
				_("Invalid Setting Value"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			self.refreshIntervalTextCtrl.SetFocus()
			return False

		return super().isValid()

	def onSave(self):
		previousUseSystem = configuration.getUseSystemLibrary(fromCache=False)

		config.conf[configuration.CONFIG_SECTION_NAME][configuration.AUTO_REFRESH_SETTING_NAME] = int(  # type: ignore
			functools.reduce(
				operator.or_,
				(self.autoRefresh[i] for i in cast(list[int], self.autoRefreshList.CheckedItems)),
				0,
			),
		)

		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.AUTO_REFRESH_IDLE_TIMEOUT_SETTING_NAME
		] = self.idleTimeoutTextCtrl.GetValue()
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.AUTO_REFRESH_INTERVAL_SETTING_NAME
		] = self.refreshIntervalTextCtrl.GetValue()
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.SCREEN_CAPTURE_MAX_LINES_PER_OBJECT_SETTING_NAME
		] = self.maxLinesPerObjectSpin.GetValue()
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.SCREEN_CAPTURE_SHOW_OBJECT_NUMBERS_SETTING_NAME
		] = self.showObjectNumbersCheckBox.GetValue()

		# Table Mode settings
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.TABLE_NAVIGATOR_AFTER_SCROLL_SETTING_NAME
		] = self.tableNavigatorChoice.GetSelection()

		# Multi-line braille source
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.BRAILLE_SOURCE_SETTING_NAME
		] = self.brailleSourceChoice.GetSelection()

		# Multi-line braille line spacing
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.MULTILINE_BRAILLE_SPACING_SETTING_NAME
		] = self.lineSpacingChoice.GetSelection()

		# Hybrid print + braille mode
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.HYBRID_PRINT_AND_BRAILLE_SETTING_NAME
		] = self.hybridPrintAndBrailleCheckBox.GetValue()

		# Advanced: system library
		config.conf[configuration.CONFIG_SECTION_NAME][  # type: ignore
			configuration.USE_SYSTEM_LIBRARY_SETTING_NAME
		] = self.useSystemLibraryCheckBox.GetValue()

		self.post_onSave.notify()

		if self.useSystemLibraryCheckBox.GetValue() != previousUseSystem:
			wx.MessageBox(
				_(
					# Translators: Message shown when the user changes the system library setting.
					"The TactileDisplayAPI library source has changed.\n"
					"The change takes effect on the next driver initialisation "
					"(disconnect and reconnect your device, or restart NVDA).",
				),
				# Translators: Title for the restart-required message box.
				_("Restart Required"),
				wx.OK | wx.ICON_INFORMATION,
				self,
			)
