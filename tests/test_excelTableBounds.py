# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the extent ExcelTable reports for a worksheet."""

import unittest
from unittest import mock
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
	# NVDA's ExcelWorksheet defines neither, so reading them raises - which is
	# what made drawTable's clamp skip itself on exactly this table type.
	del tableObj.rowCount
	del tableObj.columnCount
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


class TestCentringUsesTheUsedRange(unittest.TestCase):
	"""The clamp that keeps the last screenful full read the wrong extent.

	It asked ``tableObj.rowCount`` rather than the subclass property, and NVDA's
	ExcelWorksheet exposes no ``rowCount`` at all - so on the one table type
	where the used range matters, the clamp was skipped entirely and centring
	could run off the end of the data.
	"""

	def test_centring_near_the_last_row_clamps_to_the_data(self):
		instance = makeExcelTable(makeWorksheet(firstRow=1, rowCount=29, firstCol=1, colCount=25))
		instance.tableCurrentRow = 28
		instance.tableCurrentCol = 0
		buffer = Mock()
		buffer.height = 40
		buffer.width = 60
		with mock.patch.object(instance, "getTableCells", return_value=[]):
			instance.drawTable(buffer, 0, 0)

		visibleRows = instance.numVisibleRows
		assert visibleRows is not None
		self.assertEqual(instance.firstVisibleRow, 29 - visibleRows)


class TestARefusalIsNotCached(unittest.TestCase):
	"""Excel refuses COM calls freely while it is busy, and it recovers.

	Caching the refusal pinned the extent at unknown for the life of the
	presentation - which the reuse shortcut keeps alive for the whole worksheet
	visit - and an unknown extent disables every forward scroll. One transient
	refusal would have made the sheet unscrollable until the user left it.
	"""

	def test_a_failed_read_is_retried(self):
		worksheet = makeWorksheet(firstRow=1, rowCount=29, firstCol=1, colCount=25)
		good = worksheet.UsedRange
		type(worksheet).UsedRange = PropertyMock(side_effect=[RuntimeError("busy"), good, good])
		instance = makeExcelTable(worksheet)

		self.assertIsNone(instance.tableRowCount)

		self.assertEqual(instance.tableRowCount, 29)

	def test_the_retry_result_is_then_cached(self):
		worksheet = makeWorksheet(firstRow=1, rowCount=29, firstCol=1, colCount=25)
		good = worksheet.UsedRange
		usedRangeProperty = PropertyMock(side_effect=[RuntimeError("busy"), good])
		type(worksheet).UsedRange = usedRangeProperty
		instance = makeExcelTable(worksheet)

		instance.tableRowCount
		instance.tableRowCount
		instance.tableColumnCount

		self.assertEqual(usedRangeProperty.call_count, 2)


class TestScrollingWithAnUnknownExtent(unittest.TestCase):
	"""Reachable whenever the used range cannot be read - it must not raise."""

	def _instance(self):
		worksheet = Mock()
		type(worksheet).UsedRange = PropertyMock(side_effect=RuntimeError("busy"))
		instance = makeExcelTable(worksheet)
		instance.numVisibleRows = 4
		instance.numVisibleCols = 6
		instance.firstVisibleRow = 0
		instance.firstVisibleCol = 0
		return instance

	def test_scroll_forward_does_not_raise(self):
		"""It compared against the count without a None guard, unlike scrollRight."""
		self.assertFalse(self._instance().scrollForward())

	def test_the_plain_steps_do_not_raise_either(self):
		instance = self._instance()

		self.assertFalse(instance.scrollRight())
		self.assertFalse(instance.scrollDown())
		self.assertFalse(instance.scrollByCols(1))


if __name__ == "__main__":
	unittest.main()
