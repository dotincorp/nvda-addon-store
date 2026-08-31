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


if __name__ == "__main__":
	unittest.main()
