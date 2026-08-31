# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2026 Dot Incorporated

from enum import Enum

from extensionPoints import Action


class TriggerReason(Enum):
	"""Identifies the navigation event that triggered a presentation validity check.

	Forwarded by the originating event handler through ``PresentationRenderer.onReviewMove``
	and ``PresentationManager.update`` into ``Presentation.isStillValid``, so presentations
	can react to specific event types without subscribing to events themselves.

	``None`` (the absence of a reason) is a legitimate value meaning *no discrete
	navigation trigger* — e.g. a programmatic refresh, a manual mode toggle, or the
	initial display paint. Only events that a handler explicitly tags carry a member;
	the remaining ``onReviewMove`` call sites pass ``None``.
	"""

	CARET_MOVE = "caretMove"
	REVIEW_MOVE = "reviewMove"


reviewMove = Action()
navigatorObjectValueChange = Action()
browseModeMove = Action()
caretMove = Action()
coreCycle = Action()
