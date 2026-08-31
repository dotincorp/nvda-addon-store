# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for GraphicProvider detection logic."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from enum import IntEnum
from typing import Any
from unittest.mock import MagicMock

from addon.presentations.graphic import GraphicPresentation, GraphicProvider


class Role(IntEnum):
	"""Minimal stand-in for controlTypes.Role.

	Values must match NVDA's real ``controlTypes.Role`` enum because
	the production ``GraphicProvider`` compares against the real enum
	(``obj.role == controlTypes.Role.GRAPHIC``). Drift between this
	stub and NVDA's enum was a pre-existing test bug.
	"""

	GRAPHIC = 16
	BUTTON = 9
	STATICTEXT = 7


@dataclass
class FakeLocation:
	"""Minimal stand-in for locationHelper.RectLTRB."""

	left: int = 0
	top: int = 0
	right: int = 100
	bottom: int = 100

	@property
	def width(self) -> int:
		return self.right - self.left

	@property
	def height(self) -> int:
		return self.bottom - self.top


class FakeNVDAObject:
	"""Minimal stand-in for NVDAObject."""

	def __init__(self, role: Any, location: FakeLocation | None = None, name: str = "") -> None:
		self.role = role
		self.location = location
		self.name = name


class TestGraphicProviderAutoDetect(unittest.TestCase):
	"""GraphicProvider's auto-detect surface.

	The PresentationProvider API uses canProvide(obj) for the fast match
	check and createPresentation(obj, display) for the actual instantiation.
	(Pre-staging-rebase the surface was a generator-style ``__call__``;
	the new API is split for clarity and so the manager can avoid creating
	presentation objects for non-matching providers.)
	"""

	def setUp(self) -> None:
		self.provider = GraphicProvider()
		self.display = MagicMock()
		self.display.physicalNumCols = 15
		self.display.physicalNumRows = 10

	def test_canProvide_for_graphic_role_with_valid_location(self) -> None:
		obj = FakeNVDAObject(role=Role.GRAPHIC, location=FakeLocation())
		self.assertTrue(self.provider.canProvide(obj))  # type: ignore[arg-type]

	def test_createPresentation_yields_graphic_presentation(self) -> None:
		obj = FakeNVDAObject(role=Role.GRAPHIC, location=FakeLocation())
		presentation = self.provider.createPresentation(obj, self.display)  # type: ignore[arg-type]
		self.assertIsInstance(presentation, GraphicPresentation)

	def test_canProvide_false_for_non_graphic_role(self) -> None:
		obj = FakeNVDAObject(role=Role.BUTTON, location=FakeLocation())
		self.assertFalse(self.provider.canProvide(obj))  # type: ignore[arg-type]

	def test_canProvide_false_for_graphic_role_without_location(self) -> None:
		obj = FakeNVDAObject(role=Role.GRAPHIC, location=None)
		self.assertFalse(self.provider.canProvide(obj))  # type: ignore[arg-type]

	def test_canProvide_false_for_zero_width(self) -> None:
		loc = FakeLocation(left=100, right=100)  # width = 0
		obj = FakeNVDAObject(role=Role.GRAPHIC, location=loc)
		self.assertFalse(self.provider.canProvide(obj))  # type: ignore[arg-type]

	def test_canProvide_false_for_zero_height(self) -> None:
		loc = FakeLocation(top=100, bottom=100)  # height = 0
		obj = FakeNVDAObject(role=Role.GRAPHIC, location=loc)
		self.assertFalse(self.provider.canProvide(obj))  # type: ignore[arg-type]


class TestGraphicProviderForce(unittest.TestCase):
	def setUp(self) -> None:
		self.provider = GraphicProvider()
		self.display = MagicMock()
		self.display.physicalNumCols = 15
		self.display.physicalNumRows = 10

	def test_force_returns_presentation_for_any_role_with_location(self) -> None:
		obj = FakeNVDAObject(role=Role.BUTTON, location=FakeLocation())
		result = self.provider.forceForObject(obj, self.display)  # type: ignore[arg-type]
		self.assertIsInstance(result, GraphicPresentation)

	def test_force_returns_none_without_location(self) -> None:
		obj = FakeNVDAObject(role=Role.BUTTON, location=None)
		result = self.provider.forceForObject(obj, self.display)  # type: ignore[arg-type]
		self.assertIsNone(result)

	def test_force_returns_none_for_zero_size(self) -> None:
		loc = FakeLocation(left=50, right=50)
		obj = FakeNVDAObject(role=Role.BUTTON, location=loc)
		result = self.provider.forceForObject(obj, self.display)  # type: ignore[arg-type]
		self.assertIsNone(result)


class TestGraphicPresentation(unittest.TestCase):
	def setUp(self) -> None:
		self.display = MagicMock()
		self.display.physicalNumCols = 15
		self.display.physicalNumRows = 10

	def test_name_is_graphic(self) -> None:
		obj = FakeNVDAObject(role=Role.GRAPHIC, location=FakeLocation(), name="Logo")
		p = GraphicPresentation(obj, self.display)  # type: ignore[arg-type]
		self.assertEqual(p.name, "graphic")

	def test_scroll_forward_returns_false(self) -> None:
		obj = FakeNVDAObject(role=Role.GRAPHIC, location=FakeLocation())
		p = GraphicPresentation(obj, self.display)  # type: ignore[arg-type]
		self.assertFalse(p.scrollForward())

	def test_scroll_back_returns_false(self) -> None:
		obj = FakeNVDAObject(role=Role.GRAPHIC, location=FakeLocation())
		p = GraphicPresentation(obj, self.display)  # type: ignore[arg-type]
		self.assertFalse(p.scrollBack())

	def test_is_still_valid_returns_true_when_navobj_unchanged(self) -> None:
		"""After feature 015's session-collapse, isStillValid mirrors
		navigator-object identity. With api.getNavigatorObject returning
		the same obj the presentation was constructed for, it's still valid.
		"""
		from unittest.mock import patch

		obj = FakeNVDAObject(role=Role.GRAPHIC, location=FakeLocation())
		p = GraphicPresentation(obj, self.display)  # type: ignore[arg-type]
		with patch("api.getNavigatorObject", return_value=obj, create=True):
			self.assertTrue(p.isStillValid())

	def test_is_still_valid_returns_false_when_navobj_changed(self) -> None:
		"""When the navigator moves to a different object, the presentation
		invalidates so the manager constructs a fresh one for the new graphic.
		"""
		from unittest.mock import patch

		original = FakeNVDAObject(role=Role.GRAPHIC, location=FakeLocation())
		different = FakeNVDAObject(role=Role.GRAPHIC, location=FakeLocation())
		p = GraphicPresentation(original, self.display)  # type: ignore[arg-type]
		with patch("api.getNavigatorObject", return_value=different, create=True):
			self.assertFalse(p.isStillValid())
