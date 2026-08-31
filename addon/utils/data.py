# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2025 Dot Incorporated

"""
Data visualization classes for tactile graphics.

This module re-exports classes from table.py and chart.py for backwards
compatibility. New code should import directly from those modules.
"""

from .chart import BarChart, Chart, ScrollableChart
from .chartAxis import YAxisConfig, calculateYAxisConfig, getActiveBarIndex
from .drawing import (
	BRAILLE_CELL_SPACING,
	BRAILLE_CELL_WIDTH,
	drawBrailleCells,
	drawHorizontalRuler,
	drawLine,
	drawVerticalRuler,
	generateAZColumnLabel,
	generateYValueLabels,
	translateTextToBraille,
)
from .table import (
	TABLE_CELL_ROLES,
	TABLE_ROLES,
	ExcelTable,
	FakeNVDAObjectCell,
	Table,
)

__all__ = [
	# Chart
	"Chart",
	"ScrollableChart",
	"BarChart",
	"YAxisConfig",
	"calculateYAxisConfig",
	"getActiveBarIndex",
	# Table
	"Table",
	"ExcelTable",
	"FakeNVDAObjectCell",
	"TABLE_ROLES",
	"TABLE_CELL_ROLES",
	# Drawing
	"drawLine",
	"drawBrailleCells",
	"drawHorizontalRuler",
	"drawVerticalRuler",
	"translateTextToBraille",
	"generateAZColumnLabel",
	"generateYValueLabels",
	"BRAILLE_CELL_WIDTH",
	"BRAILLE_CELL_SPACING",
]
