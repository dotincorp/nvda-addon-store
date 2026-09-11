# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""One review-position field walk per core cycle.

``TextInfo.getTextWithFields()`` walks the document structure at the review
position. Table detection and cell-position lookup each need it, and NVDA
delivers two review events per keypress, so the same walk was being repeated
three or four times for one cursor move.

This module memoises the result for the current core cycle.
``PresentationRenderer`` calls :func:`clearCache` at the end of every cycle, so
a stale entry can never outlive the cycle it was made in. Within a cycle the
entry is additionally keyed on the review position's object identity and
bookmark, so a different object at equal offsets is never served another
object's fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from textInfos import TextInfo

_cachedObj: Any = None
"""The review position's object for the cached entry, held so its identity stays unique."""
_cachedBookmark: Any = None
_cachedFields: list[Any] | None = None


def getTextWithFields(reviewPos: TextInfo) -> list[Any]:
	"""Return ``reviewPos.getTextWithFields()``, reusing this cycle's result.

	Falls back to an uncached call when the position has no usable bookmark to
	key on.

	:param reviewPos: The review position to read.
	:returns: The field list, exactly as ``getTextWithFields`` returns it.
	"""
	global _cachedObj, _cachedBookmark, _cachedFields

	try:
		# Not every TextInfo implements a bookmark; without one there is nothing
		# safe to key on, so the caller pays for the walk.
		bookmark: Any = getattr(reviewPos, "bookmark")  # noqa: B009
	except (NotImplementedError, AttributeError, RuntimeError):
		return reviewPos.getTextWithFields()

	obj = getattr(reviewPos, "obj", None)
	if _cachedFields is not None and obj is _cachedObj and bookmark == _cachedBookmark:
		return _cachedFields

	fields = reviewPos.getTextWithFields()
	_cachedObj = obj
	_cachedBookmark = bookmark
	_cachedFields = fields
	return fields


def clearCache() -> None:
	"""Drop the cached entry. Called once per core cycle by the renderer."""
	global _cachedObj, _cachedBookmark, _cachedFields
	_cachedObj = None
	_cachedBookmark = None
	_cachedFields = None
