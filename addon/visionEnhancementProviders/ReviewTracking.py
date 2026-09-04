# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2026 Dot Incorporated

from typing import TYPE_CHECKING

import addonHandler
from autoSettingsUtils.autoSettings import SupportedSettingType  # type: ignore
from NVDAObjects import NVDAObject
from vision import providerBase
from vision.constants import Context
from vision.visionHandlerExtensionPoints import EventExtensionPoints

if TYPE_CHECKING:
	from ..extension_points.review_tracking import (
		browseModeMove,
		caretMove,
		coreCycle,
		reviewMove,
		TriggerReason,
	)
else:
	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	review_tracking_extension_points = addon.loadModule("extension_points.review_tracking")
	reviewMove = review_tracking_extension_points.reviewMove
	browseModeMove = review_tracking_extension_points.browseModeMove
	caretMove = review_tracking_extension_points.caretMove
	coreCycle = review_tracking_extension_points.coreCycle
	TriggerReason = review_tracking_extension_points.TriggerReason


class ReviewTrackingSettings(providerBase.VisionEnhancementProviderSettings):
	@classmethod
	def getId(cls) -> str:
		return "ReviewTracking"

	@classmethod
	def getDisplayName(cls) -> str:
		return "Review Tracking"

	def _get_supportedSettings(self) -> SupportedSettingType:  # type: ignore
		return []  # type: ignore


class ReviewTracking(providerBase.VisionEnhancementProvider):
	_settings: ReviewTrackingSettings = ReviewTrackingSettings()

	@classmethod
	def canStart(cls) -> bool:
		return True

	@classmethod
	def isEnabledInConfig(cls) -> bool:
		return True

	@classmethod
	def getSettings(cls) -> ReviewTrackingSettings:
		return cls._settings

	def registerEventExtensionPoints(self, extensionPoints: EventExtensionPoints) -> None:
		extensionPoints.post_reviewMove.register(self.handleReviewMove)
		extensionPoints.post_browseModeMove.register(self.handleBrowseModeMove)
		extensionPoints.post_caretMove.register(self.handleCaretMove)
		extensionPoints.post_coreCycle.register(self.handleCoreCycle)

	def terminate(self) -> None:
		"""Nothing to clean up; the extension point registrations are process-wide."""

	def handleReviewMove(self, context: Context) -> None:
		reviewMove.notify(context=context, triggerReason=TriggerReason.REVIEW_MOVE)

	def handleBrowseModeMove(self, obj: NVDAObject) -> None:
		browseModeMove.notify(obj=obj)

	def handleCaretMove(self, obj: NVDAObject) -> None:
		caretMove.notify(obj=obj, triggerReason=TriggerReason.CARET_MOVE)

	def handleCoreCycle(self) -> None:
		coreCycle.notify()


VisionEnhancementProvider = ReviewTracking
