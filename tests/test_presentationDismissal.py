# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for dismissing the presentation on screen.

Returning to braille used to force the braille presentation, and a forced
presentation short-circuits `update()` while it stays valid — which the braille
presentations always are. So one press pinned braille for the session and
nothing auto-entered again, in any mode. Dismissing the object instead lets
braille win by ordinary fallback, and only for as long as the navigator stays
where it is.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from addon.presentations import PresentationManager
from addon.presentations.manager import MAX_UNANSWERABLE_VALIDITY_CHECKS

from .test_presentations import MockProvider


class _Element:
	"""Stands in for an NVDAObject, which compares by identity of what it points at.

	NVDA mints a fresh NVDAObject per event, so the dismissal has to compare
	with ``==`` (which NVDAObject routes to ``_isEqual``); ``is`` would forget
	the dismissal on the very next event.
	"""

	def __init__(self, key: str) -> None:
		self.key = key

	def __eq__(self, other: object) -> bool:
		return isinstance(other, _Element) and other.key == self.key

	def __hash__(self) -> int:
		return hash(self.key)


class ReusingProvider(MockProvider):
	"""A provider whose presentation's validity is a complete answer.

	``TableProvider`` is the only real one. The flag is what lets a dismissal
	outlive the object it was made on.
	"""

	validityIsAuthoritative = True


class TestDismissal(unittest.TestCase):
	def setUp(self):
		self.manager = PresentationManager(MagicMock())
		self.visual = MockProvider(name="visual", should_yield=True)
		self.braille = MockProvider(name="braille", should_yield=True)
		# What a dismissal steps back to; the real BrailleProvider declares it.
		self.braille.isFallback = True
		self.manager.registerProvider(self.visual)
		self.manager.registerProvider(self.braille)

	def test_the_visual_presentation_wins_before_a_dismissal(self):
		self.manager.update(_Element("image"))

		self.assertIs(self.manager.activePresentation, self.visual._presentation)

	def test_a_dismissed_object_falls_back_to_braille(self):
		element = _Element("image")
		self.manager.update(element)

		self.manager.dismissActivePresentation(element)
		self.manager.update(_Element("image"))

		self.assertIs(self.manager.activePresentation, self.braille._presentation)

	def test_the_dismissal_survives_a_freshly_minted_object(self):
		"""The same element arrives as a new instance on every event."""
		self.manager.update(_Element("image"))
		self.manager.dismissActivePresentation(_Element("image"))

		for _ in range(3):
			self.manager.update(_Element("image"))

		self.assertIs(self.manager.activePresentation, self.braille._presentation)

	def test_moving_elsewhere_lifts_the_dismissal(self):
		self.manager.update(_Element("image"))
		self.manager.dismissActivePresentation(_Element("image"))

		self.manager.update(_Element("table"))

		self.assertIs(self.manager.activePresentation, self.visual._presentation)

	def test_returning_to_a_dismissed_element_is_a_fresh_visit(self):
		self.manager.update(_Element("image"))
		self.manager.dismissActivePresentation(_Element("image"))
		self.manager.update(_Element("elsewhere"))

		self.manager.update(_Element("image"))

		self.assertIs(self.manager.activePresentation, self.visual._presentation)

	def test_the_fallback_provider_is_never_dismissed(self):
		"""Dismissing the fallback too would leave nothing on the display."""
		self.manager.update(_Element("image"))
		self.manager.dismissActivePresentation(_Element("image"))
		self.manager.update(_Element("image"))

		self.manager.dismissActivePresentation(_Element("image"))
		self.manager.update(_Element("image"))

		self.assertIs(self.manager.activePresentation, self.braille._presentation)

	def test_an_object_that_raises_on_comparison_does_not_propagate(self):
		"""A dead COM object raises from __eq__; the update must survive it."""

		class Hostile:
			def __eq__(self, other: object) -> bool:
				raise RuntimeError("dead COM object")

			def __hash__(self) -> int:
				return 0

		self.manager.update(_Element("image"))
		self.manager.dismissActivePresentation(Hostile())

		self.manager.update(_Element("image"))

		self.assertIsNotNone(self.manager.activePresentation)

	def test_dismissing_before_anything_is_active_still_takes_effect(self):
		"""The chord means "not this", whether or not a presentation is on screen yet.

		Making it conditional on something being active would mean the chord
		silently did nothing whenever the active presentation happened to be
		None, which is not a distinction the user can see.
		"""
		self.manager.dismissActivePresentation(_Element("image"))

		self.manager.update(_Element("image"))

		self.assertIs(self.manager.activePresentation, self.braille._presentation)

	def test_a_dismissal_clears_a_forced_presentation(self):
		"""Otherwise the force would outrank the dismissal and nothing would change."""
		# A forced presentation is what the explicit force-in chords leave behind.
		self.manager.forcePresentation("visual", _Element("image"))
		self.assertTrue(self.manager.isForcedMode)

		self.manager.dismissActivePresentation(_Element("image"))
		self.manager.update(_Element("image"))

		self.assertFalse(self.manager.isForcedMode)
		self.assertIs(self.manager.activePresentation, self.braille._presentation)

	def test_clearing_the_force_also_lifts_the_dismissal(self):
		"""Screen capture clears the force so its toggle wins; it must win over this too.

		The skip keeps only the last provider, so a live dismissal would swallow
		a screen-capture toggle - which sits at the front of the list - and the
		toggle would look dead.
		"""
		element = _Element("image")
		self.manager.dismissActivePresentation(element)

		self.manager.clearOverrides()
		self.manager.update(_Element("image"))

		self.assertIs(self.manager.activePresentation, self.visual._presentation)

	def test_a_provider_that_does_not_reuse_lifts_on_any_other_object(self):
		"""The contrast to the table case below: validity is not a safe scope here.

		``MockPresentation.isStillValid`` is unconditionally True, as both
		braille presentations and screen capture are. Scoping by validity for
		those would pin the dismissal for the session.
		"""
		self.manager.update(_Element("image"))
		self.manager.dismissActivePresentation(_Element("image"))

		self.manager.update(_Element("somewhere else"))

		self.assertIs(self.manager.activePresentation, self.visual._presentation)


class TestDismissalScopedByPresentation(unittest.TestCase):
	"""A mode that spans many objects stays dismissed while its presentation holds.

	A table is navigated cell by cell and every cell is a different NVDAObject,
	so an object-scoped dismissal would be undone by the next arrow key and
	table mode would come straight back.
	"""

	def setUp(self):
		self.manager = PresentationManager(MagicMock())
		self.table = ReusingProvider(name="table", should_yield=True)
		self.braille = MockProvider(name="braille", should_yield=True)
		# What a dismissal steps back to; the real BrailleProvider declares it.
		self.braille.isFallback = True
		self.manager.registerProvider(self.table)
		self.manager.registerProvider(self.braille)

	def test_the_dismissal_survives_moving_to_another_cell(self):
		self.manager.update(_Element("cell1"))
		self.manager.dismissActivePresentation(_Element("cell1"))

		self.manager.update(_Element("cell2"))

		self.assertIs(self.manager.activePresentation, self.braille._presentation)

	def test_leaving_the_table_lifts_the_dismissal(self):
		"""Its presentation reporting itself invalid is what "left" means."""
		self.manager.update(_Element("cell1"))
		self.manager.dismissActivePresentation(_Element("cell1"))
		self.manager.update(_Element("cell2"))

		self.table._presentation._is_valid = False
		self.manager.update(_Element("a paragraph"))

		self.assertIs(self.manager.activePresentation, self.table._presentation)

	def _raiseFrom(self, presentation, times: int) -> None:
		"""Make ``isStillValid`` raise the next ``times`` calls, then answer True."""
		remaining = [times]

		def maybeBoom(triggerReason=None):
			if remaining[0] > 0:
				remaining[0] -= 1
				raise RuntimeError("Excel is busy")
			return True

		presentation.isStillValid = maybeBoom

	def test_a_momentary_refusal_does_not_lift_the_dismissal(self):
		"""Excel rejects COM calls whenever it is busy - typing in a cell, say.

		Reading a refusal as "no longer valid" would bring the table back in the
		middle of reading the sheet in braille, which is precisely what the
		chord was pressed to stop.
		"""
		self.manager.update(_Element("cell1"))
		self.manager.dismissActivePresentation(_Element("cell1"))
		self._raiseFrom(self.table._presentation, times=2)

		self.manager.update(_Element("cell2"))
		self.manager.update(_Element("cell3"))

		self.assertIs(self.manager.activePresentation, self.braille._presentation)

	def test_the_dismissal_survives_the_application_recovering(self):
		self.manager.update(_Element("cell1"))
		self.manager.dismissActivePresentation(_Element("cell1"))
		self._raiseFrom(self.table._presentation, times=2)

		for _ in range(6):
			self.manager.update(_Element("cell2"))

		self.assertIs(
			self.manager.activePresentation,
			self.braille._presentation,
			"a recovered check answering True must not spend the budget",
		)

	def test_a_check_that_never_answers_gives_the_display_back(self):
		"""An object that is really gone raises every time.

		Holding on that forever would strand the display on braille for the
		session - the pinning this replaced forcing to avoid.
		"""
		self.manager.update(_Element("cell1"))
		self.manager.dismissActivePresentation(_Element("cell1"))

		def boom(triggerReason=None):
			raise RuntimeError("dead COM object")

		self.table._presentation.isStillValid = boom
		for _ in range(MAX_UNANSWERABLE_VALIDITY_CHECKS + 1):
			self.manager.update(_Element("cell2"))

		self.assertIs(self.manager.activePresentation, self.table._presentation)

	def test_clearing_the_force_also_lifts_a_presentation_scoped_dismissal(self):
		self.manager.update(_Element("cell1"))
		self.manager.dismissActivePresentation(_Element("cell1"))

		self.manager.clearOverrides()
		self.manager.update(_Element("cell2"))

		self.assertIs(self.manager.activePresentation, self.table._presentation)


class TestAForcedPresentationSurvivesAnUnanswerableCheck(unittest.TestCase):
	"""Forcing is the most explicit thing the user can say about the mode.

	Guarding isStillValid stops a raise aborting the whole update, but a raise
	must not then read as False either: False drops the force, so a table forced
	with a long press would silently un-force the moment Excel refused one COM
	call. Before the guard a raise left the force alone, and it still must.
	"""

	def setUp(self):
		self.manager = PresentationManager(MagicMock())
		self.table = ReusingProvider(name="table", should_yield=True)
		self.braille = MockProvider(name="braille", should_yield=True)
		# What a dismissal steps back to; the real BrailleProvider declares it.
		self.braille.isFallback = True
		self.manager.registerProvider(self.table)
		self.manager.registerProvider(self.braille)

	def test_a_raising_check_keeps_the_force(self):
		self.manager.forcePresentation("table", _Element("cell1"))

		def boom(triggerReason=None):
			raise RuntimeError("Excel is busy")

		forced = self.manager.activePresentation
		assert forced is not None
		forced.isStillValid = boom
		self.manager.update(_Element("cell2"))

		self.assertTrue(self.manager.isForcedMode)
		self.assertIs(self.manager.activePresentation, forced)

	def test_a_check_that_answers_no_still_drops_the_force(self):
		self.manager.forcePresentation("table", _Element("cell1"))
		forced = self.manager.activePresentation
		assert forced is not None
		forced._is_valid = False

		self.manager.update(_Element("a paragraph"))

		self.assertFalse(self.manager.isForcedMode)


if __name__ == "__main__":
	unittest.main()
