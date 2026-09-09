# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the per-core-cycle review-fields cache."""

import unittest
from unittest.mock import MagicMock

from addon.utils import reviewFields


def makeReviewPos(obj, bookmark, fields=None):
	"""A review position stub with a settable object and bookmark."""
	reviewPos = MagicMock()
	reviewPos.obj = obj
	reviewPos.bookmark = bookmark
	reviewPos.getTextWithFields.return_value = fields if fields is not None else ["fields"]
	return reviewPos


class TestReviewFieldsCache(unittest.TestCase):
	def setUp(self):
		reviewFields.clearCache()
		self.addCleanup(reviewFields.clearCache)
		self.obj = object()

	def test_second_read_of_the_same_position_reuses_the_walk(self):
		reviewPos = makeReviewPos(self.obj, bookmark=42)

		first = reviewFields.getTextWithFields(reviewPos)
		second = reviewFields.getTextWithFields(reviewPos)

		self.assertEqual(reviewPos.getTextWithFields.call_count, 1)
		self.assertIs(first, second)

	def test_a_moved_cursor_walks_again(self):
		reviewFields.getTextWithFields(makeReviewPos(self.obj, bookmark=42))
		moved = makeReviewPos(self.obj, bookmark=43)

		reviewFields.getTextWithFields(moved)

		moved.getTextWithFields.assert_called_once()

	def test_a_different_object_at_an_equal_bookmark_walks_again(self):
		"""Offsets bookmarks compare equal across objects; identity must break the tie."""
		reviewFields.getTextWithFields(makeReviewPos(self.obj, bookmark=42))
		other = makeReviewPos(object(), bookmark=42)

		reviewFields.getTextWithFields(other)

		other.getTextWithFields.assert_called_once()

	def test_clearing_forces_the_next_read_to_walk(self):
		reviewPos = makeReviewPos(self.obj, bookmark=42)
		reviewFields.getTextWithFields(reviewPos)

		reviewFields.clearCache()
		reviewFields.getTextWithFields(reviewPos)

		self.assertEqual(reviewPos.getTextWithFields.call_count, 2)

	def test_a_position_without_a_bookmark_is_never_cached(self):
		reviewPos = makeReviewPos(self.obj, bookmark=None)
		type(reviewPos).bookmark = property(lambda _self: (_ for _ in ()).throw(NotImplementedError))

		try:
			reviewFields.getTextWithFields(reviewPos)
			reviewFields.getTextWithFields(reviewPos)
		finally:
			del type(reviewPos).bookmark

		self.assertEqual(reviewPos.getTextWithFields.call_count, 2)


class TestRendererClearsCacheEachCycle(unittest.TestCase):
	"""The renderer must drop the cache at the end of every core cycle.

	Keying on object identity and bookmark is not enough on its own: content can
	change under an unmoved cursor. Bounding the entry to one cycle is what makes
	that safe.
	"""

	def setUp(self):
		reviewFields.clearCache()
		self.addCleanup(reviewFields.clearCache)

	def _makeRenderer(self):
		"""A renderer with only the fields _handleCoreCycle reads."""
		from addon.presentations.renderer import PresentationRenderer

		renderer = PresentationRenderer.__new__(PresentationRenderer)
		renderer._isTerminating = False
		renderer._needsRender = False
		renderer._presentationManager = MagicMock(name="presentationManager")
		renderer._presentationManager.activePresentation = None
		return renderer

	def test_core_cycle_drops_the_cached_walk(self):
		reviewPos = makeReviewPos(object(), bookmark=42)
		reviewFields.getTextWithFields(reviewPos)

		self._makeRenderer()._handleCoreCycle()
		reviewFields.getTextWithFields(reviewPos)

		self.assertEqual(reviewPos.getTextWithFields.call_count, 2)


if __name__ == "__main__":
	unittest.main()
