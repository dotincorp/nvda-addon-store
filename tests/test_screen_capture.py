# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

"""Unit tests for ScreenCapturePresentation."""

import unittest
from unittest.mock import MagicMock, patch

from addon.presentations.screenCapture import (
	ScreenCapturePresentation,
	CHILD_INDENT,
)


class MockNVDAObject:
	"""A mock NVDAObject for testing screen capture."""

	def __init__(
		self,
		name: str = "Test Object",
		role=None,
		positionInfo: dict | None = None,
		parent: "MockNVDAObject | None" = None,
		previous: "MockNVDAObject | None" = None,
		next: "MockNVDAObject | None" = None,
	):
		self.name = name
		self.role = role or MagicMock()
		self.roleTextBraille = None
		self.value = None
		self.states = set()
		self.positionInfo = positionInfo
		self.parent = parent
		self.simpleParent = parent
		self.previous = previous
		self.simplePrevious = previous
		self.next = next
		self.simpleNext = next


class MockDisplay:
	"""A mock display for testing."""

	def __init__(
		self,
		numCols: int = 30,
		physicalNumCols: int = 30,
		physicalNumRows: int = 10,
		cellHeight: int = 4,
		verticalCellSpacing: int = 1,
	):
		self.numCols = numCols
		self.physicalNumCols = physicalNumCols
		self.physicalNumRows = physicalNumRows
		self.cellHeight = cellHeight
		self.verticalCellSpacing = verticalCellSpacing


def create_sibling_chain(count: int, start_index: int = 1) -> list[MockNVDAObject]:
	"""Create a chain of sibling objects.

	Returns list where index 0 is the first sibling.
	Each object has positionInfo with indexInGroup set.
	"""
	objects = []
	for i in range(count):
		obj = MockNVDAObject(
			name=f"Item {start_index + i}",
			positionInfo={"indexInGroup": start_index + i, "similarItemsInGroup": count},
		)
		objects.append(obj)

	# Link siblings
	for i, obj in enumerate(objects):
		if i > 0:
			obj.previous = objects[i - 1]
			obj.simplePrevious = objects[i - 1]
		if i < len(objects) - 1:
			obj.next = objects[i + 1]
			obj.simpleNext = objects[i + 1]

	return objects


class TestConstants(unittest.TestCase):
	"""Tests for module constants."""

	def test_no_duplicated_spacing_constants(self):
		"""Spacing is owned by the display; screen capture keeps no duplicate constants.

		SC-003 / FR-002: removing ``LINE_HEIGHT_DOTS`` / ``VERTICAL_SPACING_DOTS`` /
		``BRAILLE_CELL_HEIGHT_DOTS`` ensures a single source of truth.
		"""
		import addon.presentations.screenCapture as sc

		for name in ("LINE_HEIGHT_DOTS", "VERTICAL_SPACING_DOTS", "BRAILLE_CELL_HEIGHT_DOTS"):
			self.assertFalse(
				hasattr(sc, name),
				f"{name} should be removed; line height derives from the display",
			)

	def test_child_indent_value(self):
		"""CHILD_INDENT should be 2 spaces."""
		self.assertEqual(CHILD_INDENT, 2)


class TestGetPositionInfo(unittest.TestCase):
	"""Tests for _getPositionInfo method."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay()
		self.presentation = ScreenCapturePresentation(self.display)

	def test_returns_index_when_position_info_has_index_in_group(self):
		"""Should return indexInGroup when available."""
		obj = MockNVDAObject(positionInfo={"indexInGroup": 3, "similarItemsInGroup": 10})
		result = self.presentation._getPositionInfo(obj)
		self.assertEqual(result, 3)

	def test_returns_none_when_no_position_info(self):
		"""Should return None when object has no positionInfo."""
		obj = MockNVDAObject(positionInfo=None)
		result = self.presentation._getPositionInfo(obj)
		self.assertIsNone(result)

	def test_returns_none_when_position_info_missing_index(self):
		"""Should return None when positionInfo lacks indexInGroup."""
		obj = MockNVDAObject(positionInfo={"similarItemsInGroup": 10})
		result = self.presentation._getPositionInfo(obj)
		self.assertIsNone(result)

	def test_returns_none_when_position_info_is_empty_dict(self):
		"""Should return None when positionInfo is empty dict."""
		obj = MockNVDAObject(positionInfo={})
		result = self.presentation._getPositionInfo(obj)
		self.assertIsNone(result)

	def test_handles_index_of_one(self):
		"""Should return 1 for first item in group."""
		obj = MockNVDAObject(positionInfo={"indexInGroup": 1})
		result = self.presentation._getPositionInfo(obj)
		self.assertEqual(result, 1)


class TestViewportState(unittest.TestCase):
	"""Tests for viewport state management."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay()
		self.presentation = ScreenCapturePresentation(self.display)

	def test_initial_viewport_is_empty(self):
		"""Viewport should be empty initially."""
		self.assertEqual(self.presentation._visibleObjects, [])

	def test_initial_navigator_index_is_negative_one(self):
		"""Navigator index should be -1 when not in viewport."""
		self.assertEqual(self.presentation._navigatorIndex, -1)

	def test_initial_parent_is_none(self):
		"""Parent should be None initially."""
		self.assertIsNone(self.presentation._parent)


class TestBuildViewport(unittest.TestCase):
	"""Tests for _buildViewport method."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay(physicalNumRows=10)
		self.presentation = ScreenCapturePresentation(self.display)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_builds_viewport_with_single_object(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should build viewport with single object when no siblings."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		nav = MockNVDAObject(name="Navigator", parent=parent)

		self.presentation._buildViewport(nav, parent, availableLines=5)

		self.assertEqual(len(self.presentation._visibleObjects), 1)
		self.assertEqual(self.presentation._visibleObjects[0], nav)
		self.assertEqual(self.presentation._navigatorIndex, 0)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_builds_viewport_expanding_bidirectionally(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should expand viewport bidirectionally from center."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(5)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent
		nav = siblings[2]  # Middle object

		self.presentation._buildViewport(nav, parent, availableLines=5)

		# Should include objects around navigator
		self.assertIn(nav, self.presentation._visibleObjects)
		self.assertGreater(len(self.presentation._visibleObjects), 1)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_navigator_index_tracks_position(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Navigator index should track position in visible objects."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(3)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent
		nav = siblings[1]  # Middle object

		self.presentation._buildViewport(nav, parent, availableLines=3)

		# Navigator should be found in visible objects
		self.assertIn(nav, self.presentation._visibleObjects)
		self.assertEqual(self.presentation._visibleObjects[self.presentation._navigatorIndex], nav)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_respects_available_lines(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should not exceed available lines."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(20)  # Many siblings
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent
		nav = siblings[10]

		self.presentation._buildViewport(nav, parent, availableLines=3)

		# Should have at most 3 objects (one per line)
		self.assertLessEqual(len(self.presentation._visibleObjects), 3)


class TestBuildViewportFromFirst(unittest.TestCase):
	"""Tests for _buildViewportFromFirst method."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay(physicalNumRows=10)
		self.presentation = ScreenCapturePresentation(self.display)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_builds_from_specified_first_object(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should start viewport at specified first object."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(10)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent

		firstObj = siblings[5]
		navObj = siblings[7]

		self.presentation._buildViewportFromFirst(firstObj, navObj, parent, availableLines=3)

		self.assertEqual(self.presentation._visibleObjects[0], firstObj)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_navigator_index_negative_when_not_visible(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Navigator index should be -1 when navigator not in viewport."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(10)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent

		firstObj = siblings[0]
		navObj = siblings[9]  # Far from viewport

		self.presentation._buildViewportFromFirst(firstObj, navObj, parent, availableLines=2)

		# Navigator should not be visible (too few lines)
		self.assertEqual(self.presentation._navigatorIndex, -1)


class TestBuildViewportFromLast(unittest.TestCase):
	"""Tests for _buildViewportFromLast method."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay(physicalNumRows=10)
		self.presentation = ScreenCapturePresentation(self.display)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_builds_ending_at_specified_last_object(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should end viewport at specified last object."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(10)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent

		lastObj = siblings[7]
		navObj = siblings[5]

		self.presentation._buildViewportFromLast(lastObj, navObj, parent, availableLines=3)

		self.assertEqual(self.presentation._visibleObjects[-1], lastObj)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_fills_backward_from_last(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropsBraille,
		mock_hasUsefulText,
	):
		"""Should fill viewport backward from last object."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropsBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(10)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent

		lastObj = siblings[9]  # Last sibling
		navObj = siblings[7]

		self.presentation._buildViewportFromLast(lastObj, navObj, parent, availableLines=3)

		# Should have 3 objects ending with lastObj
		self.assertEqual(len(self.presentation._visibleObjects), 3)
		self.assertEqual(self.presentation._visibleObjects[-1], lastObj)
		# Previous objects should be siblings[8] and siblings[7]
		self.assertEqual(self.presentation._visibleObjects[-2], siblings[8])
		self.assertEqual(self.presentation._visibleObjects[-3], siblings[7])

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_navigator_index_tracks_position_when_visible(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropsBraille,
		mock_hasUsefulText,
	):
		"""Navigator index should track position when navigator is visible."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropsBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(10)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent

		lastObj = siblings[9]
		navObj = siblings[8]  # Second to last, should be visible

		self.presentation._buildViewportFromLast(lastObj, navObj, parent, availableLines=3)

		# Navigator should be visible and tracked
		self.assertIn(navObj, self.presentation._visibleObjects)
		self.assertEqual(self.presentation._visibleObjects[self.presentation._navigatorIndex], navObj)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_navigator_index_negative_when_not_visible(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropsBraille,
		mock_hasUsefulText,
	):
		"""Navigator index should be -1 when navigator not in viewport."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropsBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(10)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent

		lastObj = siblings[9]
		navObj = siblings[0]  # Far from viewport

		self.presentation._buildViewportFromLast(lastObj, navObj, parent, availableLines=2)

		# Navigator should not be visible
		self.assertEqual(self.presentation._navigatorIndex, -1)


class TestScrollForward(unittest.TestCase):
	"""Tests for scrollForward method."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay(physicalNumRows=10)
		self.presentation = ScreenCapturePresentation(self.display)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.api")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_scroll_forward_moves_to_next_page(
		self,
		mock_nvda_config,
		mock_config,
		mock_api,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Scroll forward should start new page after last visible object."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(10)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent
		navObj = siblings[0]
		mock_api.getNavigatorObject.return_value = navObj

		# Set up initial viewport with first 3 objects
		self.presentation._visibleObjects = siblings[:3]
		self.presentation._navigatorIndex = 0
		self.presentation._parent = parent
		self.presentation._navObj = navObj

		result = self.presentation.scrollForward()

		# Should have scrolled
		self.assertTrue(result)
		# First visible object should now be siblings[3] (after previous last)
		self.assertEqual(self.presentation._visibleObjects[0], siblings[3])

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.api")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_scroll_forward_returns_false_at_end(
		self,
		mock_nvda_config,
		mock_config,
		mock_api,
		mock_translate,
		mock_getPropsBraille,
		mock_hasUsefulText,
	):
		"""Scroll forward should return False when already at end."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropsBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.return_value = [ord(c) for c in "text"[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(3)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent
		navObj = siblings[2]  # Last object
		mock_api.getNavigatorObject.return_value = navObj

		# Viewport already showing last object
		self.presentation._visibleObjects = siblings
		self.presentation._navigatorIndex = 2
		self.presentation._parent = parent
		self.presentation._navObj = navObj

		result = self.presentation.scrollForward()

		self.assertFalse(result)


class TestScrollBack(unittest.TestCase):
	"""Tests for scrollBack method."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay(physicalNumRows=10)
		self.presentation = ScreenCapturePresentation(self.display)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.api")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_scroll_back_moves_to_previous_page(
		self,
		mock_nvda_config,
		mock_config,
		mock_api,
		mock_translate,
		mock_getPropsBraille,
		mock_hasUsefulText,
	):
		"""Scroll back should end new page before first visible object."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropsBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.return_value = [ord(c) for c in "text"[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(10)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent
		navObj = siblings[5]
		mock_api.getNavigatorObject.return_value = navObj

		# Set up viewport showing objects 5-7
		self.presentation._visibleObjects = siblings[5:8]
		self.presentation._navigatorIndex = 0
		self.presentation._parent = parent
		self.presentation._navObj = navObj

		result = self.presentation.scrollBack()

		# Should have scrolled
		self.assertTrue(result)
		# Last visible object should now be siblings[4] (before previous first)
		self.assertEqual(self.presentation._visibleObjects[-1], siblings[4])

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.api")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_scroll_back_returns_false_at_start(
		self,
		mock_nvda_config,
		mock_config,
		mock_api,
		mock_translate,
		mock_getPropsBraille,
		mock_hasUsefulText,
	):
		"""Scroll back should return False when already at start."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropsBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.return_value = [ord(c) for c in "text"[:10]]

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(3)
		for s in siblings:
			s.parent = parent
			s.simpleParent = parent
		navObj = siblings[0]  # First object
		mock_api.getNavigatorObject.return_value = navObj

		# Viewport already showing first object
		self.presentation._visibleObjects = siblings
		self.presentation._navigatorIndex = 0
		self.presentation._parent = parent
		self.presentation._navObj = navObj

		result = self.presentation.scrollBack()

		self.assertFalse(result)


class TestGetParentObject(unittest.TestCase):
	"""Tests for _getParentObject method."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay()
		self.presentation = ScreenCapturePresentation(self.display)

	@patch("addon.presentations.screenCapture.config")
	def test_returns_simple_parent_in_simple_mode(self, mock_config):
		"""Should return simpleParent when simpleReviewMode is True."""
		mock_config.conf = {"reviewCursor": {"simpleReviewMode": True}}

		parent = MockNVDAObject(name="Parent")
		different_parent = MockNVDAObject(name="Different Parent")
		navObj = MockNVDAObject(name="Nav", parent=different_parent)
		navObj.simpleParent = parent

		result = self.presentation._getParentObject(navObj)

		self.assertEqual(result, parent)

	@patch("addon.presentations.screenCapture.config")
	def test_returns_parent_in_normal_mode(self, mock_config):
		"""Should return parent when simpleReviewMode is False."""
		mock_config.conf = {"reviewCursor": {"simpleReviewMode": False}}

		parent = MockNVDAObject(name="Parent")
		simple_parent = MockNVDAObject(name="Simple Parent")
		navObj = MockNVDAObject(name="Nav", parent=parent)
		navObj.simpleParent = simple_parent

		result = self.presentation._getParentObject(navObj)

		self.assertEqual(result, parent)

	@patch("addon.presentations.screenCapture.config")
	def test_returns_none_when_no_parent(self, mock_config):
		"""Should return None when object has no parent."""
		mock_config.conf = {"reviewCursor": {"simpleReviewMode": False}}

		navObj = MockNVDAObject(name="Nav", parent=None)

		result = self.presentation._getParentObject(navObj)

		self.assertIsNone(result)


class TestRenderObjectToBuffer(unittest.TestCase):
	"""Tests for _renderObjectToBuffer method."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay()
		self.presentation = ScreenCapturePresentation(self.display)

	def test_renders_single_line_to_buffer(self):
		"""Should render a single line when content fits."""
		buffer = MagicMock()
		buffer.height = 40
		lineCells = [1, 2, 3, 4, 5]

		with patch("addon.presentations.screenCapture.drawBrailleCellsOnTactileBuffer") as mock_draw:
			result = self.presentation._renderObjectToBuffer(
				buffer,
				lineCells,
				y=0,
				maxLineLength=30,
				maxLinesPerObject=2,
			)

			mock_draw.assert_called_once_with(buffer, 0, 0, [1, 2, 3, 4, 5])
			self.assertEqual(result, 5)  # cellHeight 4 + verticalCellSpacing 1

	def test_renders_multiple_lines_for_long_content(self):
		"""Should wrap content across multiple lines."""
		buffer = MagicMock()
		buffer.height = 40
		lineCells = [1, 2, 3, 4, 5, 6, 7, 8]  # 8 cells, 4 per line

		with patch("addon.presentations.screenCapture.drawBrailleCellsOnTactileBuffer") as mock_draw:
			result = self.presentation._renderObjectToBuffer(
				buffer,
				lineCells,
				y=0,
				maxLineLength=4,
				maxLinesPerObject=2,
			)

			self.assertEqual(mock_draw.call_count, 2)
			mock_draw.assert_any_call(buffer, 0, 0, [1, 2, 3, 4])
			mock_draw.assert_any_call(buffer, 0, 5, [5, 6, 7, 8])
			self.assertEqual(result, 10)  # 2 * line height (cellHeight 4 + spacing 1)

	def test_respects_max_lines_per_object(self):
		"""Should stop at maxLinesPerObject even if content remains."""
		buffer = MagicMock()
		buffer.height = 40
		lineCells = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]  # 12 cells, 4 per line = 3 lines

		with patch("addon.presentations.screenCapture.drawBrailleCellsOnTactileBuffer") as mock_draw:
			result = self.presentation._renderObjectToBuffer(
				buffer,
				lineCells,
				y=0,
				maxLineLength=4,
				maxLinesPerObject=2,
			)

			self.assertEqual(mock_draw.call_count, 2)  # Only 2 lines rendered
			self.assertEqual(result, 10)  # 2 * line height (cellHeight 4 + spacing 1)

	def test_stops_at_buffer_height(self):
		"""Should stop rendering when y exceeds buffer height."""
		buffer = MagicMock()
		buffer.height = 10  # Only fits 1 line (first at y=6, next at 11 >= 10)
		lineCells = [1, 2, 3, 4, 5, 6, 7, 8]  # Would need 2 lines

		with patch("addon.presentations.screenCapture.drawBrailleCellsOnTactileBuffer") as mock_draw:
			result = self.presentation._renderObjectToBuffer(
				buffer,
				lineCells,
				y=6,
				maxLineLength=4,
				maxLinesPerObject=2,
			)

			mock_draw.assert_called_once()  # Only one line fits
			self.assertEqual(result, 11)  # y 6 + line height 5

	def test_handles_empty_content(self):
		"""Should return unchanged y for empty content."""
		buffer = MagicMock()
		buffer.height = 40
		lineCells = []

		with patch("addon.presentations.screenCapture.drawBrailleCellsOnTactileBuffer") as mock_draw:
			result = self.presentation._renderObjectToBuffer(
				buffer,
				lineCells,
				y=6,
				maxLineLength=30,
				maxLinesPerObject=2,
			)

			mock_draw.assert_not_called()
			self.assertEqual(result, 6)  # y unchanged

	def test_line_height_derives_from_display_spacing(self):
		"""Line height follows the display's verticalCellSpacing, not a hardcoded constant.

		FR-003: a display configured with a 2-dot gap steps lines by 6 (cellHeight 4 + 2),
		proving the value is read from the display rather than fixed at 5.
		"""
		display2 = MockDisplay(verticalCellSpacing=2)
		presentation2 = ScreenCapturePresentation(display2)
		buffer = MagicMock()
		buffer.height = 40
		lineCells = [1, 2, 3, 4, 5, 6, 7, 8]

		with patch("addon.presentations.screenCapture.drawBrailleCellsOnTactileBuffer") as mock_draw:
			result = presentation2._renderObjectToBuffer(
				buffer,
				lineCells,
				y=0,
				maxLineLength=4,
				maxLinesPerObject=2,
			)

			mock_draw.assert_any_call(buffer, 0, 6, [5, 6, 7, 8])  # step 6 for a 2-dot gap
			self.assertEqual(result, 12)


class TestFormatLineWithPositionInfo(unittest.TestCase):
	"""Tests for _formatLine using positionInfo."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay()
		self.presentation = ScreenCapturePresentation(self.display)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	def test_shows_position_info_index_when_available(
		self,
		mock_translate,
		mock_getPropsBraille,
		mock_hasUsefulText,
	):
		"""Should show index from positionInfo when available and showNumbers=True."""
		mock_getPropsBraille.side_effect = lambda **kwargs: kwargs.get("name", "")
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text]

		obj = MockNVDAObject(name="Item", positionInfo={"indexInGroup": 5})

		result = self.presentation._formatLine(obj, isActive=False, showNumbers=True)

		# Result should contain "5. " prefix
		result_text = "".join(chr(c) for c in result)
		self.assertIn("5.", result_text)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	def test_no_number_when_no_position_info(self, mock_translate, mock_getPropsBraille, mock_hasUsefulText):
		"""Should not show number when no positionInfo, even if showNumbers=True."""
		mock_getPropsBraille.side_effect = lambda **kwargs: kwargs.get("name", "")
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [ord(c) for c in text]

		obj = MockNVDAObject(name="Item", positionInfo=None)

		result = self.presentation._formatLine(obj, isActive=False, showNumbers=True)

		# Result should not contain number prefix
		result_text = "".join(chr(c) for c in result)
		self.assertNotIn(".", result_text[:10])  # No "X." pattern at start


class TestUpdateViewportForNavigator(unittest.TestCase):
	"""Tests for _updateViewportForNavigator: the sticky page that follows the navigator."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay(physicalNumRows=10)
		self.presentation = ScreenCapturePresentation(self.display)

	def _configureMocks(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
		maxLinesPerObject=1,
		cellsPerObject=10,
	):
		"""Point the patched module globals at simple, predictable values."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = maxLinesPerObject
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [1] * cellsPerObject

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_moving_within_the_page_keeps_it(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should leave the viewport alone and only move the highlight."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)
		page = list(self.presentation._visibleObjects)

		self.presentation._updateViewportForNavigator(page[-1], parent, self.display)

		self.assertEqual(self.presentation._visibleObjects, page)
		self.assertEqual(self.presentation._navigatorIndex, len(page) - 1)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_stepping_past_the_last_object_turns_the_page(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should start a new page at the navigator, with no overlap."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)
		page = list(self.presentation._visibleObjects)
		nextObj = page[-1].next

		self.presentation._updateViewportForNavigator(nextObj, parent, self.display)

		self.assertEqual(self.presentation._visibleObjects[0], nextObj)
		self.assertEqual(self.presentation._navigatorIndex, 0)
		self.assertEqual(set(self.presentation._visibleObjects) & set(page), set())

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_stepping_before_the_first_object_turns_the_page_back(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should end the previous page at the navigator."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[14], parent, self.display)
		page = list(self.presentation._visibleObjects)
		prevObj = page[0].previous

		self.presentation._updateViewportForNavigator(prevObj, parent, self.display)

		self.assertEqual(self.presentation._visibleObjects[-1], prevObj)
		self.assertEqual(
			self.presentation._navigatorIndex,
			len(self.presentation._visibleObjects) - 1,
		)
		self.assertEqual(set(self.presentation._visibleObjects) & set(page), set())

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_jump_off_the_page_recentres(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should recentre when the navigator lands somewhere unrelated."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)

		self.presentation._updateViewportForNavigator(siblings[15], parent, self.display)

		index = self.presentation._navigatorIndex
		self.assertEqual(self.presentation._visibleObjects[index], siblings[15])
		# Centred: objects on both sides of the navigator.
		self.assertGreater(index, 0)
		self.assertLess(index, len(self.presentation._visibleObjects) - 1)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_different_parent_recentres(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should rebuild when the navigator moved into another container."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)

		otherParent = MockNVDAObject(name="Other parent")
		otherChild = MockNVDAObject(name="Other child")
		self.presentation._updateViewportForNavigator(otherChild, otherParent, self.display)

		self.assertEqual(self.presentation._visibleObjects, [otherChild])
		self.assertEqual(self.presentation._navigatorIndex, 0)
		self.assertEqual(self.presentation._parent, otherParent)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_changed_line_budget_recentres(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Should rebuild when the page was measured against another line budget."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
			cellsPerObject=90,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)
		page = list(self.presentation._visibleObjects)

		# The user changes "Maximum lines per object" without leaving the mode: every
		# object now claims three lines instead of one, so the page no longer fits.
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 3

		self.presentation._updateViewportForNavigator(page[1], parent, self.display)

		self.assertLess(len(self.presentation._visibleObjects), len(page))
		self.assertEqual(
			self.presentation._viewportLayout,
			self.presentation._currentViewportLayout(
				self.presentation._calculateAvailableLinesForChildren(self.display, parent),
				self.display,
			),
		)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_object_added_within_the_page_recentres_onto_it(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""A child appearing mid-list is not on the page, so the page rebuilds around it."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)
		page = list(self.presentation._visibleObjects)

		# A new item appears between the second and third object on the page.
		inserted = MockNVDAObject(name="Inserted")
		inserted.previous = inserted.simplePrevious = page[1]
		inserted.next = inserted.simpleNext = page[2]
		page[1].next = page[1].simpleNext = inserted
		page[2].previous = page[2].simplePrevious = inserted

		self.presentation._updateViewportForNavigator(inserted, parent, self.display)

		self.assertIn(inserted, self.presentation._visibleObjects)
		self.assertEqual(
			self.presentation._visibleObjects[self.presentation._navigatorIndex],
			inserted,
		)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_object_appended_after_the_page_turns_the_page(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""A child appended right after the page starts the next one."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(7)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)
		page = list(self.presentation._visibleObjects)

		appended = MockNVDAObject(name="Appended")
		appended.previous = appended.simplePrevious = page[-1]
		page[-1].next = page[-1].simpleNext = appended

		self.presentation._updateViewportForNavigator(appended, parent, self.display)

		self.assertEqual(self.presentation._visibleObjects, [appended])
		self.assertEqual(self.presentation._navigatorIndex, 0)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_object_taller_than_the_budget_stays_visible(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Paging onto an object that cannot fit must not blank the display."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
			maxLinesPerObject=5,
			cellsPerObject=150,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		# The parent claims five of the eight lines, leaving three for its children,
		# so no child fits: the page builders would leave the viewport empty.
		self.assertLess(
			self.presentation._calculateAvailableLinesForChildren(self.display, parent),
			5,
		)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)

		self.presentation._updateViewportForNavigator(siblings[1], parent, self.display)

		self.assertEqual(self.presentation._visibleObjects, [siblings[1]])
		self.assertEqual(self.presentation._navigatorIndex, 0)

	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	def test_walking_a_long_list_pages_in_blocks(
		self,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
	):
		"""Regression for the reported issue: 1-7, 8-14, 15-21, never 2-8."""
		self._configureMocks(
			mock_nvda_config,
			mock_config,
			mock_translate,
			mock_getPropertiesBraille,
			mock_hasUsefulText,
		)
		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		self.presentation._rebuildViewportCenteredOnNavigator(siblings[0], parent, self.display)

		pages = [list(self.presentation._visibleObjects)]
		for obj in siblings[1:]:
			self.presentation._updateViewportForNavigator(obj, parent, self.display)
			page = list(self.presentation._visibleObjects)
			if page != pages[-1]:
				pages.append(page)

		self.assertEqual(
			[[obj.name for obj in page] for page in pages],
			[
				[f"Item {i}" for i in range(1, 8)],
				[f"Item {i}" for i in range(8, 15)],
				[f"Item {i}" for i in range(15, 22)],
			],
		)


class TestRenderFollowsTheNavigator(unittest.TestCase):
	"""Tests for render() driving the sticky page."""

	def setUp(self):
		"""Set up test fixtures."""
		self.display = MockDisplay(physicalNumRows=10)
		self.presentation = ScreenCapturePresentation(self.display)

	@patch("addon.presentations.screenCapture.drawBrailleCellsOnTactileBuffer")
	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	@patch("addon.presentations.screenCapture.api")
	def test_render_pages_instead_of_recentring(
		self,
		mock_api,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
		mock_draw,
	):
		"""Rendering successive navigator objects must page, not slide by one."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 1
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [1] * 10

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		for obj in siblings:
			obj.parent = obj.simpleParent = parent

		# Start in the middle of the list, where the old recentring behaviour would
		# shift the whole page by one object for every step.
		mock_api.getNavigatorObject.return_value = siblings[10]
		self.presentation.render(self.display)
		firstPage = list(self.presentation._visibleObjects)
		indexBefore = self.presentation._navigatorIndex

		mock_api.getNavigatorObject.return_value = siblings[11]
		self.presentation.render(self.display)

		self.assertEqual(self.presentation._visibleObjects, firstPage)
		self.assertEqual(self.presentation._navigatorIndex, indexBefore + 1)

	@patch("addon.presentations.screenCapture.drawBrailleCellsOnTactileBuffer")
	@patch("addon.presentations.screenCapture.braille.NVDAObjectHasUsefulText")
	@patch("addon.presentations.screenCapture.braille.getPropertiesBraille")
	@patch("addon.presentations.screenCapture.translateTextToBraille")
	@patch("addon.presentations.screenCapture.configuration")
	@patch("addon.presentations.screenCapture.config")
	@patch("addon.presentations.screenCapture.api")
	def test_render_recentres_when_the_page_outgrows_the_display(
		self,
		mock_api,
		mock_nvda_config,
		mock_config,
		mock_translate,
		mock_getPropertiesBraille,
		mock_hasUsefulText,
		mock_draw,
	):
		"""A page whose content grew must not leave the navigator off the display."""
		mock_nvda_config.conf = {"reviewCursor": {"simpleReviewMode": False}}
		mock_config.getScreenCaptureMaxLinesPerObject.return_value = 3
		mock_config.getScreenCaptureShowObjectNumbers.return_value = True
		mock_getPropertiesBraille.return_value = "text"
		mock_hasUsefulText.return_value = False
		mock_translate.side_effect = lambda text: [1] * 10

		parent = MockNVDAObject(name="Parent")
		siblings = create_sibling_chain(21)
		for obj in siblings:
			obj.parent = obj.simpleParent = parent

		mock_api.getNavigatorObject.return_value = siblings[0]
		self.presentation.render(self.display)
		page = list(self.presentation._visibleObjects)
		self.assertGreater(len(page), 2)

		# The children's labels grow to three lines each while the page stays put.
		# The parent's stays one line, so the line budget is unchanged and the page
		# is kept rather than rebuilt: only the draw can notice it no longer fits.
		mock_translate.side_effect = lambda text: [1] * 10 if text == "text" else [1] * 90
		mock_api.getNavigatorObject.return_value = page[-1]
		self.presentation.render(self.display)

		self.assertTrue(self.presentation._navigatorWasDrawn)
		self.assertEqual(
			self.presentation._visibleObjects[self.presentation._navigatorIndex],
			page[-1],
		)


if __name__ == "__main__":
	unittest.main()
