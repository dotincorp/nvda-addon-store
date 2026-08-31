# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

"""Unit tests for chart Y-axis calculation."""

import unittest
from unittest.mock import MagicMock


class TestYAxisConfig(unittest.TestCase):
	"""Tests for YAxisConfig dataclass."""

	def test_yAxisConfig_creation(self):
		"""YAxisConfig should store all required fields."""
		from addon.utils.chartAxis import YAxisConfig

		config = YAxisConfig(
			minVal=0.0,
			maxVal=100.0,
			step=20.0,
			rowHeight=8,
			numLabels=6,
			dotsPerValue=0.4,
		)

		self.assertEqual(config.minVal, 0.0)
		self.assertEqual(config.maxVal, 100.0)
		self.assertEqual(config.step, 20.0)
		self.assertEqual(config.rowHeight, 8)
		self.assertEqual(config.numLabels, 6)
		self.assertEqual(config.dotsPerValue, 0.4)


class TestChartAxisConstants(unittest.TestCase):
	"""Tests for chart axis constants."""

	def test_constants_exist(self):
		"""Required constants should be defined."""
		from addon.utils.chartAxis import (
			MIN_DOTS_BETWEEN_LABELS,
			MIN_Y_AXIS_LABELS,
			MAX_STEP_MULTIPLIER,
		)

		self.assertIsInstance(MIN_DOTS_BETWEEN_LABELS, int)
		self.assertIsInstance(MIN_Y_AXIS_LABELS, int)
		self.assertIsInstance(MAX_STEP_MULTIPLIER, int)
		self.assertGreater(MIN_DOTS_BETWEEN_LABELS, 0)
		self.assertGreater(MIN_Y_AXIS_LABELS, 0)
		self.assertGreater(MAX_STEP_MULTIPLIER, 0)


class TestRoundToNiceNumber(unittest.TestCase):
	"""Tests for roundToNiceNumber function."""

	def test_rounds_to_1(self):
		"""Values near 1 should round to 1."""
		from addon.utils.chartAxis import roundToNiceNumber

		self.assertEqual(roundToNiceNumber(0.8), 1)
		self.assertEqual(roundToNiceNumber(1.2), 1)

	def test_rounds_to_2(self):
		"""Values near 2 should round to 2."""
		from addon.utils.chartAxis import roundToNiceNumber

		self.assertEqual(roundToNiceNumber(1.6), 2)
		self.assertEqual(roundToNiceNumber(2.4), 2)

	def test_rounds_to_5(self):
		"""Values near 5 should round to 5."""
		from addon.utils.chartAxis import roundToNiceNumber

		self.assertEqual(roundToNiceNumber(3.5), 5)
		self.assertEqual(roundToNiceNumber(6.0), 5)

	def test_rounds_to_10(self):
		"""Values near 10 should round to 10."""
		from addon.utils.chartAxis import roundToNiceNumber

		self.assertEqual(roundToNiceNumber(8), 10)
		self.assertEqual(roundToNiceNumber(12), 10)

	def test_rounds_larger_values(self):
		"""Should handle larger values correctly."""
		from addon.utils.chartAxis import roundToNiceNumber

		self.assertEqual(roundToNiceNumber(23), 20)
		self.assertEqual(roundToNiceNumber(45), 50)
		self.assertEqual(roundToNiceNumber(180), 200)

	def test_rounds_smaller_values(self):
		"""Should handle values less than 1."""
		from addon.utils.chartAxis import roundToNiceNumber

		self.assertEqual(roundToNiceNumber(0.3), 0.5)
		self.assertEqual(roundToNiceNumber(0.08), 0.1)


class TestCalculateYAxisConfigStrategy2(unittest.TestCase):
	"""Tests for calculateYAxisConfig with Strategy 2 (no Excel axis)."""

	def test_basic_calculation(self):
		"""Should calculate config from data values alone."""
		from addon.utils.chartAxis import calculateYAxisConfig

		config = calculateYAxisConfig(
			excelAxis=None,
			dataValues=[10, 20, 30, 40, 50],
			availableHeight=40,
		)

		self.assertIsNotNone(config)
		self.assertLessEqual(config.minVal, 10)
		self.assertGreaterEqual(config.maxVal, 50)
		self.assertGreater(config.step, 0)
		self.assertGreaterEqual(config.numLabels, 3)

	def test_respects_min_dots_between_labels(self):
		"""Row height should be at least MIN_DOTS_BETWEEN_LABELS."""
		from addon.utils.chartAxis import calculateYAxisConfig, MIN_DOTS_BETWEEN_LABELS

		config = calculateYAxisConfig(
			excelAxis=None,
			dataValues=[0, 100],
			availableHeight=40,
		)

		self.assertGreaterEqual(config.rowHeight, MIN_DOTS_BETWEEN_LABELS)

	def test_respects_min_labels(self):
		"""Should have at least MIN_Y_AXIS_LABELS labels."""
		from addon.utils.chartAxis import calculateYAxisConfig, MIN_Y_AXIS_LABELS

		config = calculateYAxisConfig(
			excelAxis=None,
			dataValues=[0, 10],
			availableHeight=40,
		)

		self.assertGreaterEqual(config.numLabels, MIN_Y_AXIS_LABELS)

	def test_uses_nice_step_values(self):
		"""Step should be a nice number."""
		from addon.utils.chartAxis import calculateYAxisConfig

		config = calculateYAxisConfig(
			excelAxis=None,
			dataValues=[0, 47],
			availableHeight=40,
		)

		# Step should be one of: 1, 2, 5, 10, 20, 50, etc.
		niceSteps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]
		self.assertIn(config.step, niceSteps)


class TestCalculateYAxisConfigStrategy1(unittest.TestCase):
	"""Tests for calculateYAxisConfig with Strategy 1 (Excel axis)."""

	def _makeExcelAxis(self, minScale: float, maxScale: float, majorUnit: float) -> MagicMock:
		"""Create a mock Excel axis object."""
		axis = MagicMock()
		axis.minimumScale = minScale
		axis.maximumScale = maxScale
		axis.majorUnit = majorUnit
		return axis

	def test_uses_excel_min(self):
		"""Should use Excel's minimumScale as min value."""
		from addon.utils.chartAxis import calculateYAxisConfig

		excelAxis = self._makeExcelAxis(minScale=0, maxScale=100, majorUnit=20)

		config = calculateYAxisConfig(
			excelAxis=excelAxis,
			dataValues=[15, 25, 35, 45],
			availableHeight=40,
		)

		self.assertEqual(config.minVal, 0)

	def test_uses_data_max_not_excel_max(self):
		"""Should use data max, not Excel's max (to avoid wasting space)."""
		from addon.utils.chartAxis import calculateYAxisConfig

		excelAxis = self._makeExcelAxis(minScale=0, maxScale=100, majorUnit=20)

		config = calculateYAxisConfig(
			excelAxis=excelAxis,
			dataValues=[10, 20, 30, 45],
			availableHeight=40,
		)

		# Max should be based on data (45), not Excel's max (100)
		self.assertLessEqual(config.maxVal, 60)  # Should round up to next step

	def test_uses_excel_step_when_fits(self):
		"""Should use Excel's majorUnit when it fits the display."""
		from addon.utils.chartAxis import calculateYAxisConfig

		# With 40 dots and step=20, we'd have 3 labels (0, 20, 40)
		# 40 / 3 = 13 dots per label, which is >= MIN_DOTS_BETWEEN_LABELS
		excelAxis = self._makeExcelAxis(minScale=0, maxScale=100, majorUnit=20)

		config = calculateYAxisConfig(
			excelAxis=excelAxis,
			dataValues=[10, 20, 30, 40],
			availableHeight=40,
		)

		self.assertEqual(config.step, 20)

	def test_doubles_step_when_too_fine(self):
		"""Should double Excel's step if original is too fine."""
		from addon.utils.chartAxis import calculateYAxisConfig

		# With step=5 and data 0-45, we'd have 10 labels
		# 30 / 9 = 3.3 dots per label, which is < MIN_DOTS_BETWEEN_LABELS (4)
		# Should double to step=10, giving 5 labels, 7.5 dots per label
		excelAxis = self._makeExcelAxis(minScale=0, maxScale=100, majorUnit=5)

		config = calculateYAxisConfig(
			excelAxis=excelAxis,
			dataValues=[0, 10, 20, 30, 40],
			availableHeight=30,
		)

		self.assertEqual(config.step, 10)

	def test_falls_back_to_strategy2_when_step_too_large(self):
		"""Should fall back to Strategy 2 if Excel step doesn't work."""
		from addon.utils.chartAxis import calculateYAxisConfig

		# With step=50 and data 0-45, we'd only have 1-2 labels
		# This is less than MIN_Y_AXIS_LABELS, so fall back
		excelAxis = self._makeExcelAxis(minScale=0, maxScale=100, majorUnit=50)

		config = calculateYAxisConfig(
			excelAxis=excelAxis,
			dataValues=[5, 10, 15, 20, 25],
			availableHeight=40,
		)

		# Should use a smaller step from Strategy 2
		self.assertLess(config.step, 50)


class TestGetActiveBarIndex(unittest.TestCase):
	"""Tests for getActiveBarIndex function."""

	def test_returns_position_when_on_point(self):
		"""Should return ActiveBarPosition when navigator is on a chart point."""
		from addon.utils.chartAxis import ActiveBarPosition, getActiveBarIndex

		chartObj = MagicMock()
		navObj = MagicMock()
		navObj.arg1 = 2  # 1-based series index
		navObj.arg2 = 3  # 1-based point index
		navObj.officeChartObject = chartObj

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsInstance(result, ActiveBarPosition)
		self.assertEqual(result.seriesIndex, 1)  # 0-based
		self.assertEqual(result.pointIndex, 2)  # 0-based

	def test_returns_none_when_no_arg1(self):
		"""Should return None when navigator has no arg1 attribute."""
		from addon.utils.chartAxis import getActiveBarIndex

		chartObj = MagicMock()
		navObj = MagicMock(spec=["arg2", "officeChartObject"])
		navObj.arg2 = 1
		navObj.officeChartObject = chartObj

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsNone(result)

	def test_returns_none_when_no_arg2(self):
		"""Should return None when navigator has no arg2 attribute."""
		from addon.utils.chartAxis import getActiveBarIndex

		chartObj = MagicMock()
		navObj = MagicMock(spec=["arg1", "officeChartObject"])
		navObj.arg1 = 1
		navObj.officeChartObject = chartObj

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsNone(result)

	def test_returns_none_when_no_officeChartObject(self):
		"""Should return None when navigator has no officeChartObject."""
		from addon.utils.chartAxis import getActiveBarIndex

		chartObj = MagicMock()
		navObj = MagicMock(spec=["arg1", "arg2"])
		navObj.arg1 = 1
		navObj.arg2 = 1

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsNone(result)

	def test_returns_none_when_different_chart(self):
		"""Should return None when navigator is on a different chart."""
		from addon.utils.chartAxis import getActiveBarIndex

		chartObj = MagicMock()
		otherChartObj = MagicMock()
		navObj = MagicMock()
		navObj.arg1 = 1
		navObj.arg2 = 1
		navObj.officeChartObject = otherChartObj

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsNone(result)

	def test_returns_none_when_arg1_is_minus_one(self):
		"""Should return None when arg1 is -1 (chart level, not series)."""
		from addon.utils.chartAxis import getActiveBarIndex

		chartObj = MagicMock()
		navObj = MagicMock()
		navObj.arg1 = -1
		navObj.arg2 = 1
		navObj.officeChartObject = chartObj

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsNone(result)

	def test_returns_none_when_arg2_is_minus_one(self):
		"""Should return None when arg2 is -1 (series level, not point)."""
		from addon.utils.chartAxis import getActiveBarIndex

		chartObj = MagicMock()
		navObj = MagicMock()
		navObj.arg1 = 1
		navObj.arg2 = -1
		navObj.officeChartObject = chartObj

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsNone(result)

	def test_returns_none_when_arg2_is_none(self):
		"""Should return None when arg2 is None."""
		from addon.utils.chartAxis import getActiveBarIndex

		chartObj = MagicMock()
		navObj = MagicMock()
		navObj.arg1 = 1
		navObj.arg2 = None
		navObj.officeChartObject = chartObj

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsNone(result)

	def test_returns_none_when_arg1_is_none(self):
		"""Should return None when arg1 is None."""
		from addon.utils.chartAxis import getActiveBarIndex

		chartObj = MagicMock()
		navObj = MagicMock()
		navObj.arg1 = None
		navObj.arg2 = 1
		navObj.officeChartObject = chartObj

		result = getActiveBarIndex(navObj, chartObj)

		self.assertIsNone(result)


class TestActiveBarMarkerStyle(unittest.TestCase):
	"""Tests for ActiveBarMarkerStyle enum and related constants."""

	def test_enum_values_exist(self):
		"""ActiveBarMarkerStyle should have FLANKING and UNDERLINE values."""
		from addon.utils.chartAxis import ActiveBarMarkerStyle

		self.assertTrue(hasattr(ActiveBarMarkerStyle, "FLANKING"))
		self.assertTrue(hasattr(ActiveBarMarkerStyle, "UNDERLINE"))

	def test_marker_constants_exist(self):
		"""Marker-related constants should be defined."""
		from addon.utils.chartAxis import (
			ACTIVE_BAR_MARKER_STYLE,
			ACTIVE_BAR_MARKER_HEIGHT,
			UNDERLINE_EXTRA_HEIGHT,
			ActiveBarMarkerStyle,
		)

		self.assertIsInstance(ACTIVE_BAR_MARKER_STYLE, ActiveBarMarkerStyle)
		self.assertIsInstance(ACTIVE_BAR_MARKER_HEIGHT, int)
		self.assertIsInstance(UNDERLINE_EXTRA_HEIGHT, int)


class MockTactileBuffer:
	"""A mock tactile graphics buffer for testing drawing functions."""

	def __init__(self, width: int = 100, height: int = 100):
		self.dots: list[tuple[int, int]] = []
		self.width = width
		self.height = height

	def setDot(self, x: int, y: int):
		self.dots.append((x, y))


class TestDrawHorizontalRulerWithActiveBar(unittest.TestCase):
	"""Tests for drawHorizontalRuler with active bar marker."""

	def test_accepts_activeColIndex_parameter(self):
		"""drawHorizontalRuler should accept activeColIndex parameter."""
		from addon.utils.drawing import drawHorizontalRuler

		buffer = MockTactileBuffer()

		# Should not raise an error
		drawHorizontalRuler(
			buffer,
			x=0,
			y=0,
			colStartOffset=0,
			colEndOffset=3,
			spacing=4,
			activeColIndex=1,
		)

		self.assertGreater(len(buffer.dots), 0)

	def test_draws_marker_at_active_column(self):
		"""Should draw extra dots at active column position."""
		from addon.utils.drawing import drawHorizontalRuler

		bufferWithoutActive = MockTactileBuffer()
		bufferWithActive = MockTactileBuffer()

		# Draw without active
		drawHorizontalRuler(
			bufferWithoutActive,
			x=0,
			y=0,
			colStartOffset=0,
			colEndOffset=3,
			spacing=4,
			activeColIndex=None,
		)

		# Draw with active
		drawHorizontalRuler(
			bufferWithActive,
			x=0,
			y=0,
			colStartOffset=0,
			colEndOffset=3,
			spacing=4,
			activeColIndex=1,
		)

		# Active version should have more dots (the marker)
		self.assertGreater(len(bufferWithActive.dots), len(bufferWithoutActive.dots))


if __name__ == "__main__":
	unittest.main()
