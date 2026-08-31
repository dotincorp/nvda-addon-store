# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

"""
Chart classes for tactile graphics display.

Provides Chart, ScrollableChart, and BarChart classes that render to
DpTactileGraphicsBuffer using the drawing primitives from drawing.py.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from baseObject import AutoPropertyObject

if TYPE_CHECKING:
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from .chartAxis import YAxisConfig, calculateYAxisConfig
	from .drawing import (
		BRAILLE_CELL_SPACING,
		BRAILLE_CELL_WIDTH,
		drawHorizontalRuler,
		drawLine,
		drawVerticalRuler,
		generateAZColumnLabel,
		generateYValueLabels,
	)

# Runtime imports using NVDA's addon module loading
if not TYPE_CHECKING:
	import addonHandler

	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	chartAxis_module = addon.loadModule("utils.chartAxis")
	YAxisConfig = chartAxis_module.YAxisConfig
	calculateYAxisConfig = chartAxis_module.calculateYAxisConfig
	drawing_module = addon.loadModule("utils.drawing")
	BRAILLE_CELL_SPACING = drawing_module.BRAILLE_CELL_SPACING
	BRAILLE_CELL_WIDTH = drawing_module.BRAILLE_CELL_WIDTH
	drawHorizontalRuler = drawing_module.drawHorizontalRuler
	drawLine = drawing_module.drawLine
	drawVerticalRuler = drawing_module.drawVerticalRuler
	generateAZColumnLabel = drawing_module.generateAZColumnLabel
	generateYValueLabels = drawing_module.generateYValueLabels


class Chart(AutoPropertyObject):
	"""Base class for chart rendering.

	Uses AutoPropertyObject for NVDA-style cached properties via _get_ methods.
	"""

	#: Height of X-axis ruler area in dots
	#: 6 dots for underline mode: line(1) + gap(1) + label(3) + underline(1)
	xAxisHeight: int = 6
	#: Minimum column width in dots
	minColWidth: int = 4
	#: Starting column offset for scrolling
	colStartOffset: int = 0
	#: Index of active column to highlight (0-based), or None
	activeColIndex: int | None = None
	#: Index of active series to highlight (0-based), or None
	activeSeriesIndex: int | None = None
	#: Whether to show vertical ruler
	showVerticalRuler: bool
	#: Whether to show horizontal ruler
	showHorizontalRuler: bool
	#: Y-axis configuration
	yAxisConfig: YAxisConfig
	#: Dataset name -> values mapping
	datasets: dict[str, list[float]]
	#: Destination width in dots
	destWidth: int
	#: Destination height in dots
	destHeight: int

	# Cached property values (set by _get_ methods)
	numTotalCols: int
	colEndOffset: int
	plotHeight: int
	plotX: int
	plotWidth: int
	colWidth: int
	verticalRulerWidth: int
	verticalRulerHeight: int
	rulerHeight: int
	yOffset: int

	def __init__(
		self,
		destWidth: int,
		destHeight: int,
		datasets: dict[str, list[float]],
		excelAxis: Any | None = None,
		showVerticalRuler: bool = True,
		showHorizontalRuler: bool = True,
	):
		"""Initialize chart.

		:param destWidth: Destination width in dots.
		:param destHeight: Destination height in dots.
		:param datasets: Dictionary mapping series names to value lists.
		:param excelAxis: Excel axis object for Y-axis bounds (optional).
		:param showVerticalRuler: Whether to show Y-axis ruler.
		:param showHorizontalRuler: Whether to show X-axis ruler.
		"""
		super().__init__()
		self.destWidth = destWidth
		self.destHeight = destHeight
		self.datasets = datasets
		self.showVerticalRuler = showVerticalRuler
		self.showHorizontalRuler = showHorizontalRuler

		# Calculate Y-axis configuration based on available plot height
		plotHeight = destHeight - self.xAxisHeight if showHorizontalRuler else destHeight
		allValues = [v for values in datasets.values() for v in values]
		self.yAxisConfig = calculateYAxisConfig(excelAxis, allValues, plotHeight)

	def _get_numTotalCols(self) -> int:
		"""Total number of data columns (max across all series)."""
		if not self.datasets:
			return 0
		return max(len(values) for values in self.datasets.values())

	def _get_colEndOffset(self) -> int:
		"""Ending column offset."""
		return self.numTotalCols

	def _get_plotHeight(self) -> int:
		"""Height available for plot area."""
		if self.showHorizontalRuler:
			return self.destHeight - self.xAxisHeight
		return self.destHeight

	plotY: int = 0

	def _get_plotX(self) -> int:
		"""X position where plot starts."""
		if self.showVerticalRuler:
			return self.verticalRulerWidth
		return 0

	def _get_plotWidth(self) -> int:
		"""Width available for plot area."""
		return self.destWidth - self.plotX

	def _get_colWidth(self) -> int:
		"""Width of each column."""
		if self.numTotalCols == 0:
			return self.minColWidth
		minColWidth = self.minColWidth
		totalPlotWidth = minColWidth * self.numTotalCols
		if totalPlotWidth < self.plotWidth:
			return self.plotWidth // self.numTotalCols
		return minColWidth

	def _get_verticalRulerWidth(self) -> int:
		"""Calculate vertical ruler width without drawing."""
		if not self.showVerticalRuler:
			return 0
		# Estimate based on label length
		labels = self._getYLabels()
		maxLabelLen = max(len(label) for label in labels) if labels else 1
		return maxLabelLen * (BRAILLE_CELL_WIDTH + BRAILLE_CELL_SPACING) + 2

	def _get_verticalRulerHeight(self) -> int:
		"""Calculate vertical ruler height (intervals between labels)."""
		return (self.yAxisConfig.numLabels - 1) * self.yAxisConfig.rowHeight

	def _get_rulerHeight(self) -> int:
		"""Alias for verticalRulerHeight for bar scaling."""
		return self.verticalRulerHeight

	def _get_yOffset(self) -> int:
		"""Y offset to anchor chart to bottom (x-axis)."""
		return self.plotHeight - self.rulerHeight

	def _getYLabels(self) -> list[str]:
		"""Get Y-axis labels from config."""
		return generateYValueLabels(
			self.yAxisConfig.minVal,
			self.yAxisConfig.maxVal,
			self.yAxisConfig.numLabels,
			numberFormat=self.yAxisConfig.numberFormat,
			formatDecimalSep=self.yAxisConfig.formatDecimalSep,
		)

	def draw(self, buffer: DpTactileGraphicsBuffer) -> None:
		"""Draw the chart to the buffer.

		:param buffer: The tactile graphics buffer to draw on.
		"""
		if self.showVerticalRuler:
			drawVerticalRuler(
				buffer,
				0,
				self.yOffset,
				self.yAxisConfig.minVal,
				self.yAxisConfig.maxVal,
				self.yAxisConfig.numLabels,
				self.yAxisConfig.rowHeight,
				numberFormat=self.yAxisConfig.numberFormat,
				formatDecimalSep=self.yAxisConfig.formatDecimalSep,
			)

		if self.showHorizontalRuler:
			drawHorizontalRuler(
				buffer,
				self.plotX,
				self.plotY + self.plotHeight,
				self.colStartOffset,
				self.colEndOffset,
				self.colWidth,
				activeColIndex=self.activeColIndex,
			)

		self.drawPlot(buffer)

	@abstractmethod
	def drawPlot(self, buffer: DpTactileGraphicsBuffer) -> None:
		"""Draw the plot area. Subclasses must implement.

		:param buffer: The tactile graphics buffer to draw on.
		"""
		...


class ScrollableChart(Chart):
	"""Chart with scrolling support for datasets wider than display."""

	maxVisibleCols: int

	def _get_minColWidth(self) -> int:
		"""Minimum column width accounting for labels."""
		minColWidth = 4  # Base minimum
		if self.showHorizontalRuler and self.numTotalCols > 0:
			largestLabel = generateAZColumnLabel(self.numTotalCols - 1)
			labelColWidth = len(largestLabel) * (BRAILLE_CELL_WIDTH + BRAILLE_CELL_SPACING)
			minColWidth = max(minColWidth, labelColWidth)
		return minColWidth

	def _get_maxVisibleCols(self) -> int:
		"""Maximum columns visible at once."""
		return self.plotWidth // self.colWidth

	def _get_colEndOffset(self) -> int:
		"""Ending column offset for current scroll position."""
		return min(self.colStartOffset + self.maxVisibleCols, self.numTotalCols)

	def scrollForward(self) -> bool:
		"""Scroll chart forward.

		:returns: True if scrolled, False if at end.
		"""
		if self.colEndOffset == self.numTotalCols:
			return False
		for _ in range(self.maxVisibleCols):
			self.colStartOffset += 1
			if self.colEndOffset == self.numTotalCols:
				break
		return True

	def scrollBack(self) -> bool:
		"""Scroll chart backward.

		:returns: True if scrolled, False if at beginning.
		"""
		if self.colStartOffset == 0:
			return False
		for _ in range(self.maxVisibleCols):
			self.colStartOffset -= 1
			if self.colStartOffset == 0:
				break
		return True

	def _ensureActiveBarVisible(self) -> None:
		"""Adjust scroll position to keep active bar in view with minimal scrolling.

		When moving right, the active bar appears at the rightmost position.
		When moving left, the active bar appears at the leftmost position.
		"""
		if self.activeColIndex is None:
			return

		# Active bar is before visible range - scroll back to show it at left edge
		if self.activeColIndex < self.colStartOffset:
			self.colStartOffset = self.activeColIndex

		# Active bar is after visible range - scroll forward to show it at right edge
		elif self.activeColIndex >= self.colEndOffset:
			self.colStartOffset = self.activeColIndex - self.maxVisibleCols + 1

	def draw(self, buffer: DpTactileGraphicsBuffer) -> None:
		"""Draw the chart, ensuring active bar is visible first.

		:param buffer: The tactile graphics buffer to draw on.
		"""
		self._ensureActiveBarVisible()
		super().draw(buffer)


def _drawDiscreteDataset(
	buffer: DpTactileGraphicsBuffer,
	destX: int,
	destY: int,
	rulerHeight: int,
	minY: float,
	dotsPerValue: float,
	values: list[float],
	barWidth: int,
	colWidth: int,
) -> None:
	"""Draw a discrete dataset as vertical bars.

	:param buffer: The tactile graphics buffer to draw on.
	:param destX: Starting X position.
	:param destY: Starting Y position (top of ruler area).
	:param rulerHeight: Height of ruler area (bars scale to this).
	:param minY: Minimum Y value.
	:param dotsPerValue: Scaling factor (dots per value unit).
	:param values: Data values to plot.
	:param barWidth: Width of each bar.
	:param colWidth: Width of each column (including spacing).
	"""
	for index, value in enumerate(values):
		# Calculate bar height using consistent dotsPerValue scaling
		barHeight = int((value - minY) * dotsPerValue)

		x = destX + (index * colWidth)
		# Draw from bottom up
		startY = destY + rulerHeight - barHeight
		endY = destY + rulerHeight

		for subY in range(startY, endY):
			drawLine(buffer, x, subY, barWidth, vertical=False)


class BarChart(ScrollableChart):
	"""Bar chart with discrete vertical bars."""

	#: Width of each bar in dots
	barWidth: int = 2
	#: Gap between bars in same column
	barGap: int = 1

	colGap: int

	def _get_colGap(self) -> int:
		"""Gap between columns."""
		if len(self.datasets) > 1:
			return 2
		return 1

	def _get_minColWidth(self) -> int:
		"""Minimum column width for bar chart."""
		numDatasets = len(self.datasets)
		baseMinColWidth = super()._get_minColWidth()
		minColWidthWithBars = ((self.barWidth + self.barGap) * numDatasets) + self.colGap
		return max(baseMinColWidth, minColWidthWithBars)

	def drawPlot(self, buffer: DpTactileGraphicsBuffer) -> None:
		"""Draw bar chart plot.

		:param buffer: The tactile graphics buffer to draw on.
		"""
		for index, (_name, dataset) in enumerate(self.datasets.items()):
			xOffset = 2 + (self.barWidth + self.barGap) * index
			visibleData = list(dataset[self.colStartOffset : self.colEndOffset])

			_drawDiscreteDataset(
				buffer,
				self.plotX + xOffset,
				self.plotY + self.yOffset,
				self.rulerHeight,
				self.yAxisConfig.minVal,
				self.yAxisConfig.dotsPerValue,
				visibleData,
				self.barWidth,
				self.colWidth,
			)

		# Draw horizontal trace line from active bar to Y-axis
		if self.activeColIndex is not None and self.showVerticalRuler:
			visibleIndex = self.activeColIndex - self.colStartOffset
			if 0 <= visibleIndex < (self.colEndOffset - self.colStartOffset):
				# Determine which series to use (default to first if not specified)
				seriesIndex = self.activeSeriesIndex if self.activeSeriesIndex is not None else 0

				# Get the dataset for the active series
				datasetsList = list(self.datasets.values())

				# Bounds check for series index
				if seriesIndex < 0 or seriesIndex >= len(datasetsList):
					return

				activeDataset = datasetsList[seriesIndex]

				# Bounds check for point index
				if self.activeColIndex < 0 or self.activeColIndex >= len(activeDataset):
					return

				activeValue = activeDataset[self.activeColIndex]

				# Calculate bar top Y position
				barHeight = int((activeValue - self.yAxisConfig.minVal) * self.yAxisConfig.dotsPerValue)
				barTopY = self.plotY + self.yOffset + self.rulerHeight - barHeight
				# Y-axis vertical line is at verticalRulerWidth - 1
				yAxisLineX = self.verticalRulerWidth - 1
				# Bar left edge position includes series offset
				xOffset = 2 + (self.barWidth + self.barGap) * seriesIndex
				barLeftX = self.plotX + xOffset + (visibleIndex * self.colWidth)
				# Draw horizontal line from Y-axis to bar
				lineLength = barLeftX - yAxisLineX
				if lineLength > 0:
					drawLine(buffer, yAxisLineX, barTopY, lineLength, vertical=False)
