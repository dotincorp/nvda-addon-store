# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

"""
Chart Y-axis calculation utilities.

This module provides utilities for calculating optimal Y-axis configuration
for tactile chart displays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, NamedTuple


class ActiveBarPosition(NamedTuple):
	"""Position of active bar in a chart."""

	seriesIndex: int  # 0-based
	pointIndex: int  # 0-based


# Minimum dots between Y-axis labels for tactile readability
MIN_DOTS_BETWEEN_LABELS: int = 4

# Minimum number of Y-axis labels for a useful chart
MIN_Y_AXIS_LABELS: int = 3

# Maximum multiplier to try on Excel's step before giving up
MAX_STEP_MULTIPLIER: int = 2


class ActiveBarMarkerStyle(Enum):
	"""Style options for marking the active bar on the X-axis."""

	FLANKING = auto()  # Vertical lines on each side of letter
	UNDERLINE = auto()  # Horizontal line below letter


# Which marker style to use
ACTIVE_BAR_MARKER_STYLE: ActiveBarMarkerStyle = ActiveBarMarkerStyle.UNDERLINE

# Height of flanking lines (dots)
ACTIVE_BAR_MARKER_HEIGHT: int = 3

# Extra height needed for underline style
UNDERLINE_EXTRA_HEIGHT: int = 1


@dataclass
class YAxisConfig:
	"""Configuration for Y-axis rendering.

	:param minVal: Minimum value on the axis.
	:param maxVal: Maximum value on the axis.
	:param step: Step between axis labels.
	:param rowHeight: Height in dots between labels.
	:param numLabels: Number of labels on the axis.
	:param dotsPerValue: Scaling factor (dots per value unit) for consistent bar/tick alignment.
	:param numberFormat: Excel number format string for labels (e.g., "0.00", "#,##0").
	:param formatDecimalSep: Decimal separator used in numberFormat (locale-dependent).
	"""

	minVal: float
	maxVal: float
	step: float
	rowHeight: int
	numLabels: int
	dotsPerValue: float
	numberFormat: str | None = None
	formatDecimalSep: str = "."


def roundToNiceNumber(value: float) -> float:
	"""Round a value to a 'nice' number for axis labels.

	Nice numbers are 1, 2, 5, 10, 20, 50, 100, etc.

	:param value: The value to round.
	:returns: The nearest nice number.
	"""
	if value <= 0:
		return 1.0

	# Find the order of magnitude
	exponent = math.floor(math.log10(value))
	fraction = value / (10**exponent)

	# Round to nearest nice fraction (1, 2, 5)
	if fraction < 1.5:
		niceFraction = 1
	elif fraction <= 2.5:
		niceFraction = 2
	elif fraction < 7.5:
		niceFraction = 5
	else:
		niceFraction = 10

	return niceFraction * (10**exponent)


def calculateYAxisConfig(
	excelAxis: Any | None,
	dataValues: list[float],
	availableHeight: int,
) -> YAxisConfig:
	"""Calculate optimal Y-axis configuration for chart rendering.

	Uses two strategies:
	1. If excelAxis is provided, try to honor Excel's step value
	2. Fallback: calculate even spacing from data values

	:param excelAxis: Excel axis object with minimumScale, maximumScale, majorUnit (or None).
	:param dataValues: List of data values to display.
	:param availableHeight: Available height in dots for the chart area.
	:returns: YAxisConfig with optimal settings.
	"""
	# Extract number format and decimal separator from Excel axis if available
	numberFormat: str | None = None
	formatDecimalSep: str = "."
	if excelAxis is not None:
		try:
			numberFormat = excelAxis.TickLabels.NumberFormat
		except Exception:
			pass

		# Try to get decimal separator from multiple sources (in priority order):
		# 1. Excel's Application.International (works in Excel, not PowerPoint)
		# 2. Detect from number format pattern (works if format has both . and ,)
		# 3. Fall back to "." as default
		try:
			# xlDecimalSeparator = 3 (Excel-specific)
			formatDecimalSep = excelAxis.Application.International(3)
		except Exception:
			# PowerPoint doesn't have Application.International
			# Try to detect from the number format pattern
			if numberFormat:
				from .drawing import detectDecimalSeparatorFromFormat

				detected = detectDecimalSeparatorFromFormat(numberFormat)
				if detected:
					formatDecimalSep = detected

	# Handle empty dataValues
	if not dataValues:
		return YAxisConfig(
			minVal=0.0,
			maxVal=1.0,
			step=1.0,
			rowHeight=max(MIN_DOTS_BETWEEN_LABELS, availableHeight),
			numLabels=2,
			dotsPerValue=min(1.0, availableHeight),
			numberFormat=numberFormat,
			formatDecimalSep=formatDecimalSep,
		)

	dataMin = min(dataValues)
	dataMax = max(dataValues)

	# Strategy 1: Try to honor Excel's step value
	if excelAxis is not None:
		try:
			axisMin = excelAxis.minimumScale
			axisStep = excelAxis.majorUnit

			for multiplier in range(1, MAX_STEP_MULTIPLIER + 1):
				step = axisStep * multiplier
				# Calculate labels needed to cover data range from axis min
				# Use ceil to ensure maxVal covers dataMax (e.g., 21780 with step 5000 needs 6 labels, not 5)
				numLabelsNeeded = math.ceil((dataMax - axisMin) / step) + 1

				# If the natural number of labels is less than minimum, this step is too large
				if numLabelsNeeded < MIN_Y_AXIS_LABELS:
					continue  # Try next multiplier or fall back

				valueRange = (numLabelsNeeded - 1) * step

				# Calculate dotsPerValue (cap at 1.0 for ideal 1:1 mapping)
				dotsPerValue = min(1.0, availableHeight / valueRange)

				rowHeight = round(step * dotsPerValue)
				totalRulerHeight = (numLabelsNeeded - 1) * rowHeight

				# If rounding up causes ruler to exceed available height, use floor instead
				if totalRulerHeight > availableHeight:
					rowHeight = int(step * dotsPerValue)
					totalRulerHeight = (numLabelsNeeded - 1) * rowHeight

				# Recalculate dotsPerValue to match rounded rowHeight for exact tick alignment
				dotsPerValue = rowHeight / step

				if rowHeight >= MIN_DOTS_BETWEEN_LABELS and totalRulerHeight <= availableHeight:
					return YAxisConfig(
						minVal=axisMin,
						maxVal=axisMin + (numLabelsNeeded - 1) * step,
						step=step,
						rowHeight=rowHeight,
						numLabels=numLabelsNeeded,
						dotsPerValue=dotsPerValue,
						numberFormat=numberFormat,
						formatDecimalSep=formatDecimalSep,
					)

		except (AttributeError, TypeError):
			pass  # Fall back to Strategy 2

	# Strategy 2: Even spacing fallback
	# For bar charts, Y-axis should start at 0 (not dataMin) so bars show true magnitude
	axisMin = 0.0 if dataMin >= 0 else dataMin  # Start at 0 for positive data, or dataMin if negative
	dataRange = dataMax - axisMin
	if dataRange == 0:
		dataRange = 1  # Avoid division by zero

	# Calculate dotsPerValue (cap at 1.0, min 0.001 to prevent division by zero)
	dotsPerValue = max(0.001, min(1.0, availableHeight / dataRange))

	# Find a nice step that gives rowHeight >= MIN_DOTS_BETWEEN_LABELS
	minStep = MIN_DOTS_BETWEEN_LABELS / dotsPerValue
	step = roundToNiceNumber(minStep)

	# Ensure step is at least minStep (roundToNiceNumber might round down)
	if step < minStep:
		step = roundToNiceNumber(minStep * 1.5)

	# Use ceil to ensure maxVal covers dataMax
	numLabels = math.ceil(dataRange / step) + 1
	numLabels = max(numLabels, MIN_Y_AXIS_LABELS)

	# Recalculate maxVal based on nice step
	maxVal = axisMin + (numLabels - 1) * step

	# Recalculate dotsPerValue based on final axis range
	valueRange = maxVal - axisMin
	dotsPerValue = min(1.0, availableHeight / valueRange)

	rowHeight = round(step * dotsPerValue)
	totalRulerHeight = (numLabels - 1) * rowHeight

	# If rounding up causes ruler to exceed available height, use floor instead
	if totalRulerHeight > availableHeight:
		rowHeight = int(step * dotsPerValue)

	# Recalculate dotsPerValue to match rounded rowHeight for exact tick alignment
	dotsPerValue = rowHeight / step

	return YAxisConfig(
		minVal=axisMin,
		maxVal=maxVal,
		step=step,
		rowHeight=rowHeight,
		numLabels=numLabels,
		dotsPerValue=dotsPerValue,
		numberFormat=numberFormat,
		formatDecimalSep=formatDecimalSep,
	)


def getActiveBarIndex(navObj: Any, chartObj: Any) -> ActiveBarPosition | None:
	"""Get 0-based position of active bar from navigator object.

	:param navObj: The current navigator object.
	:param chartObj: The chart's Office chart object.
	:returns: ActiveBarPosition with seriesIndex and pointIndex (both 0-based),
	          or None if not on a chart point.
	"""
	# Check if navigator is on a chart point
	if not hasattr(navObj, "officeChartObject"):
		return None

	# Verify it's the same chart
	if navObj.officeChartObject != chartObj:
		return None

	# arg1 is 1-based series index, arg2 is 1-based point index
	# See nvda/source/NVDAObjects/window/_msOfficeChart.py
	seriesIndex = getattr(navObj, "arg1", None)
	pointIndex = getattr(navObj, "arg2", None)

	# Both must be valid (not None or -1)
	if seriesIndex is None or seriesIndex == -1:
		return None
	if pointIndex is None or pointIndex == -1:
		return None

	return ActiveBarPosition(
		seriesIndex=seriesIndex - 1,  # Convert to 0-based
		pointIndex=pointIndex - 1,  # Convert to 0-based
	)
