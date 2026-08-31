# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

"""Unit tests for PresentationManager and related classes."""

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import controlTypes

from addon.extension_points.review_tracking import TriggerReason
from addon.presentations import (
	BraillePresentation,
	BrailleProvider,
	ChartPresentation,
	ChartProvider,
	Presentation,
	PresentationManager,
	PresentationProvider,
	ScreenCapturePresentation,
	ScreenCaptureProvider,
	TablePresentation,
	TableProvider,
)

# Define TABLE_ROLES locally to avoid import issues with addon.utils.data
# These must match the roles defined in addon/utils/data.py
TABLE_ROLES = [
	controlTypes.Role.TABLE,
	controlTypes.Role.DATAGRID,
]


class TestGetUnderlyingObject(unittest.TestCase):
	"""Tests for getUnderlyingObject utility function."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_obj = MagicMock()

	def test_returns_original_object_when_no_tree_interceptor(self):
		"""Test that original object is returned when no treeInterceptor."""
		from addon.presentations.table import getUnderlyingObject

		self.mock_obj.treeInterceptor = None

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, self.mock_obj)
		self.assertFalse(from_ti)

	def test_returns_original_object_when_tree_interceptor_not_ready(self):
		"""Test fallback when TreeInterceptor is not ready."""
		from addon.presentations.table import getUnderlyingObject

		mock_ti = MagicMock()
		mock_ti.isReady = False
		mock_ti.isAlive = True
		self.mock_obj.treeInterceptor = mock_ti

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, self.mock_obj)
		self.assertFalse(from_ti)

	def test_returns_original_object_when_tree_interceptor_not_alive(self):
		"""Test fallback when TreeInterceptor is not alive."""
		from addon.presentations.table import getUnderlyingObject

		mock_ti = MagicMock()
		mock_ti.isReady = True
		mock_ti.isAlive = False
		self.mock_obj.treeInterceptor = mock_ti

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, self.mock_obj)
		self.assertFalse(from_ti)

	@patch("addon.presentations.table.api")
	def test_returns_underlying_object_from_review_position(self, mock_api):
		"""Test that underlying object is returned from review position."""
		from addon.presentations.table import getUnderlyingObject

		mock_ti = MagicMock()
		mock_ti.isReady = True
		mock_ti.isAlive = True
		self.mock_obj.treeInterceptor = mock_ti

		mock_underlying = MagicMock()
		mock_review_pos = MagicMock()
		mock_review_pos.NVDAObjectAtStart = mock_underlying
		mock_api.getReviewPosition.return_value = mock_review_pos

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, mock_underlying)
		self.assertTrue(from_ti)

	@patch("addon.presentations.table.api")
	def test_returns_original_when_review_position_is_none(self, mock_api):
		"""Test fallback when review position is None."""
		from addon.presentations.table import getUnderlyingObject

		mock_ti = MagicMock()
		mock_ti.isReady = True
		mock_ti.isAlive = True
		self.mock_obj.treeInterceptor = mock_ti

		mock_api.getReviewPosition.return_value = None

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, self.mock_obj)
		self.assertFalse(from_ti)

	@patch("addon.presentations.table.api")
	def test_returns_original_when_nvda_object_at_start_is_none(self, mock_api):
		"""Test fallback when NVDAObjectAtStart is None."""
		from addon.presentations.table import getUnderlyingObject

		mock_ti = MagicMock()
		mock_ti.isReady = True
		mock_ti.isAlive = True
		self.mock_obj.treeInterceptor = mock_ti

		mock_review_pos = MagicMock()
		mock_review_pos.NVDAObjectAtStart = None
		mock_api.getReviewPosition.return_value = mock_review_pos

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, self.mock_obj)
		self.assertFalse(from_ti)

	@patch("addon.presentations.table.api")
	def test_handles_not_implemented_error(self, mock_api):
		"""Test that NotImplementedError is handled gracefully."""
		from addon.presentations.table import getUnderlyingObject

		mock_ti = MagicMock()
		mock_ti.isReady = True
		mock_ti.isAlive = True
		self.mock_obj.treeInterceptor = mock_ti

		mock_api.getReviewPosition.side_effect = NotImplementedError

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, self.mock_obj)
		self.assertFalse(from_ti)

	@patch("addon.presentations.table.api")
	def test_handles_attribute_error(self, mock_api):
		"""Test that AttributeError is handled gracefully."""
		from addon.presentations.table import getUnderlyingObject

		mock_ti = MagicMock()
		mock_ti.isReady = True
		mock_ti.isAlive = True
		self.mock_obj.treeInterceptor = mock_ti

		mock_api.getReviewPosition.side_effect = AttributeError

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, self.mock_obj)
		self.assertFalse(from_ti)

	@patch("addon.presentations.table.api")
	def test_handles_runtime_error(self, mock_api):
		"""Test that RuntimeError is handled gracefully."""
		from addon.presentations.table import getUnderlyingObject

		mock_ti = MagicMock()
		mock_ti.isReady = True
		mock_ti.isAlive = True
		self.mock_obj.treeInterceptor = mock_ti

		mock_api.getReviewPosition.side_effect = RuntimeError

		result, from_ti = getUnderlyingObject(self.mock_obj)

		self.assertEqual(result, self.mock_obj)
		self.assertFalse(from_ti)


class MockPresentation(Presentation):
	"""A mock presentation for testing."""

	def __init__(self, name: str = "mock", is_valid: bool = True):
		self._name = name
		self._is_valid = is_valid
		self._scroll_forward_called = False
		self._scroll_back_called = False
		self._render_called = False

	@property
	def name(self) -> str:
		return self._name

	def render(self, display):
		self._render_called = True
		return MagicMock()  # Return a mock buffer

	def scrollForward(self) -> bool:
		self._scroll_forward_called = True
		return True

	def scrollBack(self) -> bool:
		self._scroll_back_called = True
		return True

	def isStillValid(self, triggerReason: TriggerReason | None = None) -> bool:
		return self._is_valid

	def terminate(self) -> None:
		pass


class MockProvider(PresentationProvider):
	"""A mock provider for testing."""

	def __init__(
		self,
		name: str = "mock_provider",
		should_yield: bool = True,
		presentation: MockPresentation | None = None,
	):
		self._name = name
		self._should_yield = should_yield
		self._presentation = presentation or MockPresentation(name=f"{name}_presentation")
		self._call_count = 0
		self._force_call_count = 0

	@property
	def name(self) -> str:
		return self._name

	def canProvide(self, obj) -> bool:
		return self._should_yield

	def _doCreatePresentation(self, obj, display) -> MockPresentation:
		self._call_count += 1
		return self._presentation

	def forceForObject(self, obj, display) -> MockPresentation | None:
		self._force_call_count += 1
		return self._presentation


class MockProviderNoForce(PresentationProvider):
	"""A mock provider that cannot force presentations."""

	def __init__(self, name: str = "no_force_provider"):
		self._name = name
		self._call_count = 0

	@property
	def name(self) -> str:
		return self._name

	def canProvide(self, obj) -> bool:
		return True

	def _doCreatePresentation(self, obj, display) -> MockPresentation:
		self._call_count += 1
		return MockPresentation(name=f"{self.name}_presentation")

	def forceForObject(self, obj, display) -> MockPresentation | None:
		return None


class TestPresentationProtocol(unittest.TestCase):
	"""Tests for the Presentation protocol."""

	def test_mock_presentation_implements_protocol(self):
		"""Test that MockPresentation satisfies the Presentation protocol."""
		presentation = MockPresentation()
		self.assertTrue(isinstance(presentation, Presentation))

	def test_presentation_has_required_attributes(self):
		"""Test that presentation has all required attributes."""
		presentation = MockPresentation(name="test")
		self.assertEqual(presentation.name, "test")
		self.assertTrue(hasattr(presentation, "render"))
		self.assertTrue(hasattr(presentation, "scrollForward"))
		self.assertTrue(hasattr(presentation, "scrollBack"))
		self.assertTrue(hasattr(presentation, "isStillValid"))


class TestPresentationProviderProtocol(unittest.TestCase):
	"""Tests for the PresentationProvider protocol."""

	def test_mock_provider_implements_protocol(self):
		"""Test that MockProvider satisfies the PresentationProvider protocol."""
		provider = MockProvider()
		self.assertTrue(isinstance(provider, PresentationProvider))

	def test_provider_has_required_attributes(self):
		"""Test that provider has all required attributes."""
		provider = MockProvider(name="test_provider")
		self.assertEqual(provider.name, "test_provider")
		self.assertTrue(hasattr(provider, "canProvide"))
		self.assertTrue(hasattr(provider, "createPresentation"))
		self.assertTrue(hasattr(provider, "forceForObject"))


class TestPresentationManagerRegistration(unittest.TestCase):
	"""Tests for provider registration in PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MagicMock()
		self.manager = PresentationManager(self.mock_display)

	def test_register_provider(self):
		"""Test basic provider registration."""
		provider = MockProvider(name="test")
		self.manager.registerProvider(provider)

		self.assertIsNotNone(self.manager.getProviderByName("test"))
		self.assertEqual(self.manager.getProviderByName("test"), provider)

	def test_register_multiple_providers(self):
		"""Test registering multiple providers."""
		provider1 = MockProvider(name="provider1")
		provider2 = MockProvider(name="provider2")

		self.manager.registerProvider(provider1)
		self.manager.registerProvider(provider2)

		self.assertIsNotNone(self.manager.getProviderByName("provider1"))
		self.assertIsNotNone(self.manager.getProviderByName("provider2"))

	def test_register_provider_move_to_start(self):
		"""Test registering provider with moveToStart."""
		provider1 = MockProvider(name="first")
		provider2 = MockProvider(name="second")

		self.manager.registerProvider(provider1)
		self.manager.registerProvider(provider2, moveToStart=True)

		# Both should be registered
		self.assertIsNotNone(self.manager.getProviderByName("first"))
		self.assertIsNotNone(self.manager.getProviderByName("second"))
		# Second provider should be first in the list (moveToStart=True)
		self.assertEqual(self.manager._providers[0], provider2)
		self.assertEqual(self.manager._providers[1], provider1)


class TestPresentationManagerUpdate(unittest.TestCase):
	"""Tests for the update() method of PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MagicMock()
		self.manager = PresentationManager(self.mock_display)
		self.mock_obj = MagicMock()

	def test_update_selects_first_matching_provider(self):
		"""Test that update() selects the first matching provider."""
		provider1 = MockProvider(name="provider1", should_yield=True)
		provider2 = MockProvider(name="provider2", should_yield=True)

		self.manager.registerProvider(provider1)
		self.manager.registerProvider(provider2)

		self.manager.update(self.mock_obj)

		# First provider should have been called
		self.assertEqual(provider1._call_count, 1)
		# Active presentation should be from first provider
		self.assertIsNotNone(self.manager.activePresentation)
		self.assertEqual(self.manager.activePresentation.name, "provider1_presentation")

	def test_update_skips_non_providing_provider(self):
		"""Test that update() skips providers that can't provide."""
		provider1 = MockProvider(name="provider1", should_yield=False)
		provider2 = MockProvider(name="provider2", should_yield=True)

		self.manager.registerProvider(provider1)
		self.manager.registerProvider(provider2)

		self.manager.update(self.mock_obj)

		# Provider1 can't provide, so its createPresentation is never called
		self.assertEqual(provider1._call_count, 0)
		# Provider2 can provide, so its createPresentation is called
		self.assertEqual(provider2._call_count, 1)
		# Active presentation should be from second provider
		self.assertEqual(self.manager.activePresentation.name, "provider2_presentation")

	def test_update_with_no_matching_providers(self):
		"""Test that update() sets no active presentation when none match."""
		provider1 = MockProvider(name="provider1", should_yield=False)
		provider2 = MockProvider(name="provider2", should_yield=False)

		self.manager.registerProvider(provider1)
		self.manager.registerProvider(provider2)

		self.manager.update(self.mock_obj)

		self.assertIsNone(self.manager.activePresentation)
		self.assertFalse(self.manager.hasActivePresentation)


class TestPresentationManagerForce(unittest.TestCase):
	"""Tests for forced presentations in PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MagicMock()
		self.manager = PresentationManager(self.mock_display)
		self.mock_obj = MagicMock()

	def test_force_presentation_success(self):
		"""Test successful forced presentation."""
		provider = MockProvider(name="forceable")
		self.manager.registerProvider(provider)

		result = self.manager.forcePresentation("forceable", self.mock_obj)

		self.assertTrue(result)
		self.assertTrue(self.manager.isForcedMode)
		self.assertIsNotNone(self.manager.forcedPresentation)
		self.assertIsNotNone(self.manager.activePresentation)

	def test_force_presentation_unknown_provider(self):
		"""Test forcing with unknown provider name."""
		result = self.manager.forcePresentation("nonexistent", self.mock_obj)

		self.assertFalse(result)
		self.assertFalse(self.manager.isForcedMode)
		self.assertIsNone(self.manager.forcedPresentation)

	def test_force_presentation_provider_returns_none(self):
		"""Test forcing when provider's forceForObject returns None."""
		provider = MockProviderNoForce(name="no_force")
		self.manager.registerProvider(provider)

		result = self.manager.forcePresentation("no_force", self.mock_obj)

		self.assertFalse(result)
		self.assertFalse(self.manager.isForcedMode)

	def test_forced_presentation_persists_on_update(self):
		"""Test that forced presentation persists across updates."""
		provider = MockProvider(name="forceable")
		self.manager.registerProvider(provider)

		self.manager.forcePresentation("forceable", self.mock_obj)
		initial_presentation = self.manager.activePresentation

		# Call update - forced presentation should persist
		self.manager.update(self.mock_obj)

		self.assertEqual(self.manager.activePresentation, initial_presentation)
		self.assertTrue(self.manager.isForcedMode)

	def test_forced_presentation_cleared_when_invalid(self):
		"""Test that forced presentation is cleared when isStillValid returns False."""
		invalid_presentation = MockPresentation(name="invalid", is_valid=False)
		# Provider that only works for forcing, not auto-detection
		provider = MockProvider(name="forceable", should_yield=False, presentation=invalid_presentation)
		self.manager.registerProvider(provider)

		# Add a fallback provider first (but registered second, so lower priority in chain)
		fallback = MockProvider(name="fallback")
		self.manager.registerProvider(fallback)

		# Force the presentation
		self.manager.forcePresentation("forceable", self.mock_obj)
		self.assertTrue(self.manager.isForcedMode)

		# Update should clear the invalid forced presentation
		self.manager.update(self.mock_obj)

		self.assertFalse(self.manager.isForcedMode)
		self.assertIsNone(self.manager.forcedPresentation)
		# Should have fallen back to the next provider (forceable doesn't yield, fallback does)
		self.assertEqual(self.manager.activePresentation.name, "fallback_presentation")


class TestPresentationManagerClearForced(unittest.TestCase):
	"""Tests for clearForced() in PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MagicMock()
		self.manager = PresentationManager(self.mock_display)
		self.mock_obj = MagicMock()

	def test_clear_forced_returns_to_auto_detect(self):
		"""Test that clearForced returns to auto-detect mode."""
		# Set up providers
		forced_provider = MockProvider(name="forced")
		auto_provider = MockProvider(name="auto")
		self.manager.registerProvider(forced_provider)
		self.manager.registerProvider(auto_provider)

		# Force a presentation
		self.manager.forcePresentation("forced", self.mock_obj)
		self.assertTrue(self.manager.isForcedMode)

		# Clear forced
		self.manager.clearForced()
		self.assertFalse(self.manager.isForcedMode)
		self.assertIsNone(self.manager.forcedPresentation)

		# Update should now use auto-detect
		self.manager.update(self.mock_obj)
		self.assertEqual(self.manager.activePresentation.name, "forced_presentation")

	def test_clear_forced_when_not_forced(self):
		"""Test that clearForced is safe to call when not in forced mode."""
		self.assertFalse(self.manager.isForcedMode)
		self.manager.clearForced()  # Should not raise
		self.assertFalse(self.manager.isForcedMode)


class TestPresentationManagerRenderAndScroll(unittest.TestCase):
	"""Tests for render() and scroll methods in PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MagicMock()
		self.manager = PresentationManager(self.mock_display)
		self.mock_obj = MagicMock()

	def test_render_with_active_presentation(self):
		"""Test rendering with an active presentation."""
		presentation = MockPresentation()
		provider = MockProvider(name="test", presentation=presentation)
		self.manager.registerProvider(provider)
		self.manager.update(self.mock_obj)

		result = self.manager.render()

		self.assertTrue(presentation._render_called)
		self.assertIsNotNone(result)

	def test_render_without_active_presentation(self):
		"""Test rendering without an active presentation."""
		result = self.manager.render()

		self.assertIsNone(result)

	def test_scroll_forward_with_active_presentation(self):
		"""Test scrolling forward with an active presentation."""
		presentation = MockPresentation()
		provider = MockProvider(name="test", presentation=presentation)
		self.manager.registerProvider(provider)
		self.manager.update(self.mock_obj)

		result = self.manager.scrollForward()

		self.assertTrue(result)
		self.assertTrue(presentation._scroll_forward_called)

	def test_scroll_forward_without_active_presentation(self):
		"""Test scrolling forward without an active presentation."""
		result = self.manager.scrollForward()

		self.assertFalse(result)

	def test_scroll_back_with_active_presentation(self):
		"""Test scrolling back with an active presentation."""
		presentation = MockPresentation()
		provider = MockProvider(name="test", presentation=presentation)
		self.manager.registerProvider(provider)
		self.manager.update(self.mock_obj)

		result = self.manager.scrollBack()

		self.assertTrue(result)
		self.assertTrue(presentation._scroll_back_called)

	def test_scroll_back_without_active_presentation(self):
		"""Test scrolling back without an active presentation."""
		result = self.manager.scrollBack()

		self.assertFalse(result)


class TestPresentationManagerProperties(unittest.TestCase):
	"""Tests for PresentationManager properties."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MagicMock()
		self.manager = PresentationManager(self.mock_display)

	def test_initial_state(self):
		"""Test initial state of PresentationManager."""
		self.assertIsNone(self.manager.activePresentation)
		self.assertIsNone(self.manager.forcedPresentation)
		self.assertFalse(self.manager.hasActivePresentation)
		self.assertFalse(self.manager.isForcedMode)

	def test_display_property(self):
		"""Test that display is properly stored."""
		self.assertEqual(self.manager.display, self.mock_display)


class MockBrailleBuffer:
	"""A mock braille buffer for testing BraillePresentation."""

	def __init__(
		self,
		cells: list[int] | None = None,
		cursor_pos: int | None = None,
	):
		self._cells = cells if cells is not None else [0x41, 0x42, 0x43]  # "ABC" in braille-ish
		self._cursor_pos = cursor_pos
		self._scroll_forward_called = False
		self._scroll_back_called = False

	@property
	def windowBrailleCells(self) -> list[int]:
		return self._cells

	@property
	def cursorWindowPos(self) -> int | None:
		return self._cursor_pos

	def scrollForward(self) -> None:
		self._scroll_forward_called = True

	def scrollBack(self) -> None:
		self._scroll_back_called = True


class MockDisplay:
	"""A mock display for testing presentations."""

	def __init__(
		self,
		numCols: int = 40,
		numRows: int = 1,
		physicalNumCols: int = 60,
		physicalNumRows: int = 40,
		cellHeight: int = 4,
		horizontalCellSpacing: int = 1,
		verticalCellSpacing: int = 1,
	):
		self.numCols = numCols
		self.numRows = numRows
		self.physicalNumCols = physicalNumCols
		self.physicalNumRows = physicalNumRows
		self.numCells = numCols * numRows
		self.cellHeight = cellHeight
		self.horizontalCellSpacing = horizontalCellSpacing
		self.verticalCellSpacing = verticalCellSpacing

	def getBrailleCellPosition(self, cellIndex: int) -> tuple[int, int]:
		"""Mock implementation of getBrailleCellPosition."""
		from tactile.braille import CELL_WIDTH

		row = cellIndex // self.numCols
		col = cellIndex % self.numCols
		x = col * (CELL_WIDTH + self.horizontalCellSpacing)
		y = row * (self.cellHeight + self.verticalCellSpacing)
		return x, y

	def drawBrailleCells(self, buffer, cells: list[int]) -> None:
		"""Mock implementation of drawBrailleCells."""
		# This is a mock - it doesn't need to do anything for tests


class TestBraillePresentationProtocol(unittest.TestCase):
	"""Tests for BraillePresentation implementing the Presentation protocol."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_buffer = MockBrailleBuffer()
		self.mock_display = MockDisplay()
		self.presentation = BraillePresentation(self.mock_display)

	def test_implements_presentation_protocol(self):
		"""Test that BraillePresentation implements the Presentation protocol."""
		self.assertTrue(isinstance(self.presentation, Presentation))

	def test_has_name_attribute(self):
		"""Test that BraillePresentation has a name attribute."""
		self.assertEqual(self.presentation.name, "braille")

	def test_has_required_methods(self):
		"""Test that BraillePresentation has all required methods."""
		self.assertTrue(hasattr(self.presentation, "render"))
		self.assertTrue(hasattr(self.presentation, "scrollForward"))
		self.assertTrue(hasattr(self.presentation, "scrollBack"))
		self.assertTrue(hasattr(self.presentation, "isStillValid"))


class TestBraillePresentationIsStillValid(unittest.TestCase):
	"""Tests for BraillePresentation.isStillValid()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_buffer = MockBrailleBuffer()
		self.mock_display = MockDisplay()
		self.presentation = BraillePresentation(self.mock_display)

	def test_is_still_valid_returns_true_when_source_is_nvda(self):
		"""When ``brailleSource`` is ``NVDA``, BraillePresentation stays valid.

		Feature 017 made ``isStillValid()`` config-aware so a mid-session
		``brailleSource`` flip causes the manager to re-pick via providers
		on the next focus event. Under the ``NVDA`` setting (selected
		here) the presentation's mode matches; isStillValid returns True.
		"""
		from unittest.mock import patch

		from addon.configuration import BrailleSource

		with patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.NVDA):
			self.assertTrue(self.presentation.isStillValid())

	def test_is_still_valid_consistently_returns_true_when_source_is_nvda(self):
		"""Repeat calls under NVDA source consistently return True."""
		from unittest.mock import patch

		from addon.configuration import BrailleSource

		with patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.NVDA):
			self.assertTrue(self.presentation.isStillValid())
			self.assertTrue(self.presentation.isStillValid())
			self.assertTrue(self.presentation.isStillValid())


class TestBraillePresentationScroll(unittest.TestCase):
	"""Tests for BraillePresentation scroll methods."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_buffer = MockBrailleBuffer()
		self.mock_display = MockDisplay()
		self.presentation = BraillePresentation(self.mock_display)

	def test_scroll_forward_delegates_to_buffer(self):
		"""Test that scrollForward() delegates to the internal buffer."""
		# Replace internal buffer with mock to verify delegation
		self.presentation._buffer = self.mock_buffer

		result = self.presentation.scrollForward()

		self.assertTrue(result)
		self.assertTrue(self.mock_buffer._scroll_forward_called)

	def test_scroll_back_delegates_to_buffer(self):
		"""Test that scrollBack() delegates to the internal buffer."""
		# Replace internal buffer with mock to verify delegation
		self.presentation._buffer = self.mock_buffer

		result = self.presentation.scrollBack()

		self.assertTrue(result)
		self.assertTrue(self.mock_buffer._scroll_back_called)

	def test_scroll_forward_returns_true(self):
		"""Test that scrollForward() returns True."""
		result = self.presentation.scrollForward()
		self.assertTrue(result)

	def test_scroll_back_returns_true(self):
		"""Test that scrollBack() returns True."""
		result = self.presentation.scrollBack()
		self.assertTrue(result)


class TestBraillePresentationRender(unittest.TestCase):
	"""Tests for BraillePresentation.render()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_buffer = MockBrailleBuffer()
		self.mock_display = MockDisplay()
		self.presentation = BraillePresentation(self.mock_display)

	def test_render_returns_buffer(self):
		"""Test that render() returns a DpTactileGraphicsBuffer."""
		from addon.brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer

		result = self.presentation.render(self.mock_display)

		self.assertIsInstance(result, DpTactileGraphicsBuffer)

	def test_render_creates_buffer_with_correct_dimensions(self):
		"""Test that render() creates a buffer with the display's physical dimensions."""
		result = self.presentation.render(self.mock_display)

		# Physical dimensions are 60x40 cells, each cell is 2x4 pixels
		expected_width = self.mock_display.physicalNumCols * 2  # 60 * 2 = 120
		expected_height = self.mock_display.physicalNumRows * 4  # 40 * 4 = 160
		self.assertEqual(result.width, expected_width)
		self.assertEqual(result.height, expected_height)


class TestBrailleProviderProtocol(unittest.TestCase):
	"""Tests for BrailleProvider implementing the PresentationProvider protocol."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_buffer = MockBrailleBuffer()
		self.provider = BrailleProvider()

	def test_implements_provider_protocol(self):
		"""Test that BrailleProvider implements the PresentationProvider protocol."""
		self.assertTrue(isinstance(self.provider, PresentationProvider))

	def test_has_name_attribute(self):
		"""Test that BrailleProvider has a name attribute."""
		self.assertEqual(self.provider.name, "braille")

	def test_has_canProvide_method(self):
		"""Test that BrailleProvider has canProvide method."""
		self.assertTrue(hasattr(self.provider, "canProvide"))
		self.assertTrue(callable(self.provider.canProvide))

	def test_has_createPresentation_method(self):
		"""Test that BrailleProvider has createPresentation method."""
		self.assertTrue(hasattr(self.provider, "createPresentation"))
		self.assertTrue(callable(self.provider.createPresentation))

	def test_has_force_for_object_method(self):
		"""Test that BrailleProvider has forceForObject method."""
		self.assertTrue(hasattr(self.provider, "forceForObject"))


class TestBrailleProviderYields(unittest.TestCase):
	"""Tests for BrailleProvider yielding presentations."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_buffer = MockBrailleBuffer()
		self.mock_display = MockDisplay()
		self.mock_obj = MagicMock()

	def test_canProvide_always_returns_true(self):
		"""Test that canProvide always returns True (braille is always available)."""
		provider = BrailleProvider()

		self.assertTrue(provider.canProvide(self.mock_obj))

	def test_createPresentation_returns_braille_presentation(self):
		"""Test that createPresentation returns a BraillePresentation."""
		provider = BrailleProvider()

		presentation = provider.createPresentation(self.mock_obj, self.mock_display)

		self.assertIsInstance(presentation, BraillePresentation)

	def test_createPresentation_returns_fresh_instance_each_call(self):
		"""``BrailleProvider`` constructs a fresh presentation every call after
		feature 017 (research §G — caching removed so config swaps apply on
		the next call).
		"""
		provider = BrailleProvider()

		presentation1 = provider.createPresentation(self.mock_obj, self.mock_display)
		presentation2 = provider.createPresentation(self.mock_obj, self.mock_display)

		# Each call constructs a fresh instance — no cache.
		self.assertIsNot(presentation1, presentation2)


class TestBrailleProviderForceForObject(unittest.TestCase):
	"""Tests for BrailleProvider.forceForObject()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_buffer = MockBrailleBuffer()
		self.mock_display = MockDisplay()
		self.mock_obj = MagicMock()

	def test_force_for_object_returns_presentation(self):
		"""Test that forceForObject returns a BraillePresentation."""
		provider = BrailleProvider()

		result = provider.forceForObject(self.mock_obj, self.mock_display)

		self.assertIsInstance(result, BraillePresentation)

	def test_force_for_object_returns_fresh_instance_each_call(self):
		"""``forceForObject`` constructs a fresh presentation every call after
		feature 017 — same no-cache contract as ``createPresentation``."""
		provider = BrailleProvider()

		result1 = provider.forceForObject(self.mock_obj, self.mock_display)
		result2 = provider.forceForObject(self.mock_obj, self.mock_display)

		self.assertIsNot(result1, result2)


class TestBrailleProviderIntegration(unittest.TestCase):
	"""Integration tests for BrailleProvider with PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_buffer = MockBrailleBuffer()
		self.mock_display = MockDisplay()
		self.mock_obj = MagicMock()

	def test_provider_works_with_presentation_manager(self):
		"""Test that BrailleProvider works correctly with PresentationManager."""
		provider = BrailleProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Update with an object
		manager.update(self.mock_obj)

		# Should have an active presentation
		self.assertTrue(manager.hasActivePresentation)
		self.assertEqual(manager.activePresentation.name, "braille")

	def test_braille_presentation_stays_valid_in_manager_when_source_is_nvda(self):
		"""Forced braille presentation remains valid across updates under
		the ``NVDA`` brailleSource setting.

		Feature 017 made ``BraillePresentation.isStillValid()`` config-aware
		— it returns False when the user switches to LIBRARY mode (so the
		manager re-picks the active presentation). Under NVDA source the
		presentation stays valid; the forced-presentation guarantee holds.
		"""
		from unittest.mock import patch

		from addon.configuration import BrailleSource

		provider = BrailleProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		with patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.NVDA):
			# Force the braille presentation.
			manager.forcePresentation("braille", self.mock_obj)
			self.assertTrue(manager.isForcedMode)
			# Update multiple times — should remain valid.
			manager.update(self.mock_obj)
			self.assertTrue(manager.isForcedMode)
			manager.update(self.mock_obj)
			self.assertTrue(manager.isForcedMode)


class MockTableObject:
	"""A mock table NVDAObject for testing TablePresentation."""

	def __init__(
		self,
		role=controlTypes.Role.TABLE,
		name: str = "Test Table",
		children: list | None = None,
		location=None,
	):
		self.role = role
		self.name = name
		self.description = ""
		self.children = children if children is not None else []
		self.parent = None
		self.location = location
		self._currentRow = None
		self._currentCol = None


class MockTableDisplay:
	"""A mock display for testing table presentations."""

	def __init__(
		self,
		numCols: int = 40,
		numRows: int = 1,
		physicalNumCols: int = 60,
		physicalNumRows: int = 40,
		horizontalCellSpacing: int = 1,
		verticalCellSpacing: int = 2,
	):
		self.numCols = numCols
		self.numRows = numRows
		self.physicalNumCols = physicalNumCols
		self.physicalNumRows = physicalNumRows
		self.numCells = numCols * numRows
		self.horizontalCellSpacing = horizontalCellSpacing
		self.verticalCellSpacing = verticalCellSpacing


class MockLocation:
	"""A mock location rectangle for bounds checking."""

	def __init__(self, left: int, top: int, right: int, bottom: int):
		self.left = left
		self.top = top
		self.right = right
		self.bottom = bottom


class TestTablePresentationProtocol(unittest.TestCase):
	"""Tests for TablePresentation implementing the Presentation protocol."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_table = MockTableObject()
		self.mock_display = MockTableDisplay()

	@patch("addon.presentations.table.Table")
	def test_implements_presentation_protocol(self, mock_table_class):
		"""Test that TablePresentation implements the Presentation protocol."""
		mock_table_class.return_value = MagicMock()
		presentation = TablePresentation(self.mock_table, self.mock_display)
		self.assertTrue(isinstance(presentation, Presentation))

	@patch("addon.presentations.table.Table")
	def test_uses_display_vertical_cell_spacing(self, mock_table_class):
		"""Table data is built with the display's verticalCellSpacing (FR-004).

		The table presentation must derive its row gap from the single source of
		truth (``display.verticalCellSpacing``), so a display configured for a
		1-dot gap yields ``vCellPadding=1`` rather than a hardcoded value.
		"""
		mock_table_class.return_value = MagicMock()
		display = MockTableDisplay(verticalCellSpacing=1)
		TablePresentation(self.mock_table, display)
		_, kwargs = mock_table_class.call_args
		self.assertEqual(kwargs["vCellPadding"], 1)

	@patch("addon.presentations.table.Table")
	def test_has_name_attribute(self, mock_table_class):
		"""Test that TablePresentation has a name attribute."""
		mock_table_class.return_value = MagicMock()
		presentation = TablePresentation(self.mock_table, self.mock_display)
		self.assertEqual(presentation.name, "table")

	@patch("addon.presentations.table.Table")
	def test_has_required_methods(self, mock_table_class):
		"""Test that TablePresentation has all required methods."""
		mock_table_class.return_value = MagicMock()
		presentation = TablePresentation(self.mock_table, self.mock_display)
		self.assertTrue(hasattr(presentation, "render"))
		self.assertTrue(hasattr(presentation, "scrollForward"))
		self.assertTrue(hasattr(presentation, "scrollBack"))
		self.assertTrue(hasattr(presentation, "isStillValid"))

	@patch("addon.presentations.table.Table")
	def test_stores_table_obj(self, mock_table_class):
		"""Test that TablePresentation stores the table object."""
		mock_table_class.return_value = MagicMock()
		presentation = TablePresentation(self.mock_table, self.mock_display)
		self.assertEqual(presentation.tableObj, self.mock_table)

	@patch("addon.presentations.table.Table")
	def test_stores_forced_from(self, mock_table_class):
		"""Test that TablePresentation stores the forcedFrom object."""
		mock_table_class.return_value = MagicMock()
		forced_from = MagicMock()
		presentation = TablePresentation(self.mock_table, self.mock_display, forcedFrom=forced_from)
		self.assertEqual(presentation._forcedFrom, forced_from)


class TestTablePresentationRender(unittest.TestCase):
	"""Tests for TablePresentation.render()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_table = MockTableObject()
		self.mock_display = MockTableDisplay()

	@patch("addon.presentations.table.Table")
	def test_render_returns_buffer(self, mock_table_class):
		"""Test that render() returns a DpTactileGraphicsBuffer."""
		from addon.brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer

		mock_table_class.return_value = MagicMock()
		presentation = TablePresentation(self.mock_table, self.mock_display)
		result = presentation.render(self.mock_display)

		self.assertIsInstance(result, DpTactileGraphicsBuffer)

	@patch("addon.presentations.table.Table")
	def test_render_calls_table_draw(self, mock_table_class):
		"""Test that render() calls the Table.draw() method."""
		mock_table_data = MagicMock()
		mock_table_class.return_value = mock_table_data
		presentation = TablePresentation(self.mock_table, self.mock_display)

		presentation.render(self.mock_display)

		mock_table_data.draw.assert_called_once()

	@patch("addon.presentations.table.Table")
	def test_render_creates_buffer_with_correct_dimensions(self, mock_table_class):
		"""Test that render() creates a buffer with correct dimensions."""
		mock_table_class.return_value = MagicMock()
		presentation = TablePresentation(self.mock_table, self.mock_display)
		result = presentation.render(self.mock_display)

		# Physical dimensions are 60x40 cells, each cell is 2x4 pixels
		expected_width = self.mock_display.physicalNumCols * 2  # 60 * 2 = 120
		expected_height = self.mock_display.physicalNumRows * 4  # 40 * 4 = 160
		self.assertEqual(result.width, expected_width)
		self.assertEqual(result.height, expected_height)


class TestTablePresentationScroll(unittest.TestCase):
	"""Tests for TablePresentation scroll methods."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_table = MockTableObject()
		self.mock_display = MockTableDisplay()

	@patch("addon.presentations.table.Table")
	def test_scroll_forward_delegates_to_table(self, mock_table_class):
		"""Test that scrollForward() delegates to the table."""
		mock_table_data = MagicMock()
		mock_table_data.scrollForward.return_value = True
		mock_table_class.return_value = mock_table_data
		presentation = TablePresentation(self.mock_table, self.mock_display)

		result = presentation.scrollForward()

		self.assertTrue(result)
		mock_table_data.scrollForward.assert_called_once()

	@patch("addon.presentations.table.Table")
	def test_scroll_back_delegates_to_table(self, mock_table_class):
		"""Test that scrollBack() delegates to the table."""
		mock_table_data = MagicMock()
		mock_table_data.scrollBack.return_value = True
		mock_table_class.return_value = mock_table_data
		presentation = TablePresentation(self.mock_table, self.mock_display)

		result = presentation.scrollBack()

		self.assertTrue(result)
		mock_table_data.scrollBack.assert_called_once()

	@patch("addon.presentations.table.Table")
	def test_scroll_forward_returns_false_at_end(self, mock_table_class):
		"""Test that scrollForward() returns False when at end."""
		mock_table_data = MagicMock()
		mock_table_data.scrollForward.return_value = False
		mock_table_class.return_value = mock_table_data
		presentation = TablePresentation(self.mock_table, self.mock_display)

		result = presentation.scrollForward()

		self.assertFalse(result)

	@patch("addon.presentations.table.Table")
	def test_scroll_back_returns_false_at_beginning(self, mock_table_class):
		"""Test that scrollBack() returns False when at beginning."""
		mock_table_data = MagicMock()
		mock_table_data.scrollBack.return_value = False
		mock_table_class.return_value = mock_table_data
		presentation = TablePresentation(self.mock_table, self.mock_display)

		result = presentation.scrollBack()

		self.assertFalse(result)


class TestTablePresentationIsStillValid(unittest.TestCase):
	"""Tests for TablePresentation.isStillValid()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_table = MockTableObject()
		self.mock_display = MockTableDisplay()

	@patch("addon.presentations.table.api")
	@patch("addon.presentations.table.Table")
	def test_is_still_valid_with_table_property(self, mock_table_class, mock_api):
		"""Test isStillValid() when navObj.table equals the table object."""
		mock_table_class.return_value = MagicMock()
		presentation = TablePresentation(self.mock_table, self.mock_display)

		# Create a mock navigator object that has a table property
		mock_nav_obj = MagicMock()
		mock_nav_obj.table = self.mock_table
		mock_nav_obj.treeInterceptor = None  # No TreeInterceptor in this test
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		result = presentation.isStillValid()

		self.assertTrue(result)

	@patch("addon.presentations.table.api")
	@patch("addon.presentations.table.Table")
	def test_is_still_valid_with_bounds_check(self, mock_table_class, mock_api):
		"""Test isStillValid() fallback to bounds check."""
		mock_table_class.return_value = MagicMock()

		# Set up table with location
		self.mock_table.location = MockLocation(0, 0, 100, 100)
		presentation = TablePresentation(self.mock_table, self.mock_display)

		# Create a mock navigator object without table property but with location inside table
		mock_nav_obj = MagicMock()
		mock_nav_obj.table = property(lambda self: None)  # Raises AttributeError
		type(mock_nav_obj).table = PropertyMock(side_effect=AttributeError)
		mock_nav_obj.location = MockLocation(10, 10, 50, 50)  # Inside table bounds
		mock_nav_obj.treeInterceptor = None  # No TreeInterceptor in this test
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		result = presentation.isStillValid()

		self.assertTrue(result)

	@patch("addon.presentations.table.api")
	@patch("addon.presentations.table.Table")
	def test_is_still_valid_returns_false_outside_bounds(self, mock_table_class, mock_api):
		"""Test isStillValid() returns False when navigator is outside bounds."""
		mock_table_class.return_value = MagicMock()

		# Set up table with location
		self.mock_table.location = MockLocation(0, 0, 100, 100)
		presentation = TablePresentation(self.mock_table, self.mock_display)

		# Create a mock navigator object outside table bounds
		mock_nav_obj = MagicMock()
		type(mock_nav_obj).table = PropertyMock(side_effect=AttributeError)
		mock_nav_obj.location = MockLocation(200, 200, 300, 300)  # Outside table bounds
		mock_nav_obj.treeInterceptor = None  # No TreeInterceptor in this test
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		result = presentation.isStillValid()

		self.assertFalse(result)

	@patch("addon.presentations.table.api")
	@patch("addon.presentations.table.Table")
	def test_is_still_valid_returns_false_without_location(self, mock_table_class, mock_api):
		"""Test isStillValid() returns False when no location available."""
		mock_table_class.return_value = MagicMock()

		# No location on table
		self.mock_table.location = None
		presentation = TablePresentation(self.mock_table, self.mock_display)

		# Create a mock navigator object without table property and no location
		mock_nav_obj = MagicMock()
		type(mock_nav_obj).table = PropertyMock(side_effect=AttributeError)
		mock_nav_obj.location = None
		mock_nav_obj.treeInterceptor = None  # No TreeInterceptor in this test
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		result = presentation.isStillValid()

		self.assertFalse(result)

	@patch("addon.presentations.table.api")
	@patch("addon.presentations.table.Table")
	def test_is_still_valid_handles_not_implemented_error(self, mock_table_class, mock_api):
		"""Test isStillValid() handles NotImplementedError from table property."""
		mock_table_class.return_value = MagicMock()

		# Set up table with location for fallback
		self.mock_table.location = MockLocation(0, 0, 100, 100)
		presentation = TablePresentation(self.mock_table, self.mock_display)

		# Create a mock navigator object that raises NotImplementedError
		mock_nav_obj = MagicMock()
		type(mock_nav_obj).table = PropertyMock(side_effect=NotImplementedError)
		mock_nav_obj.location = MockLocation(10, 10, 50, 50)  # Inside table bounds
		mock_nav_obj.treeInterceptor = None  # No TreeInterceptor in this test
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		# Should fall back to bounds check and return True
		result = presentation.isStillValid()

		self.assertTrue(result)


class TestTablePresentationGetRelevantObject(unittest.TestCase):
	"""Tests for TablePresentation._getRelevantObject()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_table = MockTableObject()
		self.mock_display = MockTableDisplay()

	@patch("addon.presentations.table.getUnderlyingObject")
	@patch("addon.presentations.table.api")
	@patch("addon.presentations.table.Table")
	def test_get_relevant_object_uses_utility(self, mock_table_class, mock_api, mock_get_underlying):
		"""Test that _getRelevantObject uses getUnderlyingObject utility."""
		mock_table_class.return_value = MagicMock()
		mock_nav_obj = MagicMock()
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		mock_underlying = MagicMock()
		mock_get_underlying.return_value = (mock_underlying, True)

		presentation = TablePresentation(self.mock_table, self.mock_display)
		result = presentation._getRelevantObject()

		mock_get_underlying.assert_called_once_with(mock_nav_obj)
		self.assertEqual(result, mock_underlying)

	@patch("addon.presentations.table.getUnderlyingObject")
	@patch("addon.presentations.table.api")
	@patch("addon.presentations.table.Table")
	def test_get_relevant_object_returns_nav_obj_when_no_tree_interceptor(
		self,
		mock_table_class,
		mock_api,
		mock_get_underlying,
	):
		"""Test _getRelevantObject returns nav object when no TreeInterceptor."""
		mock_table_class.return_value = MagicMock()
		mock_nav_obj = MagicMock()
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		mock_get_underlying.return_value = (mock_nav_obj, False)

		presentation = TablePresentation(self.mock_table, self.mock_display)
		result = presentation._getRelevantObject()

		self.assertEqual(result, mock_nav_obj)


class TestTableProviderProtocol(unittest.TestCase):
	"""Tests for TableProvider implementing the PresentationProvider protocol."""

	def test_implements_provider_protocol(self):
		"""Test that TableProvider implements the PresentationProvider protocol."""
		provider = TableProvider()
		self.assertTrue(isinstance(provider, PresentationProvider))

	def test_has_name_attribute(self):
		"""Test that TableProvider has a name attribute."""
		provider = TableProvider()
		self.assertEqual(provider.name, "table")

	def test_has_canProvide_method(self):
		"""Test that TableProvider has canProvide method."""
		provider = TableProvider()
		self.assertTrue(hasattr(provider, "canProvide"))
		self.assertTrue(callable(provider.canProvide))

	def test_has_createPresentation_method(self):
		"""Test that TableProvider has createPresentation method."""
		provider = TableProvider()
		self.assertTrue(hasattr(provider, "createPresentation"))
		self.assertTrue(callable(provider.createPresentation))

	def test_has_force_for_object_method(self):
		"""Test that TableProvider has forceForObject method."""
		provider = TableProvider()
		self.assertTrue(hasattr(provider, "forceForObject"))

	def test_has_max_parent_scan_depth(self):
		"""Test that TableProvider has MAX_PARENT_SCAN_DEPTH."""
		provider = TableProvider()
		self.assertEqual(provider.MAX_PARENT_SCAN_DEPTH, 20)


class TestTableProviderDetection(unittest.TestCase):
	"""Tests for TableProvider detection logic."""

	def setUp(self):
		"""Set up test fixtures."""
		self.provider = TableProvider()
		self.mock_display = MockTableDisplay()

	@patch("addon.presentations.table.Table")
	def test_createPresentation_for_table_role(self, mock_table_class):
		"""Test that createPresentation returns a presentation for table role objects."""
		mock_table_class.return_value = MagicMock()
		mock_obj = MockTableObject(role=controlTypes.Role.TABLE)

		# Mock _getObjectFromReviewPosition to return None (no review position in tests)
		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=None):
			presentation = self.provider.createPresentation(mock_obj, self.mock_display)

		self.assertIsInstance(presentation, TablePresentation)

	@patch("addon.presentations.table.Table")
	def test_createPresentation_for_datagrid_role(self, mock_table_class):
		"""Test that createPresentation returns a presentation for datagrid role objects."""
		mock_table_class.return_value = MagicMock()
		mock_obj = MockTableObject(role=controlTypes.Role.DATAGRID)

		# Mock _getObjectFromReviewPosition to return None (no review position in tests)
		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=None):
			presentation = self.provider.createPresentation(mock_obj, self.mock_display)

		self.assertIsInstance(presentation, TablePresentation)

	def test_canProvide_returns_false_for_non_table(self):
		"""Test canProvide returns False for non-table objects."""
		mock_obj = MockTableObject(role=controlTypes.Role.BUTTON)

		self.assertFalse(self.provider.canProvide(mock_obj))

	def test_canProvide_returns_true_for_table_roles(self):
		"""Test canProvide returns True for table roles."""
		for role in TABLE_ROLES:
			mock_obj = MockTableObject(role=role)
			self.assertTrue(self.provider.canProvide(mock_obj))


class TestTableProviderForceForObject(unittest.TestCase):
	"""Tests for TableProvider.forceForObject()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.provider = TableProvider()
		self.mock_display = MockTableDisplay()

	@patch("addon.presentations.table.Table")
	def test_force_for_object_finds_table_parent(self, mock_table_class):
		"""Test that forceForObject finds a table in parent chain."""
		mock_table_class.return_value = MagicMock()

		# Create a parent chain: button -> row -> table
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)
		row_obj = MockTableObject(role=controlTypes.Role.TABLEROW)
		row_obj.parent = table_obj
		button_obj = MockTableObject(role=controlTypes.Role.BUTTON)
		button_obj.parent = row_obj

		result = self.provider.forceForObject(button_obj, self.mock_display)

		self.assertIsNotNone(result)
		self.assertIsInstance(result, TablePresentation)
		self.assertEqual(result.tableObj, table_obj)
		self.assertEqual(result._forcedFrom, button_obj)

	@patch("addon.presentations.table.Table")
	def test_force_for_object_returns_none_without_table_parent(self, mock_table_class):
		"""Test that forceForObject returns None when no table in parents."""
		mock_table_class.return_value = MagicMock()

		# Create a chain without a table
		button_obj = MockTableObject(role=controlTypes.Role.BUTTON)
		button_obj.parent = MockTableObject(role=controlTypes.Role.WINDOW)

		result = self.provider.forceForObject(button_obj, self.mock_display)

		self.assertIsNone(result)

	@patch("addon.presentations.table.Table")
	def test_force_for_object_respects_max_depth(self, mock_table_class):
		"""Test that forceForObject respects MAX_PARENT_SCAN_DEPTH."""
		mock_table_class.return_value = MagicMock()

		# Create a chain deeper than MAX_PARENT_SCAN_DEPTH
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)

		# Build a chain of 25 objects (more than MAX_PARENT_SCAN_DEPTH=20)
		current = table_obj
		for i in range(25):
			new_obj = MockTableObject(role=controlTypes.Role.UNKNOWN)
			new_obj.parent = current
			current = new_obj

		# The deepest object shouldn't find the table
		result = self.provider.forceForObject(current, self.mock_display)

		self.assertIsNone(result)

	@patch("addon.presentations.table.Table")
	def test_force_for_object_finds_table_at_max_depth(self, mock_table_class):
		"""Test that forceForObject finds table at exactly MAX_PARENT_SCAN_DEPTH."""
		mock_table_class.return_value = MagicMock()

		# Create a chain of exactly MAX_PARENT_SCAN_DEPTH objects with table at the end
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)

		# Build a chain of 19 objects (so table is at depth 19, within 20)
		current = table_obj
		for i in range(19):
			new_obj = MockTableObject(role=controlTypes.Role.UNKNOWN)
			new_obj.parent = current
			current = new_obj

		# Mock _getObjectFromReviewPosition to return None (no review position in tests)
		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=None):
			result = self.provider.forceForObject(current, self.mock_display)

		self.assertIsNotNone(result)
		self.assertEqual(result.tableObj, table_obj)

	@patch("addon.presentations.table.Table")
	def test_force_for_object_handles_none_parent(self, mock_table_class):
		"""Test that forceForObject handles None parent gracefully."""
		mock_table_class.return_value = MagicMock()

		# Object with no parent
		obj = MockTableObject(role=controlTypes.Role.BUTTON)
		obj.parent = None

		result = self.provider.forceForObject(obj, self.mock_display)

		self.assertIsNone(result)


class TestTableProviderFindTable(unittest.TestCase):
	"""Tests for TableProvider._findTable()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.provider = TableProvider()

	def test_find_table_returns_self_if_table(self):
		"""Test that _findTable returns the object itself if it's a table."""
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)

		result = self.provider._findTable(table_obj)

		self.assertEqual(result, table_obj)

	def test_find_table_returns_datagrid(self):
		"""Test that _findTable returns a datagrid from parent."""
		datagrid_obj = MockTableObject(role=controlTypes.Role.DATAGRID)
		button_obj = MockTableObject(role=controlTypes.Role.BUTTON)
		button_obj.parent = datagrid_obj

		result = self.provider._findTable(button_obj)

		self.assertEqual(result, datagrid_obj)

	def test_find_table_returns_none_for_no_table(self):
		"""Test that _findTable returns None when no table found."""
		button_obj = MockTableObject(role=controlTypes.Role.BUTTON)
		window_obj = MockTableObject(role=controlTypes.Role.WINDOW)
		button_obj.parent = window_obj
		window_obj.parent = None

		result = self.provider._findTable(button_obj)

		self.assertIsNone(result)

	def test_find_table_uses_obj_table_attribute(self):
		"""Test that _findTable uses obj.table attribute when available."""
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)
		cell_obj = MockTableObject(role=controlTypes.Role.TABLECELL)
		cell_obj.table = table_obj

		result = self.provider._findTable(cell_obj)

		self.assertEqual(result, table_obj)

	def test_find_table_ignores_table_attribute_with_non_table_role(self):
		"""Regression: obj.table may resolve to a non-table object.

		The Windows 11 alt+tab switcher is a LIST (role 14) that exposes the
		UIA Grid pattern, so its items report a containing ``.table`` whose role
		is LIST, not TABLE/DATAGRID. _findTable must not return such an object,
		since TableClass rejects anything outside TABLE_ROLES (raising
		ValueError and crashing onReviewMove during alt+tab).
		"""
		# Container reported as a LIST despite exposing the .table attribute.
		list_container = MockTableObject(role=controlTypes.Role.LIST)
		switcher_item = MockTableObject(role=controlTypes.Role.LISTITEM)
		switcher_item.table = list_container
		switcher_item.parent = None

		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=None):
			result = self.provider._findTable(switcher_item)

		self.assertIsNone(result)

	def test_find_table_ignores_underlying_table_attribute_with_non_table_role(self):
		"""Regression: the review-position underlying object's .table is also untrusted.

		Mirrors the alt+tab case for step 5 of _findTable, where the underlying
		object obtained from the review position exposes a LIST-roled ``.table``.
		"""
		list_container = MockTableObject(role=controlTypes.Role.LIST)
		underlying = MockTableObject(role=controlTypes.Role.LISTITEM)
		underlying.table = list_container
		underlying.parent = None

		# Navigator object yields nothing on its own; underlying comes from review.
		doc_obj = MockTableObject(role=controlTypes.Role.DOCUMENT)
		doc_obj.parent = None

		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=underlying):
			result = self.provider._findTable(doc_obj)

		self.assertIsNone(result)

	def test_find_table_respects_max_depth(self):
		"""Test that _findTable respects maxDepth parameter."""
		# Create a chain: button -> window -> datagrid
		datagrid_obj = MockTableObject(role=controlTypes.Role.DATAGRID)
		window_obj = MockTableObject(role=controlTypes.Role.WINDOW)
		button_obj = MockTableObject(role=controlTypes.Role.BUTTON)
		button_obj.parent = window_obj
		window_obj.parent = datagrid_obj

		# With maxDepth=1, should not find datagrid (2 levels up)
		result = self.provider._findTable(button_obj, maxDepth=1)
		self.assertIsNone(result)

		# With maxDepth=2, should find datagrid
		result = self.provider._findTable(button_obj, maxDepth=2)
		self.assertEqual(result, datagrid_obj)

	def test_find_table_uses_max_parent_scan_depth_by_default(self):
		"""Test that _findTable uses MAX_PARENT_SCAN_DEPTH when maxDepth is None."""
		# Create a deep chain
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)
		current = table_obj
		for _ in range(15):  # 15 levels deep, less than MAX_PARENT_SCAN_DEPTH (20)
			child = MockTableObject(role=controlTypes.Role.BUTTON)
			child.parent = current
			current = child

		result = self.provider._findTable(current)

		self.assertEqual(result, table_obj)

	def test_find_table_uses_review_position_for_table(self):
		"""Test that _findTable uses review position to find a table."""
		# Create a table that we'll return from review position
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)

		# Pass a document object (not a table, no .table attr, no table parent)
		doc_obj = MockTableObject(role=controlTypes.Role.DOCUMENT)

		# Mock the review position to return the table
		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=table_obj):
			result = self.provider._findTable(doc_obj)

		self.assertEqual(result, table_obj)

	def test_find_table_scans_parents_of_review_position_object(self):
		"""Test that _findTable scans parents of object from review position."""
		# Create parent chain: cell -> row -> table
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)
		row_obj = MockTableObject(role=controlTypes.Role.TABLEROW)
		row_obj.parent = table_obj
		cell_obj = MockTableObject(role=controlTypes.Role.TABLECELL)
		cell_obj.parent = row_obj

		# Pass a document object
		doc_obj = MockTableObject(role=controlTypes.Role.DOCUMENT)

		# Mock the review position to return the cell (whose parent chain leads to table)
		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=cell_obj):
			result = self.provider._findTable(doc_obj)

		self.assertEqual(result, table_obj)

	def test_find_table_returns_none_when_no_table_in_review_position(self):
		"""Test _findTable returns None when review position has no table ancestor."""
		# Object without table parent
		para_obj = MockTableObject(role=controlTypes.Role.PARAGRAPH)
		para_obj.parent = None

		doc_obj = MockTableObject(role=controlTypes.Role.DOCUMENT)

		# Mock the review position to return paragraph with no table ancestor
		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=para_obj):
			result = self.provider._findTable(doc_obj)

		self.assertIsNone(result)

	def test_find_table_prefers_obj_table_over_review_position(self):
		"""Test that _findTable prefers obj.table over review position.

		This tests the Word IAccessible table scenario where:
		- The cell object has .table attribute pointing to the table
		- Review position would return a different object
		- We should use obj.table directly (native table support)
		"""
		# The table we expect to be returned (from obj.table)
		native_table = MockTableObject(role=controlTypes.Role.TABLE)

		# A different table that would come from review position
		review_table = MockTableObject(role=controlTypes.Role.TABLE)

		# The cell object with native .table attribute
		cell_obj = MockTableObject(role=controlTypes.Role.TABLECELL)
		cell_obj.table = native_table

		# Mock review position to return a different table
		with patch.object(self.provider, "_getObjectFromReviewPosition", return_value=review_table):
			result = self.provider._findTable(cell_obj)

		# Should return the native table, not the review position's table
		self.assertEqual(result, native_table)


class TestTableProviderFindTableViaVbuf(unittest.TestCase):
	"""Tests for TableProvider._findTableViaVbuf() (browse-mode virtual buffer lookup)."""

	def setUp(self):
		self.provider = TableProvider()
		self.mock_vbuf = MagicMock()

	def _make_table_field_cmd(self, doc_handle: str = "42", node_id: str = "123"):
		"""Create a controlStart FieldCommand with a TABLE role."""
		from textInfos import ControlField, FieldCommand

		field = ControlField(
			{
				"role": controlTypes.Role.TABLE,
				"controlIdentifier_docHandle": doc_handle,
				"controlIdentifier_ID": node_id,
			},
		)
		return FieldCommand("controlStart", field)

	def _make_link_field_cmd(self):
		"""Create a controlStart FieldCommand with a LINK role (not a table)."""
		from textInfos import ControlField, FieldCommand

		return FieldCommand("controlStart", ControlField({"role": controlTypes.Role.LINK}))

	@patch("addon.presentations.table.api")
	def test_finds_table_role_in_fields(self, mock_api):
		"""Should return NVDAObject from getNVDAObjectFromIdentifier when TABLE found."""
		obj = MockTableObject(role=controlTypes.Role.LINK)
		obj.treeInterceptor = self.mock_vbuf

		table_cmd = self._make_table_field_cmd("42", "123")
		link_cmd = self._make_link_field_cmd()
		mock_review_pos = MagicMock()
		mock_review_pos.getTextWithFields.return_value = [link_cmd, table_cmd, "some text"]
		mock_api.getReviewPosition.return_value = mock_review_pos

		expected_table = MockTableObject(role=controlTypes.Role.TABLE)
		self.mock_vbuf.getNVDAObjectFromIdentifier.return_value = expected_table

		result = self.provider._findTableViaVbuf(obj)

		self.assertEqual(result, expected_table)
		self.mock_vbuf.getNVDAObjectFromIdentifier.assert_called_once_with(42, 123)

	@patch("addon.presentations.table.api")
	def test_returns_none_when_no_table_in_fields(self, mock_api):
		"""Should return None without calling getNVDAObjectFromIdentifier when no TABLE role found."""
		obj = MockTableObject(role=controlTypes.Role.LINK)
		obj.treeInterceptor = self.mock_vbuf

		link_cmd = self._make_link_field_cmd()
		mock_review_pos = MagicMock()
		mock_review_pos.getTextWithFields.return_value = [link_cmd, "link text"]
		mock_api.getReviewPosition.return_value = mock_review_pos

		result = self.provider._findTableViaVbuf(obj)

		self.assertIsNone(result)
		self.mock_vbuf.getNVDAObjectFromIdentifier.assert_not_called()

	@patch("addon.presentations.table.api")
	def test_returns_none_when_review_position_is_none(self, mock_api):
		"""Should return None gracefully when review position is not available."""
		obj = MockTableObject(role=controlTypes.Role.LINK)
		obj.treeInterceptor = self.mock_vbuf
		mock_api.getReviewPosition.return_value = None

		result = self.provider._findTableViaVbuf(obj)

		self.assertIsNone(result)

	@patch("addon.presentations.table.api")
	def test_skips_field_when_identifiers_missing(self, mock_api):
		"""Should return None when TABLE field has no controlIdentifier_ attributes."""
		from textInfos import ControlField, FieldCommand

		obj = MockTableObject(role=controlTypes.Role.LINK)
		obj.treeInterceptor = self.mock_vbuf

		field_without_ids = ControlField({"role": controlTypes.Role.TABLE})
		cmd = FieldCommand("controlStart", field_without_ids)
		mock_review_pos = MagicMock()
		mock_review_pos.getTextWithFields.return_value = [cmd]
		mock_api.getReviewPosition.return_value = mock_review_pos

		result = self.provider._findTableViaVbuf(obj)

		self.assertIsNone(result)
		self.mock_vbuf.getNVDAObjectFromIdentifier.assert_not_called()

	@patch("addon.presentations.table.api")
	def test_returns_none_when_tree_interceptor_becomes_none(self, mock_api):
		"""Should return None if treeInterceptor is None inside the method."""
		obj = MockTableObject(role=controlTypes.Role.LINK)
		obj.treeInterceptor = None

		table_cmd = self._make_table_field_cmd()
		mock_review_pos = MagicMock()
		mock_review_pos.getTextWithFields.return_value = [table_cmd]
		mock_api.getReviewPosition.return_value = mock_review_pos

		result = self.provider._findTableViaVbuf(obj)

		self.assertIsNone(result)

	@patch("addon.presentations.table.api")
	def test_find_table_calls_vbuf_path_for_browse_mode_obj(self, mock_api):
		"""_findTable should delegate to _findTableViaVbuf for browse-mode objects."""
		obj = MockTableObject(role=controlTypes.Role.LINK)
		obj.treeInterceptor = self.mock_vbuf

		mock_review_pos = MagicMock()
		mock_review_pos.getTextWithFields.return_value = []
		mock_api.getReviewPosition.return_value = mock_review_pos

		with patch.object(self.provider, "_findTableViaVbuf", return_value=None) as mock_vbuf_fn:
			self.provider._findTable(obj)

		mock_vbuf_fn.assert_called_once_with(obj)

	@patch("addon.presentations.table.api")
	def test_find_table_skips_ia2_walk_for_browse_mode_obj(self, mock_api):
		"""_findTable must not call findAncestorWithRole for browse-mode objects."""
		obj = MockTableObject(role=controlTypes.Role.LINK)
		obj.treeInterceptor = self.mock_vbuf

		mock_review_pos = MagicMock()
		mock_review_pos.getTextWithFields.return_value = []
		mock_api.getReviewPosition.return_value = mock_review_pos

		with patch("addon.presentations.table.findAncestorWithRole") as mock_ancestor:
			self.provider._findTable(obj)

		mock_ancestor.assert_not_called()


class TestTableProviderCanProvideCache(unittest.TestCase):
	"""Tests for canProvide() obj-identity cache (avoids double _findTable per keypress)."""

	def setUp(self):
		self.provider = TableProvider()

	def test_second_call_with_same_obj_uses_cache(self):
		"""Second canProvide call for the same obj instance must not re-call _findTable."""
		obj = MockTableObject(role=controlTypes.Role.BUTTON)
		obj.parent = None

		with patch.object(self.provider, "_findTable", wraps=self.provider._findTable) as mock_find:
			result1 = self.provider.canProvide(obj)
			result2 = self.provider.canProvide(obj)

		self.assertEqual(mock_find.call_count, 1)
		self.assertEqual(result1, result2)
		self.assertFalse(result1)

	def test_cache_hit_returns_true_when_table_was_found(self):
		"""Cache hit must return True when the first call found a table."""
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)

		with patch.object(self.provider, "_findTable", return_value=table_obj) as mock_find:
			result1 = self.provider.canProvide(table_obj)
			result2 = self.provider.canProvide(table_obj)

		self.assertEqual(mock_find.call_count, 1)
		self.assertTrue(result1)
		self.assertTrue(result2)

	def test_different_obj_instance_invalidates_cache(self):
		"""A different obj instance must bypass the cache and call _findTable again."""
		obj1 = MockTableObject(role=controlTypes.Role.BUTTON)
		obj1.parent = None
		obj2 = MockTableObject(role=controlTypes.Role.BUTTON)
		obj2.parent = None

		with patch.object(self.provider, "_findTable", wraps=self.provider._findTable) as mock_find:
			self.provider.canProvide(obj1)
			self.provider.canProvide(obj2)

		self.assertEqual(mock_find.call_count, 2)


class TestTableProviderIntegration(unittest.TestCase):
	"""Integration tests for TableProvider with PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MockTableDisplay()

	@patch.object(TableProvider, "_getObjectFromReviewPosition", return_value=None)
	@patch("addon.presentations.table.Table")
	def test_provider_works_with_presentation_manager(self, mock_table_class, mock_review_pos):
		"""Test that TableProvider works correctly with PresentationManager."""
		mock_table_class.return_value = MagicMock()
		provider = TableProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Update with a table object
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)
		manager.update(table_obj)

		# Should have an active presentation
		self.assertTrue(manager.hasActivePresentation)
		self.assertEqual(manager.activePresentation.name, "table")

	@patch.object(TableProvider, "_getObjectFromReviewPosition", return_value=None)
	@patch("addon.presentations.table.Table")
	def test_force_table_mode_with_manager(self, mock_table_class, mock_review_pos):
		"""Test forcing table mode through the PresentationManager."""
		mock_table_class.return_value = MagicMock()
		provider = TableProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Create a cell inside a table
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)
		cell_obj = MockTableObject(role=controlTypes.Role.TABLECELL)
		cell_obj.parent = table_obj

		# Force table presentation
		result = manager.forcePresentation("table", cell_obj)

		self.assertTrue(result)
		self.assertTrue(manager.isForcedMode)
		self.assertEqual(manager.activePresentation.name, "table")

	@patch.object(TableProvider, "_getObjectFromReviewPosition", return_value=None)
	@patch("addon.presentations.table.api")
	@patch("addon.presentations.table.Table")
	def test_forced_table_clears_when_nav_leaves_table(
		self,
		mock_table_class,
		mock_api,
		mock_review_pos,
	):
		"""Test that forced table presentation clears when navigator leaves table."""
		mock_table_class.return_value = MagicMock()
		provider = TableProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Create a cell inside a table with location
		table_obj = MockTableObject(role=controlTypes.Role.TABLE)
		table_obj.location = MockLocation(0, 0, 100, 100)
		cell_obj = MockTableObject(role=controlTypes.Role.TABLECELL)
		cell_obj.parent = table_obj

		# Force table presentation
		manager.forcePresentation("table", cell_obj)
		self.assertTrue(manager.isForcedMode)

		# Simulate navigator moving outside table - use spec to prevent auto-creation of .table
		mock_nav_obj = MagicMock(spec=["role", "location", "treeInterceptor", "windowHandle", "parent"])
		mock_nav_obj.location = MockLocation(200, 200, 300, 300)  # Outside table
		mock_nav_obj.role = controlTypes.Role.BUTTON
		mock_nav_obj.treeInterceptor = None  # No TreeInterceptor in this test
		mock_nav_obj.windowHandle = None  # Avoid window handle check
		mock_nav_obj.parent = None  # No parent chain - not inside any table
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		# Update should clear forced mode
		manager.update(mock_nav_obj)

		self.assertFalse(manager.isForcedMode)


# ============================================================================
# Table Scroll Wrapping Tests (addon/utils/table.py)
# ============================================================================


class TestTableScrollWrapping(unittest.TestCase):
	"""Tests for Table.scrollForward() and scrollBack() wrapping behavior."""

	def setUp(self):
		"""Set up test fixtures with a mock table object."""
		from addon.utils.table import Table

		self.Table = Table
		# Create a mock table object with required attributes
		self.mock_table_obj = MagicMock()
		self.mock_table_obj.role = controlTypes.Role.TABLE
		self.mock_table_obj.name = "Test Table"
		self.mock_table_obj.description = ""
		self.mock_table_obj.children = []
		self.mock_table_obj.columnCount = 10
		self.mock_table_obj.rowCount = 5

	def _create_table_with_state(
		self,
		firstVisibleCol: int = 0,
		firstVisibleRow: int = 0,
		numVisibleCols: int = 3,
		numVisibleRows: int = 2,
		columnCount: int = 10,
		rowCount: int = 5,
	):
		"""Create a Table instance with pre-configured scroll state."""
		self.mock_table_obj.columnCount = columnCount
		self.mock_table_obj.rowCount = rowCount
		table = self.Table(self.mock_table_obj)
		# Set internal state that would normally be set by drawTable()
		table.firstVisibleCol = firstVisibleCol
		table.firstVisibleRow = firstVisibleRow
		table.numVisibleCols = numVisibleCols
		table.numVisibleRows = numVisibleRows
		return table

	# scrollForward() tests

	def test_scroll_forward_scrolls_right_when_not_at_end_of_row(self):
		"""Test that scrollForward() scrolls right when not at end of row."""
		table = self._create_table_with_state(
			firstVisibleCol=0,
			firstVisibleRow=0,
			numVisibleCols=3,
			columnCount=10,
		)

		result = table.scrollForward()

		self.assertTrue(result)
		self.assertEqual(table.firstVisibleCol, 3)
		self.assertEqual(table.firstVisibleRow, 0)

	def test_scroll_forward_wraps_to_first_column_on_row_change(self):
		"""Test that scrollForward() wraps to first column when at end of row."""
		table = self._create_table_with_state(
			firstVisibleCol=9,  # At last column page (cols 9 visible, but col 9 + 3 >= 10)
			firstVisibleRow=0,
			numVisibleCols=3,
			numVisibleRows=2,
			columnCount=10,
			rowCount=5,
		)

		result = table.scrollForward()

		self.assertTrue(result)
		self.assertEqual(table.firstVisibleCol, 0)  # Reset to first column
		self.assertEqual(table.firstVisibleRow, 2)  # Moved down by numVisibleRows

	def test_scroll_forward_at_last_row_last_col_returns_false(self):
		"""Test that scrollForward() returns False at bottom-right corner."""
		table = self._create_table_with_state(
			firstVisibleCol=9,  # At last column page
			firstVisibleRow=4,  # At last row (4 + 2 >= 5)
			numVisibleCols=3,
			numVisibleRows=2,
			columnCount=10,
			rowCount=5,
		)

		result = table.scrollForward()

		self.assertFalse(result)
		# Position should not change
		self.assertEqual(table.firstVisibleCol, 9)
		self.assertEqual(table.firstVisibleRow, 4)

	def test_scroll_forward_returns_false_when_not_drawn(self):
		"""Test that scrollForward() returns False when table not yet drawn."""
		table = self.Table(self.mock_table_obj)
		# numVisibleCols and numVisibleRows are None (not drawn yet)

		result = table.scrollForward()

		self.assertFalse(result)

	# scrollBack() tests

	def test_scroll_back_scrolls_left_when_not_at_start_of_row(self):
		"""Test that scrollBack() scrolls left when not at start of row."""
		table = self._create_table_with_state(
			firstVisibleCol=6,
			firstVisibleRow=0,
			numVisibleCols=3,
			columnCount=10,
		)

		result = table.scrollBack()

		self.assertTrue(result)
		self.assertEqual(table.firstVisibleCol, 3)
		self.assertEqual(table.firstVisibleRow, 0)

	def test_scroll_back_wraps_to_last_column_on_row_change(self):
		"""Test that scrollBack() wraps to last column page when at start of row."""
		table = self._create_table_with_state(
			firstVisibleCol=0,  # At first column
			firstVisibleRow=2,
			numVisibleCols=3,
			numVisibleRows=2,
			columnCount=10,
			rowCount=5,
		)

		result = table.scrollBack()

		self.assertTrue(result)
		# Last page start: ((10-1)//3)*3 = (9//3)*3 = 3*3 = 9
		self.assertEqual(table.firstVisibleCol, 9)
		self.assertEqual(table.firstVisibleRow, 0)  # Moved up by numVisibleRows

	def test_scroll_back_at_first_row_first_col_returns_false(self):
		"""Test that scrollBack() returns False at top-left corner."""
		table = self._create_table_with_state(
			firstVisibleCol=0,
			firstVisibleRow=0,
			numVisibleCols=3,
			numVisibleRows=2,
			columnCount=10,
			rowCount=5,
		)

		result = table.scrollBack()

		self.assertFalse(result)
		# Position should not change
		self.assertEqual(table.firstVisibleCol, 0)
		self.assertEqual(table.firstVisibleRow, 0)

	def test_scroll_back_returns_false_when_not_drawn(self):
		"""Test that scrollBack() returns False when table not yet drawn."""
		table = self.Table(self.mock_table_obj)
		# numVisibleCols and numVisibleRows are None (not drawn yet)

		result = table.scrollBack()

		self.assertFalse(result)

	# Last page calculation tests

	def test_scroll_back_calculates_last_page_correctly_exact_multiple(self):
		"""Test last page calculation when column count is exact multiple of visible cols."""
		table = self._create_table_with_state(
			firstVisibleCol=0,
			firstVisibleRow=2,
			numVisibleCols=3,
			numVisibleRows=2,
			columnCount=9,  # Exact multiple of 3
			rowCount=5,
		)

		result = table.scrollBack()

		self.assertTrue(result)
		# Last page start: ((9-1)//3)*3 = (8//3)*3 = 2*3 = 6
		self.assertEqual(table.firstVisibleCol, 6)

	def test_scroll_back_calculates_last_page_correctly_not_multiple(self):
		"""Test last page calculation when column count is not a multiple of visible cols."""
		table = self._create_table_with_state(
			firstVisibleCol=0,
			firstVisibleRow=2,
			numVisibleCols=3,
			numVisibleRows=2,
			columnCount=11,  # Not a multiple of 3
			rowCount=5,
		)

		result = table.scrollBack()

		self.assertTrue(result)
		# Last page start: ((11-1)//3)*3 = (10//3)*3 = 3*3 = 9
		self.assertEqual(table.firstVisibleCol, 9)

	def test_scroll_back_with_single_column_page(self):
		"""Test scrollBack() when table has fewer columns than visible cols."""
		table = self._create_table_with_state(
			firstVisibleCol=0,
			firstVisibleRow=2,
			numVisibleCols=5,
			numVisibleRows=2,
			columnCount=3,  # Fewer than numVisibleCols
			rowCount=5,
		)

		result = table.scrollBack()

		self.assertTrue(result)
		# Last page start: ((3-1)//5)*5 = (2//5)*5 = 0*5 = 0
		self.assertEqual(table.firstVisibleCol, 0)

	# Forward wrapping edge cases

	def test_scroll_forward_wraps_with_exact_column_boundary(self):
		"""Test scrollForward() wrapping when exactly at column boundary."""
		table = self._create_table_with_state(
			firstVisibleCol=6,  # 6 + 3 = 9, which equals columnCount - 1
			firstVisibleRow=0,
			numVisibleCols=3,
			numVisibleRows=2,
			columnCount=9,
			rowCount=5,
		)

		result = table.scrollForward()

		self.assertTrue(result)
		self.assertEqual(table.firstVisibleCol, 0)
		self.assertEqual(table.firstVisibleRow, 2)


# ============================================================================
# Chart Presentation Tests
# ============================================================================


class MockChartObject:
	"""A mock chart NVDAObject for testing ChartPresentation."""

	def __init__(
		self,
		name: str = "Test Chart",
		location=None,
		officeChartObject=None,
	):
		self.name = name
		self.location = location
		self.officeChartObject = officeChartObject


class MockChartDisplay:
	"""A mock display for testing chart presentations."""

	def __init__(
		self,
		numCols: int = 40,
		numRows: int = 1,
		physicalNumCols: int = 60,
		physicalNumRows: int = 40,
		cellWidth: int = 2,
		cellHeight: int = 4,
	):
		self.numCols = numCols
		self.numRows = numRows
		self.physicalNumCols = physicalNumCols
		self.physicalNumRows = physicalNumRows
		self.numCells = numCols * numRows
		self.cellWidth = cellWidth
		self.cellHeight = cellHeight


class TestChartPresentationProtocol(unittest.TestCase):
	"""Tests for ChartPresentation implementing the Presentation protocol."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_chart = MockChartObject(officeChartObject=MagicMock())
		self.mock_display = MockChartDisplay()

	def test_implements_presentation_protocol(self):
		"""Test that ChartPresentation implements the Presentation protocol."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)
		self.assertTrue(isinstance(presentation, Presentation))

	def test_has_name_attribute(self):
		"""Test that ChartPresentation has a name attribute."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)
		self.assertEqual(presentation.name, "chart")

	def test_has_required_methods(self):
		"""Test that ChartPresentation has all required methods."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)
		self.assertTrue(hasattr(presentation, "render"))
		self.assertTrue(hasattr(presentation, "scrollForward"))
		self.assertTrue(hasattr(presentation, "scrollBack"))
		self.assertTrue(hasattr(presentation, "isStillValid"))

	def test_stores_chart_obj(self):
		"""Test that ChartPresentation stores the chart object."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)
		self.assertEqual(presentation.chartObj, self.mock_chart)


class TestChartPresentationRender(unittest.TestCase):
	"""Tests for ChartPresentation.render()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_chart = MockChartObject(officeChartObject=MagicMock())
		self.mock_display = MockChartDisplay()

	@patch("addon.presentations.chart.BarChart")
	def test_render_returns_buffer(self, mock_barchart):
		"""Test that render() returns a DpTactileGraphicsBuffer."""
		from addon.brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer

		mock_barchart.return_value = MagicMock()
		presentation = ChartPresentation(self.mock_chart, self.mock_display)
		result = presentation.render(self.mock_display)

		self.assertIsInstance(result, DpTactileGraphicsBuffer)

	@patch("addon.presentations.chart.BarChart")
	def test_render_creates_buffer_with_correct_dimensions(self, mock_barchart):
		"""Test that render() creates a buffer with correct dimensions."""
		mock_barchart.return_value = MagicMock()
		presentation = ChartPresentation(self.mock_chart, self.mock_display)
		result = presentation.render(self.mock_display)

		# Physical dimensions are 60x40 cells, each cell is 2x4 pixels
		expected_width = self.mock_display.physicalNumCols * 2  # 60 * 2 = 120
		expected_height = self.mock_display.physicalNumRows * 4  # 40 * 4 = 160
		self.assertEqual(result.width, expected_width)
		self.assertEqual(result.height, expected_height)


class TestChartPresentationScroll(unittest.TestCase):
	"""Tests for ChartPresentation scroll methods."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_chart = MockChartObject(officeChartObject=MagicMock())
		self.mock_display = MockChartDisplay()

	def test_scroll_forward_returns_false_when_no_chart(self):
		"""Test that scrollForward() returns False when chart is not initialized."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)
		# Don't call render, so _chart is None
		result = presentation.scrollForward()
		self.assertFalse(result)

	def test_scroll_back_returns_false_when_no_chart(self):
		"""Test that scrollBack() returns False when chart is not initialized."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)
		# Don't call render, so _chart is None
		result = presentation.scrollBack()
		self.assertFalse(result)

	def test_scroll_forward_delegates_to_chart(self):
		"""Test that scrollForward() delegates to the chart when available."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)

		# Mock the internal chart object
		mock_internal_chart = MagicMock()
		mock_internal_chart.scrollForward.return_value = True
		presentation._chart = mock_internal_chart

		result = presentation.scrollForward()

		self.assertTrue(result)
		mock_internal_chart.scrollForward.assert_called_once()

	def test_scroll_back_delegates_to_chart(self):
		"""Test that scrollBack() delegates to the chart when available."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)

		# Mock the internal chart object
		mock_internal_chart = MagicMock()
		mock_internal_chart.scrollBack.return_value = True
		presentation._chart = mock_internal_chart

		result = presentation.scrollBack()

		self.assertTrue(result)
		mock_internal_chart.scrollBack.assert_called_once()


class TestChartPresentationIsStillValid(unittest.TestCase):
	"""Tests for ChartPresentation.isStillValid()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_chart = MockChartObject(officeChartObject=MagicMock())
		self.mock_display = MockChartDisplay()

	@patch("addon.presentations.chart.api")
	def test_is_still_valid_same_object(self, mock_api):
		"""Test isStillValid() returns True when navigator is same object."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)

		# Navigator is the same chart object
		mock_api.getNavigatorObject.return_value = self.mock_chart

		result = presentation.isStillValid()

		self.assertTrue(result)

	@patch("addon.presentations.chart.api")
	def test_is_still_valid_same_office_chart_object(self, mock_api):
		"""Test isStillValid() returns True when officeChartObject matches."""
		presentation = ChartPresentation(self.mock_chart, self.mock_display)

		# Navigator is a different object but same officeChartObject
		mock_nav_obj = MockChartObject(officeChartObject=self.mock_chart.officeChartObject)
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		result = presentation.isStillValid()

		self.assertTrue(result)

	@patch("addon.presentations.chart.api")
	def test_is_still_valid_with_bounds_check(self, mock_api):
		"""Test isStillValid() fallback to bounds check."""
		self.mock_chart.location = MockLocation(0, 0, 100, 100)
		presentation = ChartPresentation(self.mock_chart, self.mock_display)

		# Navigator is inside chart bounds
		mock_nav_obj = MagicMock()
		mock_nav_obj.officeChartObject = None  # Different/no chart object
		mock_nav_obj.location = MockLocation(10, 10, 50, 50)
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		result = presentation.isStillValid()

		self.assertTrue(result)

	@patch("addon.presentations.chart.api")
	def test_is_still_valid_returns_false_outside_bounds(self, mock_api):
		"""Test isStillValid() returns False when navigator is outside bounds."""
		self.mock_chart.location = MockLocation(0, 0, 100, 100)
		presentation = ChartPresentation(self.mock_chart, self.mock_display)

		# Navigator is outside chart bounds
		mock_nav_obj = MagicMock()
		mock_nav_obj.officeChartObject = None
		mock_nav_obj.location = MockLocation(200, 200, 300, 300)
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		result = presentation.isStillValid()

		self.assertFalse(result)

	@patch("addon.presentations.chart.api")
	def test_is_still_valid_returns_false_without_location(self, mock_api):
		"""Test isStillValid() returns False when no location available."""
		self.mock_chart.location = None
		presentation = ChartPresentation(self.mock_chart, self.mock_display)

		# Navigator without location
		mock_nav_obj = MagicMock()
		mock_nav_obj.officeChartObject = None
		mock_nav_obj.location = None
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		result = presentation.isStillValid()

		self.assertFalse(result)


class TestChartProviderProtocol(unittest.TestCase):
	"""Tests for ChartProvider implementing the PresentationProvider protocol."""

	def test_implements_provider_protocol(self):
		"""Test that ChartProvider implements the PresentationProvider protocol."""
		provider = ChartProvider()
		self.assertTrue(isinstance(provider, PresentationProvider))

	def test_has_name_attribute(self):
		"""Test that ChartProvider has a name attribute."""
		provider = ChartProvider()
		self.assertEqual(provider.name, "chart")

	def test_has_canProvide_method(self):
		"""Test that ChartProvider has canProvide method."""
		provider = ChartProvider()
		self.assertTrue(hasattr(provider, "canProvide"))
		self.assertTrue(callable(provider.canProvide))

	def test_has_createPresentation_method(self):
		"""Test that ChartProvider has createPresentation method."""
		provider = ChartProvider()
		self.assertTrue(hasattr(provider, "createPresentation"))
		self.assertTrue(callable(provider.createPresentation))

	def test_has_force_for_object_method(self):
		"""Test that ChartProvider has forceForObject method."""
		provider = ChartProvider()
		self.assertTrue(hasattr(provider, "forceForObject"))


class TestChartProviderDetection(unittest.TestCase):
	"""Tests for ChartProvider detection logic."""

	def setUp(self):
		"""Set up test fixtures."""
		self.provider = ChartProvider()
		self.mock_display = MockChartDisplay()

	def test_createPresentation_for_chart_with_office_chart_object(self):
		"""Test that createPresentation returns a presentation for objects with officeChartObject."""
		mock_obj = MockChartObject(officeChartObject=MagicMock())

		presentation = self.provider.createPresentation(mock_obj, self.mock_display)

		self.assertIsInstance(presentation, ChartPresentation)

	def test_canProvide_returns_false_for_non_chart(self):
		"""Test canProvide returns False for non-chart objects."""
		mock_obj = MagicMock(spec=[])  # No officeChartObject attribute

		self.assertFalse(self.provider.canProvide(mock_obj))

	def test_canProvide_returns_true_for_office_chart(self):
		"""Test canProvide returns True for objects with officeChartObject."""
		mock_obj = MockChartObject(officeChartObject=MagicMock())
		self.assertTrue(self.provider.canProvide(mock_obj))


class TestChartProviderForceForObject(unittest.TestCase):
	"""Tests for ChartProvider.forceForObject()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.provider = ChartProvider()
		self.mock_display = MockChartDisplay()

	def test_force_for_object_returns_none(self):
		"""Test that forceForObject always returns None (charts don't support forcing)."""
		mock_obj = MockChartObject(officeChartObject=MagicMock())

		result = self.provider.forceForObject(mock_obj, self.mock_display)

		self.assertIsNone(result)

	def test_force_for_object_returns_none_for_any_object(self):
		"""Test that forceForObject returns None even for chart objects."""
		# Even when given a chart object, forceForObject should return None
		mock_obj = MagicMock()
		mock_obj.officeChartObject = MagicMock()

		result = self.provider.forceForObject(mock_obj, self.mock_display)

		self.assertIsNone(result)


class TestChartProviderIntegration(unittest.TestCase):
	"""Integration tests for ChartProvider with PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MockChartDisplay()

	def test_provider_works_with_presentation_manager(self):
		"""Test that ChartProvider works correctly with PresentationManager."""
		provider = ChartProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Update with a chart object
		chart_obj = MockChartObject(officeChartObject=MagicMock())
		manager.update(chart_obj)

		# Should have an active presentation
		self.assertTrue(manager.hasActivePresentation)
		self.assertEqual(manager.activePresentation.name, "chart")

	def test_chart_provider_does_not_detect_non_charts(self):
		"""Test that ChartProvider doesn't yield presentations for non-chart objects."""
		provider = ChartProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Update with a non-chart object
		mock_obj = MagicMock(spec=[])  # No officeChartObject attribute
		manager.update(mock_obj)

		# Should not have an active presentation
		self.assertFalse(manager.hasActivePresentation)

	def test_force_chart_returns_false(self):
		"""Test that forcing chart mode returns False."""
		provider = ChartProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		mock_obj = MockChartObject(officeChartObject=MagicMock())
		result = manager.forcePresentation("chart", mock_obj)

		# forceForObject returns None, so forcePresentation returns False
		self.assertFalse(result)
		self.assertFalse(manager.isForcedMode)

	@patch("addon.presentations.chart.api")
	def test_chart_presentation_clears_when_nav_leaves_chart(self, mock_api):
		"""Test that chart presentation clears when navigator leaves chart."""
		provider = ChartProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Create chart object with location
		chart_obj = MockChartObject(officeChartObject=MagicMock())
		chart_obj.location = MockLocation(0, 0, 100, 100)

		# Set up active chart presentation
		manager.update(chart_obj)
		self.assertTrue(manager.hasActivePresentation)

		# Simulate navigator moving outside chart
		mock_nav_obj = MagicMock(spec=[])  # No officeChartObject
		mock_nav_obj.location = MockLocation(200, 200, 300, 300)
		mock_api.getNavigatorObject.return_value = mock_nav_obj

		# Update should select no presentation (provider doesn't yield)
		manager.update(mock_nav_obj)

		# Since the mock_nav_obj has no officeChartObject, provider won't yield
		self.assertFalse(manager.hasActivePresentation)


# ============================================================================
# Screen Capture Presentation Tests
# ============================================================================


class MockScreenCaptureDisplay:
	"""A mock display for testing screen capture presentations."""

	def __init__(
		self,
		numCols: int = 40,
		numRows: int = 1,
		physicalNumCols: int = 60,
		physicalNumRows: int = 40,
	):
		self.numCols = numCols
		self.numRows = numRows
		self.physicalNumCols = physicalNumCols
		self.physicalNumRows = physicalNumRows
		self.numCells = numCols * numRows


class TestScreenCapturePresentationProtocol(unittest.TestCase):
	"""Tests for ScreenCapturePresentation implementing the Presentation protocol."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MockScreenCaptureDisplay()

	def test_implements_presentation_protocol(self):
		"""Test that ScreenCapturePresentation implements the Presentation protocol."""
		presentation = ScreenCapturePresentation(self.mock_display)
		self.assertTrue(isinstance(presentation, Presentation))

	def test_has_name_attribute(self):
		"""Test that ScreenCapturePresentation has a name attribute."""
		presentation = ScreenCapturePresentation(self.mock_display)
		self.assertEqual(presentation.name, "screenCapture")

	def test_has_required_methods(self):
		"""Test that ScreenCapturePresentation has all required methods."""
		presentation = ScreenCapturePresentation(self.mock_display)
		self.assertTrue(hasattr(presentation, "render"))
		self.assertTrue(hasattr(presentation, "scrollForward"))
		self.assertTrue(hasattr(presentation, "scrollBack"))
		self.assertTrue(hasattr(presentation, "isStillValid"))


class TestScreenCapturePresentationIsStillValid(unittest.TestCase):
	"""Tests for ScreenCapturePresentation.isStillValid()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MockScreenCaptureDisplay()

	def test_is_still_valid_returns_true(self):
		"""Test that isStillValid() always returns True for screen capture presentations."""
		presentation = ScreenCapturePresentation(self.mock_display)
		# Screen capture follows navigation, so it's always valid
		self.assertTrue(presentation.isStillValid())

	def test_is_still_valid_returns_true_multiple_times(self):
		"""Test that isStillValid() consistently returns True."""
		presentation = ScreenCapturePresentation(self.mock_display)
		# Call multiple times to ensure consistency
		self.assertTrue(presentation.isStillValid())
		self.assertTrue(presentation.isStillValid())
		self.assertTrue(presentation.isStillValid())


class TestScreenCapturePresentationScroll(unittest.TestCase):
	"""Tests for ScreenCapturePresentation scroll methods."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MockScreenCaptureDisplay()

	@patch("addon.presentations.screenCapture.api")
	@patch("addon.presentations.screenCapture.configuration")
	def test_scroll_forward_returns_false_when_empty(self, mock_config, mock_api):
		"""Test that scrollForward() returns False when viewport is empty."""
		# With no visible objects, scrolling should fail
		mock_config.getScreenCaptureShowObjectNumbers.return_value = False
		mock_api.getNavigatorObject.return_value = MagicMock()
		presentation = ScreenCapturePresentation(self.mock_display)
		result = presentation.scrollForward()
		self.assertFalse(result)

	@patch("addon.presentations.screenCapture.api")
	@patch("addon.presentations.screenCapture.configuration")
	def test_scroll_back_returns_false_when_empty(self, mock_config, mock_api):
		"""Test that scrollBack() returns False when viewport is empty."""
		# With no visible objects, scrolling should fail
		mock_config.getScreenCaptureShowObjectNumbers.return_value = False
		mock_api.getNavigatorObject.return_value = MagicMock()
		presentation = ScreenCapturePresentation(self.mock_display)
		result = presentation.scrollBack()
		self.assertFalse(result)


class TestScreenCapturePresentationRender(unittest.TestCase):
	"""Tests for ScreenCapturePresentation.render()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MockScreenCaptureDisplay()

	@patch("addon.presentations.screenCapture.api")
	def test_render_returns_buffer(self, mock_api):
		"""Test that render() returns a DpTactileGraphicsBuffer."""
		from addon.brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer

		mock_api.getNavigatorObject.return_value = None
		presentation = ScreenCapturePresentation(self.mock_display)
		result = presentation.render(self.mock_display)

		self.assertIsInstance(result, DpTactileGraphicsBuffer)

	@patch("addon.presentations.screenCapture.api")
	def test_render_creates_buffer_with_correct_dimensions(self, mock_api):
		"""Test that render() creates a buffer with the display's physical dimensions."""
		mock_api.getNavigatorObject.return_value = None
		presentation = ScreenCapturePresentation(self.mock_display)
		result = presentation.render(self.mock_display)

		# Physical dimensions are 60x40 cells, each cell is 2x4 pixels
		expected_width = self.mock_display.physicalNumCols * 2  # 60 * 2 = 120
		expected_height = self.mock_display.physicalNumRows * 4  # 40 * 4 = 160
		self.assertEqual(result.width, expected_width)
		self.assertEqual(result.height, expected_height)


class TestScreenCaptureProviderProtocol(unittest.TestCase):
	"""Tests for ScreenCaptureProvider implementing the PresentationProvider protocol."""

	def test_implements_provider_protocol(self):
		"""Test that ScreenCaptureProvider implements the PresentationProvider protocol."""
		provider = ScreenCaptureProvider()
		self.assertTrue(isinstance(provider, PresentationProvider))

	def test_has_name_attribute(self):
		"""Test that ScreenCaptureProvider has a name attribute."""
		provider = ScreenCaptureProvider()
		self.assertEqual(provider.name, "screenCapture")

	def test_has_canProvide_method(self):
		"""Test that ScreenCaptureProvider has canProvide method."""
		provider = ScreenCaptureProvider()
		self.assertTrue(hasattr(provider, "canProvide"))
		self.assertTrue(callable(provider.canProvide))

	def test_has_createPresentation_method(self):
		"""Test that ScreenCaptureProvider has createPresentation method."""
		provider = ScreenCaptureProvider()
		self.assertTrue(hasattr(provider, "createPresentation"))
		self.assertTrue(callable(provider.createPresentation))

	def test_has_force_for_object_method(self):
		"""Test that ScreenCaptureProvider has forceForObject method."""
		provider = ScreenCaptureProvider()
		self.assertTrue(hasattr(provider, "forceForObject"))

	def test_has_toggle_method(self):
		"""Test that ScreenCaptureProvider has toggle method."""
		provider = ScreenCaptureProvider()
		self.assertTrue(hasattr(provider, "toggle"))

	def test_has_enabled_property(self):
		"""Test that ScreenCaptureProvider has enabled property."""
		provider = ScreenCaptureProvider()
		self.assertTrue(hasattr(provider, "enabled"))


class TestScreenCaptureProviderToggle(unittest.TestCase):
	"""Tests for ScreenCaptureProvider toggle behavior."""

	def setUp(self):
		"""Set up test fixtures."""
		self.provider = ScreenCaptureProvider()
		self.mock_display = MockScreenCaptureDisplay()
		self.mock_obj = MagicMock()

	def test_initial_state_is_disabled(self):
		"""Test that provider starts disabled."""
		self.assertFalse(self.provider.enabled)

	def test_toggle_enables_when_disabled(self):
		"""Test that toggle enables when initially disabled."""
		result = self.provider.toggle()
		self.assertTrue(result)
		self.assertTrue(self.provider.enabled)

	def test_toggle_disables_when_enabled(self):
		"""Test that toggle disables when currently enabled."""
		self.provider.toggle()  # Enable
		result = self.provider.toggle()  # Disable
		self.assertFalse(result)
		self.assertFalse(self.provider.enabled)

	def test_toggle_returns_new_state(self):
		"""Test that toggle returns the new enabled state."""
		# First toggle should return True (now enabled)
		self.assertTrue(self.provider.toggle())
		# Second toggle should return False (now disabled)
		self.assertFalse(self.provider.toggle())
		# Third toggle should return True (enabled again)
		self.assertTrue(self.provider.toggle())

	def test_set_enabled_true(self):
		"""Test that setEnabled(True) enables the provider."""
		self.provider.setEnabled(True)
		self.assertTrue(self.provider.enabled)

	def test_set_enabled_false(self):
		"""Test that setEnabled(False) disables the provider."""
		self.provider.toggle()  # Enable first
		self.provider.setEnabled(False)
		self.assertFalse(self.provider.enabled)


class TestScreenCaptureProviderYields(unittest.TestCase):
	"""Tests for ScreenCaptureProvider yielding presentations."""

	def setUp(self):
		"""Set up test fixtures."""
		self.provider = ScreenCaptureProvider()
		self.mock_display = MockScreenCaptureDisplay()
		self.mock_obj = MagicMock()

	def test_canProvide_returns_false_when_disabled(self):
		"""Test that canProvide returns False when disabled."""
		self.assertFalse(self.provider.canProvide(self.mock_obj))

	def test_canProvide_returns_true_when_enabled(self):
		"""Test that canProvide returns True when enabled."""
		self.provider.toggle()  # Enable

		self.assertTrue(self.provider.canProvide(self.mock_obj))

	def test_createPresentation_returns_screen_capture_presentation(self):
		"""Test that createPresentation returns a ScreenCapturePresentation when enabled."""
		self.provider.toggle()  # Enable

		presentation = self.provider.createPresentation(self.mock_obj, self.mock_display)

		self.assertIsInstance(presentation, ScreenCapturePresentation)

	def test_createPresentation_reuses_same_instance(self):
		"""Test that createPresentation reuses the same presentation instance to maintain scroll state."""
		self.provider.toggle()  # Enable

		presentation1 = self.provider.createPresentation(self.mock_obj, self.mock_display)
		presentation2 = self.provider.createPresentation(self.mock_obj, self.mock_display)

		# Should be the same instance
		self.assertIs(presentation1, presentation2)

	def test_clears_presentation_on_disable(self):
		"""Test that disabling clears the presentation instance."""
		self.provider.toggle()  # Enable
		presentation1 = self.provider.createPresentation(self.mock_obj, self.mock_display)
		self.provider.toggle()  # Disable
		self.provider.toggle()  # Re-enable

		presentation2 = self.provider.createPresentation(self.mock_obj, self.mock_display)

		# Should be a new instance after re-enabling
		self.assertIsNot(presentation1, presentation2)


class TestScreenCaptureProviderForceForObject(unittest.TestCase):
	"""Tests for ScreenCaptureProvider.forceForObject()."""

	def setUp(self):
		"""Set up test fixtures."""
		self.provider = ScreenCaptureProvider()
		self.mock_display = MockScreenCaptureDisplay()
		self.mock_obj = MagicMock()

	def test_force_for_object_returns_none(self):
		"""Test that forceForObject always returns None (screen capture is toggled, not forced)."""
		result = self.provider.forceForObject(self.mock_obj, self.mock_display)
		self.assertIsNone(result)

	def test_force_for_object_returns_none_even_when_enabled(self):
		"""Test that forceForObject returns None even when provider is enabled."""
		self.provider.toggle()  # Enable
		result = self.provider.forceForObject(self.mock_obj, self.mock_display)
		self.assertIsNone(result)


class TestScreenCaptureProviderIntegration(unittest.TestCase):
	"""Integration tests for ScreenCaptureProvider with PresentationManager."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mock_display = MockScreenCaptureDisplay()
		self.mock_obj = MagicMock()

	def test_provider_works_with_presentation_manager(self):
		"""Test that ScreenCaptureProvider works correctly with PresentationManager."""
		provider = ScreenCaptureProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Initially disabled - should not have active presentation
		manager.update(self.mock_obj)
		self.assertFalse(manager.hasActivePresentation)

		# Enable and update
		provider.toggle()
		manager.update(self.mock_obj)

		# Should have an active presentation
		self.assertTrue(manager.hasActivePresentation)
		self.assertEqual(manager.activePresentation.name, "screenCapture")

	def test_screen_capture_presentation_is_always_valid_in_manager(self):
		"""Test that screen capture presentations remain valid across updates."""
		provider = ScreenCaptureProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Enable and update
		provider.toggle()
		manager.update(self.mock_obj)
		self.assertTrue(manager.hasActivePresentation)

		# Update multiple times - should remain valid
		manager.update(self.mock_obj)
		self.assertTrue(manager.hasActivePresentation)
		manager.update(MagicMock())  # Different object
		self.assertTrue(manager.hasActivePresentation)

	def test_force_screen_capture_returns_false(self):
		"""Test that forcing screen capture mode returns False."""
		provider = ScreenCaptureProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		result = manager.forcePresentation("screenCapture", self.mock_obj)

		# forceForObject returns None, so forcePresentation returns False
		self.assertFalse(result)
		self.assertFalse(manager.isForcedMode)

	def test_toggle_controls_presentation_availability(self):
		"""Test that toggle controls when presentations are available."""
		provider = ScreenCaptureProvider()
		manager = PresentationManager(self.mock_display)
		manager.registerProvider(provider)

		# Disabled - no presentation
		manager.update(self.mock_obj)
		self.assertFalse(manager.hasActivePresentation)

		# Enable - has presentation
		provider.toggle()
		manager.update(self.mock_obj)
		self.assertTrue(manager.hasActivePresentation)

		# Disable again - no presentation
		provider.toggle()
		manager.update(self.mock_obj)
		self.assertFalse(manager.hasActivePresentation)


if __name__ == "__main__":
	unittest.main()
