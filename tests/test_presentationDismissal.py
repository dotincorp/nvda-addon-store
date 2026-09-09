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


class TestDismissal(unittest.TestCase):
	def setUp(self):
		self.manager = PresentationManager(MagicMock())
		self.visual = MockProvider(name="visual", should_yield=True)
		self.braille = MockProvider(name="braille", should_yield=True)
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

	def test_the_last_provider_is_never_dismissed(self):
		"""Braille is the fallback; dismissing everything would leave no output."""
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


if __name__ == "__main__":
	unittest.main()
