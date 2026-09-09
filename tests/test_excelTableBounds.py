# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the extent ExcelTable reports for a worksheet."""

import unittest
from unittest.mock import Mock, PropertyMock

# addon.presentations first: addon.utils.table's runtime loadModule pulls the
# driver back through presentations, so importing it first here deadlocks the
# cycle when this module is run on its own.
import addon.presentations  # noqa: F401
from addon.utils import table


def makeWorksheet(firstRow, rowCount, firstCol, colCount):
	"""A worksheet whose UsedRange covers the given block."""
	usedRange = Mock()
	usedRange.Row = firstRow
	usedRange.Rows.Count = rowCount
	usedRange.Column = firstCol
	usedRange.Columns.Count = colCount
	worksheet = Mock()
	worksheet.UsedRange = usedRange
	# The whole-sheet bounds, which are what we must NOT report.
	worksheet.rows.count = 1048576
	worksheet.columns.count = 16384
	return worksheet


def makeExcelTable(worksheet):
	tableObj = Mock()
	tableObj.role = table.ROLE_TABLE
	tableObj.name = "Sheet1"
	tableObj.excelWorksheetObject = worksheet
	return table.ExcelTable(tableObj, hCellPadding=1, vCellPadding=1)


class TestExcelBounds(unittest.TestCase):
	"""The extent must be the data, not the worksheet's 1,048,576 x 16,384.

	Otherwise a jump to the last row lands a million rows into empty space, and
	paging walks through all of it.
	"""

	def test_bounds_come_from_the_used_range(self):
		instance = makeExcelTable(makeWorksheet(firstRow=1, rowCount=29, firstCol=1, colCount=25))

		self.assertEqual(instance.tableRowCount, 29)
		self.assertEqual(instance.tableColumnCount, 25)

	def test_a_used_range_not_starting_at_A1_still_bounds_the_last_row(self):
		"""Data in C5:H20 ends at row 20 and column 8, not at row 16 or column 6."""
		instance = makeExcelTable(makeWorksheet(firstRow=5, rowCount=16, firstCol=3, colCount=6))

		self.assertEqual(instance.tableRowCount, 20)
		self.assertEqual(instance.tableColumnCount, 8)

	def test_the_bounds_are_read_once(self):
		"""Each read is a COM round trip, and drawTable and the scroll steps ask repeatedly."""
		worksheet = makeWorksheet(firstRow=1, rowCount=29, firstCol=1, colCount=25)
		usedRangeProperty = PropertyMock(return_value=worksheet.UsedRange)
		type(worksheet).UsedRange = usedRangeProperty
		instance = makeExcelTable(worksheet)

		instance.tableRowCount
		instance.tableRowCount
		instance.tableColumnCount

		self.assertEqual(usedRangeProperty.call_count, 1)

	def test_a_worksheet_that_refuses_falls_back_to_no_extent(self):
		"""Excel raises COMError freely while busy; an unknown extent is handled."""
		worksheet = Mock()
		type(worksheet).UsedRange = PropertyMock(side_effect=RuntimeError("busy"))
		instance = makeExcelTable(worksheet)

		self.assertIsNone(instance.tableRowCount)
		self.assertIsNone(instance.tableColumnCount)


if __name__ == "__main__":
	unittest.main()
