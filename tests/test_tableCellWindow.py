# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the coordinate window that replaced walking rows.

The window fetch is what made a Google Sheets draw ~5x cheaper, but it is a
second source of cells alongside the row walk, and the two must agree about
what a window contains.
"""

import unittest
from unittest.mock import Mock, patch

# addon.presentations first: addon.utils.table's runtime loadModule pulls the
# driver back through presentations, so importing it first here deadlocks the
# cycle when this module is run on its own.
import addon.presentations  # noqa: F401
from addon.utils import table


def makeTable(rowCount=20, colCount=20):
	tableObj = Mock()
	tableObj.role = table.ROLE_TABLE
	tableObj.name = "Test Table"
	tableObj.rowCount = rowCount
	tableObj.columnCount = colCount
	instance = table.Table(tableObj, hCellPadding=1, vCellPadding=1)
	instance.tableCurrentRow = 0
	instance.tableCurrentCol = 0
	return instance


def makeCell(rowNumber, columnNumber):
	"""A cell carrying the 1-based coordinates NVDA reports."""
	cell = Mock()
	cell.rowNumber = rowNumber
	cell.columnNumber = columnNumber
	return cell


class TestARefusingTableFallsBackToTheRowWalk(unittest.TestCase):
	"""Exposing the interface is not the same as answering through it.

	An IAccessibleTable v1 implementation that refuses every ``accessibleAt``
	returned an empty list, and an empty list is a valid answer - so the caller
	drew a blank table instead of trying the row walk that would have worked.
	"""

	def test_every_lookup_raising_asks_for_the_row_walk(self):
		instance = makeTable()
		with patch.object(instance, "_getIA2CellAccessor", return_value=Mock(side_effect=RuntimeError)):
			self.assertIsNone(instance._getCellWindow(0, 0, maxCellsPerRow=6, maxRows=4))

	def test_every_lookup_returning_nothing_asks_for_the_row_walk(self):
		instance = makeTable()
		with patch.object(instance, "_getIA2CellAccessor", return_value=Mock(return_value=None)):
			self.assertIsNone(instance._getCellWindow(0, 0, maxCellsPerRow=6, maxRows=4))

	def test_an_empty_window_is_still_an_empty_window(self):
		"""A zero-width request has nothing to find, so it is not a failure."""
		instance = makeTable()
		with patch.object(instance, "_getIA2CellAccessor", return_value=Mock(side_effect=RuntimeError)):
			self.assertEqual(instance._getCellWindow(0, 0, maxCellsPerRow=0, maxRows=4), [])


class TestCellsSpanningInFromOutside(unittest.TestCase):
	"""A merged cell answers for coordinates it spans, wherever it starts.

	Asked for a window that a cell only reaches into, the accessor hands back
	that cell with its own out-of-window origin. drawTable positions a cell by
	subtracting the window's origin, so such a cell lands at a negative offset
	and paints a fragment of itself over the first visible row or column. The
	row walk never produced one.
	"""

	def _windowWith(self, cells):
		instance = makeTable()
		byCoord = {(c.rowNumber - 1, c.columnNumber - 1): c for c in cells}

		def accessor(rowIndex, colIndex):
			# A spanning cell answers for coordinates it covers, not just its own.
			for (originRow, originCol), cell in byCoord.items():
				if originRow <= rowIndex < originRow + 3 and originCol <= colIndex < originCol + 3:
					return cell
			return None

		with patch.object(instance, "_getIA2CellAccessor", return_value=accessor):
			with patch.object(instance, "_makeCellFromIA2", side_effect=lambda raw: raw):
				return instance._getCellWindow(5, 5, maxCellsPerRow=4, maxRows=4)

	def test_a_cell_starting_above_the_window_is_skipped(self):
		window = self._windowWith([makeCell(rowNumber=4, columnNumber=7)])

		self.assertIsNone(window, "a window holding only out-of-origin cells asks for the row walk")

	def _served(self, window):
		"""Only the cells the table itself served, not the blanks filling gaps."""
		assert window is not None
		return [(c.rowNumber, c.columnNumber) for c in window if not isinstance(c, table.FakeNVDAObjectCell)]

	def test_a_cell_starting_inside_the_window_is_kept(self):
		window = self._windowWith([makeCell(rowNumber=7, columnNumber=7)])

		self.assertIsNotNone(window)
		self.assertEqual(self._served(window), [(7, 7)])

	def test_only_the_out_of_origin_cell_is_dropped(self):
		window = self._windowWith(
			[makeCell(rowNumber=4, columnNumber=7), makeCell(rowNumber=8, columnNumber=8)],
		)

		self.assertEqual(self._served(window), [(8, 8)])


class TestARaggedTableStillDrawsAFullGrid(unittest.TestCase):
	"""Google Sheets' screen-reader view has a header row shorter than its data.

	A coordinate the table serves nothing for used to be skipped entirely, and
	drawing no cell there draws no border either - so the short row stopped
	partway across while every row beneath it ran the full width. A reader
	cannot tell a missing cell from an empty one; the inconsistent grid is what
	misleads.
	"""

	def _window(self, headerWidth):
		instance = makeTable()

		def accessor(rowIndex, colIndex):
			if rowIndex == 0 and colIndex >= headerWidth:
				raise RuntimeError("no such cell")
			return makeCell(rowNumber=rowIndex + 1, columnNumber=colIndex + 1)

		with patch.object(instance, "_getIA2CellAccessor", return_value=accessor):
			with patch.object(instance, "_makeCellFromIA2", side_effect=lambda raw: raw):
				return instance._getCellWindow(0, 0, maxCellsPerRow=4, maxRows=3)

	def test_every_visible_coordinate_gets_a_cell(self):
		window = self._window(headerWidth=2)

		assert window is not None
		self.assertEqual(len(window), 12, "4 columns x 3 rows, gaps included")

	def test_the_gaps_are_blank_and_in_the_right_places(self):
		window = self._window(headerWidth=2)

		assert window is not None
		blanks = [c for c in window if isinstance(c, table.FakeNVDAObjectCell)]
		self.assertEqual([(c.rowNumber, c.columnNumber) for c in blanks], [(1, 3), (1, 4)])
		self.assertEqual({c.name for c in blanks}, {""})

	def test_a_table_that_serves_every_cell_gains_no_blanks(self):
		window = self._window(headerWidth=4)

		assert window is not None
		self.assertEqual([c for c in window if isinstance(c, table.FakeNVDAObjectCell)], [])


if __name__ == "__main__":
	unittest.main()
