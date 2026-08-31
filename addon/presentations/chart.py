# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated

"""
Chart presentation for DotPad tactile display.

This module provides ChartPresentation and ChartProvider for rendering
chart content to the tactile display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import api

from .base import Presentation, PresentationProvider

if TYPE_CHECKING:
	from NVDAObjects import NVDAObject

	from ..brailleDisplayDrivers.dotPad.driver import Display
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from ..extension_points.review_tracking import TriggerReason
	from ..utils.chart import BarChart
	from ..utils.data import Chart
	from ..utils.chartAxis import getActiveBarIndex

# Runtime imports using NVDA's addon module loading
if not TYPE_CHECKING:
	import addonHandler

	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	DpTactileGraphicsBuffer = addon.loadModule(
		"brailleDisplayDrivers.dotPad.tactileBuffer",
	).DpTactileGraphicsBuffer
	Chart = addon.loadModule("utils.chart").Chart
	BarChart = addon.loadModule("utils.chart").BarChart
	chartAxis_module = addon.loadModule("utils.chartAxis")
	ActiveBarPosition = chartAxis_module.ActiveBarPosition
	getActiveBarIndex = chartAxis_module.getActiveBarIndex


class ChartPresentation(Presentation):
	"""Presentation that renders chart content to the tactile display.

	This presentation wraps an existing Chart object and converts it to
	tactile graphics format for display on the DotPad. It integrates with
	the OfficeChartOverlay system for detecting and rendering Office charts.
	"""

	def __init__(
		self,
		chartObj: NVDAObject,
		display: Display,
	):
		"""Initialize a chart presentation.

		:param chartObj: The NVDA chart object to render (with officeChartObject attribute).
		:param display: The display to render to.
		"""
		super().__init__()
		self._chartObj = chartObj
		self._display = display
		self._chart: Chart | None = None

	def _ensureChart(self, display: Display) -> Chart | None:
		"""Ensure the Chart instance is created.

		Lazily creates the Chart instance from the officeChartObject.
		This follows the pattern from OfficeChartOverlay.dotMap().

		:param display: The display to use for dimensions.
		:returns: The Chart instance, or None if chart creation failed.
		"""
		if self._chart is not None:
			return self._chart

		# Get the native Office chart object
		officeChart = getattr(self._chartObj, "officeChartObject", None)
		if officeChart is None:
			return None

		try:
			# Import msOfficeChart for axis constants
			import NVDAObjects.window._msOfficeChart as msOfficeChart

			# Extract series data from the chart
			sr = officeChart.seriesCollection()
			datasets: dict[str, list[float | int]] = {}
			for index in range(1, sr.count + 1):
				series = sr.item(index)
				datasets[series.name] = list(series.values)

			# Get axis bounds and Excel axis object
			excelAxis = None
			if officeChart.HasAxis(msOfficeChart.xlValue):
				excelAxis = officeChart.axes(msOfficeChart.xlValue)

			# Calculate dimensions
			width = display.physicalNumCols * display.cellWidth
			height = display.physicalNumRows * display.cellHeight

			# Store officeChart reference for active bar detection
			self._officeChart = officeChart

			self._chart = BarChart(
				width,
				height,
				datasets=datasets,
				excelAxis=excelAxis,
				showHorizontalRuler=True,
				showVerticalRuler=True,
			)
		except Exception:
			# If chart creation fails, return None
			return None

		return self._chart

	def render(self, display: Display) -> DpTactileGraphicsBuffer:
		"""Render the chart to a tactile graphics buffer.

		:param display: The display to render to.
		:returns: A tactile graphics buffer containing the rendered chart.
		"""
		buffer = DpTactileGraphicsBuffer(display.physicalNumCols, display.physicalNumRows)
		chart = self._ensureChart(display)
		if chart is not None:
			chart = cast(BarChart, chart)
			# Detect active bar from navigator position
			navObj = api.getNavigatorObject()
			officeChart = getattr(self, "_officeChart", None)
			if officeChart is not None:
				activePos = getActiveBarIndex(navObj, officeChart)
				if activePos is not None:
					chart.activeSeriesIndex = activePos.seriesIndex
					chart.activeColIndex = activePos.pointIndex
				else:
					chart.activeSeriesIndex = None
					chart.activeColIndex = None

			chart.draw(buffer)
		return buffer

	def scrollForward(self) -> bool:
		"""Scroll the chart forward.

		:returns: True if scrolling occurred, False if at end or chart not available.
		"""
		if self._chart is None:
			return False
		scrollFunc = getattr(self._chart, "scrollForward", None)
		if scrollFunc is None:
			return False
		return scrollFunc()

	def scrollBack(self) -> bool:
		"""Scroll the chart back.

		:returns: True if scrolling occurred, False if at beginning or chart not available.
		"""
		if self._chart is None:
			return False
		scrollFunc = getattr(self._chart, "scrollBack", None)
		if scrollFunc is None:
			return False
		return scrollFunc()

	def isStillValid(self, triggerReason: TriggerReason | None = None) -> bool:
		"""Check if this presentation is still valid for current navigator position.

		A chart presentation is valid if the navigator is still on the same
		chart object.

		:returns: True if the presentation is still valid, False otherwise.
		"""
		navObj = api.getNavigatorObject()

		# Check if the navigator is still on the same chart object
		if navObj == self._chartObj:
			return True

		# Check if the navigator still has the same officeChartObject
		navChartObj = getattr(navObj, "officeChartObject", None)
		chartObjRef = getattr(self._chartObj, "officeChartObject", None)
		if navChartObj is not None and chartObjRef is not None:
			try:
				if navChartObj == chartObjRef:
					return True
			except Exception:
				pass

		# Fallback: bounds check
		chartLocation = getattr(self._chartObj, "location", None)
		navLocation = getattr(navObj, "location", None)

		if chartLocation and navLocation:
			# Check if navigator is within chart bounds
			return (
				chartLocation.left <= navLocation.left
				and chartLocation.top <= navLocation.top
				and chartLocation.right >= navLocation.right
				and chartLocation.bottom >= navLocation.bottom
			)

		return False

	@property
	def chartObj(self) -> NVDAObject | None:
		"""The chart NVDAObject this presentation is rendering."""
		return self._chartObj

	def terminate(self) -> None:
		"""Clean up resources held by this presentation.

		Clears references to NVDA objects and chart data.
		"""
		self._chartObj = None
		self._chart = None

	@property
	def name(self) -> str:
		return "chart"


class ChartProvider(PresentationProvider):
	"""Provider that creates chart presentations.

	This provider detects Office charts and creates ChartPresentation instances.
	It detects charts by checking for the officeChartObject attribute, which is
	present on objects with the OfficeChartOverlay applied.
	"""

	@property
	def name(self) -> str:
		return "chart"

	def canProvide(self, obj: NVDAObject) -> bool:
		"""Check if this provider can create a presentation for the object.

		An object can be provided for if it has the officeChartObject attribute,
		which indicates it's an Office chart with the OfficeChartOverlay applied.

		:param obj: The NVDA object to check.
		:returns: True if a presentation can be created, False otherwise.
		"""
		# Check if object has officeChartObject attribute (like OfficeChartOverlay)
		return hasattr(obj, "officeChartObject")

	def _doCreatePresentation(self, obj: NVDAObject, display: Display) -> ChartPresentation:
		"""Create a chart presentation for the object.

		:param obj: The NVDA object (must be a chart).
		:param display: The display to render to.
		:returns: A ChartPresentation instance.
		"""
		return ChartPresentation(obj, display)

	def forceForObject(
		self,
		obj: NVDAObject,
		display: Display,
	) -> ChartPresentation | None:
		"""Try to force a chart presentation for the given object.

		Charts don't support forcing via parent scanning - the user must be
		directly on a chart object for it to be detected.

		:param obj: The NVDA object to create a presentation for.
		:param display: The display to render to.
		:returns: None - charts don't support forcing.
		"""
		# Charts don't support forcing via parent scan
		return None
