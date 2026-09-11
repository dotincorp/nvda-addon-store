# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the table viewport steps that the table-mode gestures drive."""

import unittest
from unittest import mock
from unittest.mock import Mock

# addon.presentations first: addon.utils.table's runtime loadModule pulls the
# driver back through presentations, so importing it first here deadlocks the
# cycle when this module is run on its own.
import addon.presentations  # noqa: F401
from addon.utils import table


def makeTable(rowCount, colCount, visibleRows=4, visibleCols=6):
	"""A drawn table with a known extent and viewport size."""
	tableObj = Mock()
	tableObj.role = table.ROLE_TABLE
	tableObj.name = "Test Table"
	tableObj.rowCount = rowCount
	tableObj.columnCount = colCount
	instance = table.Table(tableObj, hCellPadding=1, vCellPadding=1)
	instance.tableCurrentRow = 0
	instance.tableCurrentCol = 0
	# drawTable normally sets these; the scroll steps refuse to run without them.
	instance.numVisibleRows = visibleRows
	instance.numVisibleCols = visibleCols
	instance.firstVisibleRow = 0
	instance.firstVisibleCol = 0
	return instance


class TestTheLastRowAndColumnFitOnTheDisplay(unittest.TestCase):
	"""Adjacent cells share a border, so N cells need N * size + 1 dots.

	Sizing the viewport with a plain floor division claimed one row and one
	column too many, and the bottom cell border of the last row fell one dot
	outside the buffer and was clipped away.
	"""

	def _drawInto(self, height, width):
		instance = makeTable(rowCount=50, colCount=50)
		buffer = Mock()
		buffer.height = height
		buffer.width = width
		with mock.patch.object(instance, "getTableCells", return_value=[]):
			instance.drawTable(buffer, 0, 0)
		return instance

	def test_an_exact_multiple_leaves_room_for_the_final_border(self):
		instance = makeTable(rowCount=50, colCount=50)
		cellHeight = instance.tableCellHeight
		drawn = self._drawInto(height=cellHeight * 4, width=1000)

		self.assertEqual(drawn.numVisibleRows, 3)

	def test_the_bottom_border_lands_inside_the_buffer(self):
		instance = makeTable(rowCount=50, colCount=50)
		cellHeight = instance.tableCellHeight
		height = cellHeight * 4
		drawn = self._drawInto(height=height, width=1000)

		rows = drawn.numVisibleRows
		assert rows is not None
		lastDrawnDotRow = rows * cellHeight
		self.assertLess(lastDrawnDotRow, height, "the last bottom border must fit")

	def test_one_dot_of_slack_buys_the_row_back(self):
		instance = makeTable(rowCount=50, colCount=50)
		cellHeight = instance.tableCellHeight
		drawn = self._drawInto(height=cellHeight * 4 + 1, width=1000)

		self.assertEqual(drawn.numVisibleRows, 4)

	def test_columns_are_sized_the_same_way(self):
		"""The right border sits at leftX + cellWidth, exactly as the bottom does."""
		instance = makeTable(rowCount=50, colCount=50)
		cellWidth = instance.tableCellWidth
		drawn = self._drawInto(height=1000, width=cellWidth * 5)

		self.assertEqual(drawn.numVisibleCols, 4)


class TestAStepNeverMovesBackwards(unittest.TestCase):
	"""A page step can leave the view past the last full page.

	scrollRight/scrollDown land on a partial trailing page, so the view can sit
	beyond the clamp the single steps use. Clamping to it there would turn a
	press of "right one column" into a jump several columns left.
	"""

	def _pastTheLastFullPage(self):
		instance = makeTable(rowCount=13, colCount=10, visibleRows=4, visibleCols=3)
		instance.firstVisibleCol = 6
		instance.firstVisibleRow = 8
		self.assertTrue(instance.scrollRight(), "setup: expected a partial trailing page")
		self.assertTrue(instance.scrollDown(), "setup: expected a partial trailing page")
		self.assertEqual((instance.firstVisibleRow, instance.firstVisibleCol), (12, 9))
		return instance

	def test_stepping_right_at_a_partial_last_page_refuses(self):
		instance = self._pastTheLastFullPage()

		self.assertFalse(instance.scrollByCols(1))

		self.assertEqual(instance.firstVisibleCol, 9)

	def test_stepping_down_at_a_partial_last_page_refuses(self):
		instance = self._pastTheLastFullPage()

		self.assertFalse(instance.scrollByRows(1))

		self.assertEqual(instance.firstVisibleRow, 12)

	def test_stepping_back_from_there_still_works(self):
		instance = self._pastTheLastFullPage()

		self.assertTrue(instance.scrollByCols(-1))

		self.assertEqual(instance.firstVisibleCol, 8)

	def test_the_edge_jump_still_lands_on_the_last_full_page(self):
		"""Pulling back to a full display is what the jump is for."""
		instance = self._pastTheLastFullPage()

		self.assertTrue(instance.scrollToLastCol())

		self.assertEqual(instance.firstVisibleCol, 7)


class TestSingleStepStepping(unittest.TestCase):
	"""One row or column at a time — what the chorded gestures move by."""

	def test_stepping_down_moves_one_row(self):
		instance = makeTable(rowCount=50, colCount=10)

		self.assertTrue(instance.scrollByRows(1))

		self.assertEqual(instance.firstVisibleRow, 1)

	def test_stepping_up_moves_one_row(self):
		instance = makeTable(rowCount=50, colCount=10)
		instance.firstVisibleRow = 5

		self.assertTrue(instance.scrollByRows(-1))

		self.assertEqual(instance.firstVisibleRow, 4)

	def test_stepping_right_moves_one_column(self):
		instance = makeTable(rowCount=50, colCount=10)

		self.assertTrue(instance.scrollByCols(1))

		self.assertEqual(instance.firstVisibleCol, 1)

	def test_stepping_up_at_the_top_does_not_move(self):
		instance = makeTable(rowCount=50, colCount=10)

		self.assertFalse(instance.scrollByRows(-1))

		self.assertEqual(instance.firstVisibleRow, 0)

	def test_stepping_down_stops_where_the_display_is_still_full(self):
		"""50 rows, 4 visible: row 46 is the last start that fills the display."""
		instance = makeTable(rowCount=50, colCount=10)
		instance.firstVisibleRow = 46

		self.assertFalse(instance.scrollByRows(1))

		self.assertEqual(instance.firstVisibleRow, 46)

	def test_a_step_past_the_end_is_clamped_rather_than_refused(self):
		instance = makeTable(rowCount=50, colCount=10)
		instance.firstVisibleRow = 44

		self.assertTrue(instance.scrollByRows(10))

		self.assertEqual(instance.firstVisibleRow, 46)

	def test_stepping_is_refused_before_the_table_is_drawn(self):
		instance = makeTable(rowCount=50, colCount=10)
		instance.numVisibleRows = None

		self.assertFalse(instance.scrollByRows(1))


class TestSteppingWithAnUnknownExtent(unittest.TestCase):
	"""A table that does not report its size cannot have its far edge clamped."""

	def test_forward_stepping_is_refused(self):
		instance = makeTable(rowCount=None, colCount=None)

		self.assertFalse(instance.scrollByRows(1))
		self.assertFalse(instance.scrollByCols(1))

	def test_backward_stepping_still_works(self):
		instance = makeTable(rowCount=None, colCount=None)
		instance.firstVisibleRow = 5

		self.assertTrue(instance.scrollByRows(-1))

		self.assertEqual(instance.firstVisibleRow, 4)

	def test_the_page_steps_do_not_raise(self):
		"""scrollRight/scrollDown compared an int against None and raised TypeError."""
		instance = makeTable(rowCount=None, colCount=None)

		self.assertFalse(instance.scrollRight())
		self.assertFalse(instance.scrollDown())


class TestEdgeJumps(unittest.TestCase):
	"""Long-press jumps land on a full screenful, not on the last row."""

	def test_jump_to_last_row_keeps_the_display_full(self):
		instance = makeTable(rowCount=50, colCount=10)

		self.assertTrue(instance.scrollToLastRow())

		self.assertEqual(instance.firstVisibleRow, 46)

	def test_jump_to_last_column_keeps_the_display_full(self):
		instance = makeTable(rowCount=50, colCount=10)

		self.assertTrue(instance.scrollToLastCol())

		self.assertEqual(instance.firstVisibleCol, 4)

	def test_jump_to_first_row(self):
		instance = makeTable(rowCount=50, colCount=10)
		instance.firstVisibleRow = 20

		self.assertTrue(instance.scrollToFirstRow())

		self.assertEqual(instance.firstVisibleRow, 0)

	def test_jump_to_first_column(self):
		instance = makeTable(rowCount=50, colCount=10)
		instance.firstVisibleCol = 4

		self.assertTrue(instance.scrollToFirstCol())

		self.assertEqual(instance.firstVisibleCol, 0)

	def test_a_table_shorter_than_the_display_stays_at_the_top(self):
		instance = makeTable(rowCount=2, colCount=3)

		self.assertFalse(instance.scrollToLastRow())

		self.assertEqual(instance.firstVisibleRow, 0)

	def test_jumping_where_we_already_are_reports_no_movement(self):
		instance = makeTable(rowCount=50, colCount=10)

		self.assertFalse(instance.scrollToFirstRow())

	def test_jump_to_the_end_is_refused_when_the_extent_is_unknown(self):
		instance = makeTable(rowCount=None, colCount=None)

		self.assertFalse(instance.scrollToLastRow())
		self.assertFalse(instance.scrollToLastCol())


if __name__ == "__main__":
	unittest.main()
