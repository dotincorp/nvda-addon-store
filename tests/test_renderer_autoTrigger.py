# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the presentation-transition hook in PresentationRenderer (feature 015).

The hook lives in ``onReviewMove``'s transition-detection block. After
the session-collapse refactor, it has one job: call
``previousPresentation.terminate()`` on ``"graphic" → other`` transitions
so the outgoing GraphicPresentation can clear the tactile area.

Auto-entry and same-graphic re-renders are handled implicitly by
``GraphicPresentation.render()`` running on the next coreCycle — there
is no explicit "enter" code path in the renderer.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _makeRenderer():
	"""Build a renderer with mocked-out collaborators.

	Bypasses ``__init__`` (which constructs a PresentationManager and
	registers providers — too much I/O for a unit test). Populates only
	the fields ``onReviewMove`` reads.
	"""
	from addon.presentations.renderer import PresentationRenderer

	renderer = PresentationRenderer.__new__(PresentationRenderer)
	renderer._isTerminating = False
	renderer._presentationManager = MagicMock(name="presentationManager")
	renderer._needsRender = False
	renderer.forceRefresh = False
	renderer.display = MagicMock(name="display")
	return renderer


def _setPresentationTransition(renderer, previousName: str | None, activeName: str | None):
	"""Configure the presentation manager to report a transition.

	``onReviewMove`` reads ``activePresentation`` twice — once before the
	manager's ``update`` (that becomes ``previousPresentation``) and
	again after.
	"""
	previous = None
	if previousName is not None:
		previous = MagicMock(name=f"prev-{previousName}")
		previous.name = previousName
	active = None
	if activeName is not None:
		active = MagicMock(name=f"active-{activeName}")
		active.name = activeName
	# First call to .activePresentation returns previous; second returns
	# active (after manager.update has run).
	type(renderer._presentationManager).activePresentation = property(
		lambda self_: self_._active,
	)
	renderer._presentationManager._active = previous

	def updateSideEffect(_obj, triggerReason=None):
		renderer._presentationManager._active = active

	renderer._presentationManager.update.side_effect = updateSideEffect
	return previous, active


class TestAutoTransitionHook(unittest.TestCase):
	"""``onReviewMove`` calls ``previousPresentation.terminate()`` on graphic-out."""

	def test_transitionOutOfGraphicCallsTerminate(self) -> None:
		"""``"graphic" → "braille"`` transition triggers
		``previousPresentation.terminate()``."""
		renderer = _makeRenderer()
		previous, _active = _setPresentationTransition(
			renderer,
			previousName="graphic",
			activeName="braille",
		)
		navObj = MagicMock(name="navObj")

		with patch("api.getNavigatorObject", return_value=navObj, create=True):
			renderer.onReviewMove()

		assert previous is not None  # for type-checker
		previous.terminate.assert_called_once_with()

	def test_transitionToNoneCallsTerminate(self) -> None:
		"""``"graphic" → None`` (no active presentation after) triggers terminate."""
		renderer = _makeRenderer()
		previous, _active = _setPresentationTransition(
			renderer,
			previousName="graphic",
			activeName=None,
		)
		navObj = MagicMock(name="navObj")

		with patch("api.getNavigatorObject", return_value=navObj, create=True):
			renderer.onReviewMove()

		assert previous is not None
		previous.terminate.assert_called_once_with()

	def test_transitionIntoGraphicDoesNotCallTerminate(self) -> None:
		"""``"braille" → "graphic"`` doesn't terminate the outgoing braille presentation.

		The renderer's hook only terminates on graphic-out; render-driven
		updates handle graphic-in via the next coreCycle.
		"""
		renderer = _makeRenderer()
		previous, _active = _setPresentationTransition(
			renderer,
			previousName="braille",
			activeName="graphic",
		)
		navObj = MagicMock(name="navObj")

		with patch("api.getNavigatorObject", return_value=navObj, create=True):
			renderer.onReviewMove()

		assert previous is not None
		previous.terminate.assert_not_called()

	def test_sameNameTransitionDoesNothing(self) -> None:
		"""``previousName == activeName`` is a no-op for the transition hook."""
		renderer = _makeRenderer()
		previous, _active = _setPresentationTransition(
			renderer,
			previousName="graphic",
			activeName="graphic",
		)
		navObj = MagicMock(name="navObj")

		with patch("api.getNavigatorObject", return_value=navObj, create=True):
			renderer.onReviewMove()

		assert previous is not None
		previous.terminate.assert_not_called()


class TestRemovedNotification(unittest.TestCase):
	"""The ``Graphic view available`` message is gone from the renderer."""

	def test_noGraphicViewAvailableMessage(self) -> None:
		"""Source of ``renderer.py`` no longer contains the message string."""
		rendererPath = Path(__file__).resolve().parent.parent / "addon" / "presentations" / "renderer.py"
		source = rendererPath.read_text(encoding="utf-8")
		self.assertNotIn(
			"Graphic view available",
			source,
			"renderer.py must not contain the 'Graphic view available' "
			"notification after feature 015 — auto-entry replaces it.",
		)


if __name__ == "__main__":
	unittest.main()
