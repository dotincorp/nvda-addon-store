# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for how table cell text is obtained while drawing."""

import unittest
from unittest.mock import MagicMock, Mock, patch

from NVDAObjects import NVDAObject

# addon.presentations first: addon.utils.table's runtime loadModule pulls the
# driver back through presentations, so importing it first here deadlocks the
# cycle when this module is run on its own.
import addon.presentations  # noqa: F401
from addon.utils import table


class TestCellTextSource(unittest.TestCase):
	"""drawTable must not build a TextInfo for a cell whose name already has the text.

	Building one costs a cross-process call per cell on every render, and the
	result is discarded whenever ``cell.name`` is set.
	"""

	def setUp(self):
		self.mockTableObj = Mock()
		self.mockTableObj.role = table.ROLE_TABLE
		self.mockTableObj.name = "Test Table"
		self.tableInstance = table.Table(self.mockTableObj, hCellPadding=1, vCellPadding=1)
		# Table.__init__ copies these off the mock, where they are Mocks.
		self.tableInstance.tableCurrentRow = 0
		self.tableInstance.tableCurrentCol = 0
		self.buffer = MagicMock()
		self.buffer.height = 40
		self.buffer.width = 60

	def _makeCell(self, name: str) -> Mock:
		"""A cell that passes drawTable's ``isinstance(cell, NVDAObject)`` check."""
		cell = Mock(spec=NVDAObject)
		cell.rowNumber = 1
		cell.columnNumber = 1
		cell.name = name
		cell.columnSpan = 1
		cell.makeTextInfo.return_value = MagicMock(text="from text info")
		return cell

	def _drawWith(self, cell: Mock) -> None:
		with patch.object(self.tableInstance, "getTableCells", return_value=[cell]):
			with patch.object(self.tableInstance, "drawCell"):
				self.tableInstance.drawTable(self.buffer, 0, 0)

	def test_named_cell_does_not_build_a_text_info(self):
		cell = self._makeCell("ab")

		self._drawWith(cell)

		cell.makeTextInfo.assert_not_called()

	def test_unnamed_cell_falls_back_to_the_text_info(self):
		cell = self._makeCell("")

		with patch.object(self.tableInstance, "getTableCells", return_value=[cell]):
			with patch.object(self.tableInstance, "drawCell") as mockDrawCell:
				self.tableInstance.drawTable(self.buffer, 0, 0)

		cell.makeTextInfo.assert_called_once()
		drawnText = mockDrawCell.call_args.args[3]
		self.assertEqual(drawnText, "from text info")


class TestDrawStats(unittest.TestCase):
	"""The draw records what it cost, for the debug line a slow-table report needs."""

	def setUp(self):
		self.mockTableObj = Mock()
		self.mockTableObj.role = table.ROLE_TABLE
		self.mockTableObj.name = "Test Table"
		# These tests are about the row-walking path; a bare Mock would otherwise
		# answer for the cell-window interfaces and take the other one.
		self.mockTableObj.IAccessibleTable2Object = None
		self.mockTableObj.IAccessibleTableObject = None
		self.tableInstance = table.Table(self.mockTableObj, hCellPadding=1, vCellPadding=1)
		self.tableInstance.tableCurrentRow = 0
		self.tableInstance.tableCurrentCol = 0
		self.buffer = MagicMock()
		self.buffer.height = 40
		self.buffer.width = 60

	def _makeCell(self, row: int, col: int) -> Mock:
		cell = Mock(spec=NVDAObject)
		cell.rowNumber = row
		cell.columnNumber = col
		cell.name = "ab"
		cell.columnSpan = 1
		return cell

	def test_cells_drawn_is_counted(self):
		cells = [self._makeCell(1, 1), self._makeCell(1, 2), self._makeCell(2, 1)]

		with patch.object(self.tableInstance, "getTableCells", return_value=cells):
			with patch.object(self.tableInstance, "drawCell"):
				self.tableInstance.drawTable(self.buffer, 0, 0)

		self.assertEqual(self.tableInstance.lastDrawStats.cellsDrawn, 3)
		self.assertGreater(self.tableInstance.lastDrawStats.totalSeconds, 0)

	def test_stats_reset_between_draws(self):
		cells = [self._makeCell(1, 1)]

		with patch.object(self.tableInstance, "getTableCells", return_value=cells):
			with patch.object(self.tableInstance, "drawCell"):
				self.tableInstance.drawTable(self.buffer, 0, 0)
				self.tableInstance.drawTable(self.buffer, 0, 0)

		self.assertEqual(self.tableInstance.lastDrawStats.cellsDrawn, 1)

	def test_rows_materialised_counts_every_row_object_built(self):
		"""The count must reflect the whole child walk, not the rows drawn.

		This is the number that says whether a slow table is slow because NVDA
		built an object for every row in the document to draw the few that fit.
		"""
		rows = []
		for rowNumber in range(1, 51):
			row = Mock()
			row.role = table.ROLE_TABLEROW
			row.children = [self._makeCell(rowNumber, 1)]
			rows.append(row)
		self.mockTableObj.children = rows

		with patch.object(self.tableInstance, "drawCell"):
			self.tableInstance.drawTable(self.buffer, 0, 0)

		self.assertEqual(self.tableInstance.lastDrawStats.rowsMaterialised, 50)
		self.assertLess(self.tableInstance.lastDrawStats.cellsDrawn, 50)


class TestCellWindowFetch(unittest.TestCase):
	"""Only the cells that will be drawn should be fetched.

	Walking rows asks for row.children, which NVDA builds eagerly, so the full
	width of every row is turned into NVDAObjects however few columns fit on the
	display. Measured at ~11ms per cell object in Google Sheets, which is where a
	1.7s draw of a 25-column table came from.
	"""

	def setUp(self):
		self.mockTableObj = Mock()
		self.mockTableObj.role = table.ROLE_TABLE
		self.mockTableObj.name = "Test Table"
		self.mockTableObj.rowCount = 15
		self.mockTableObj.columnCount = 25
		self.tableInstance = table.Table(self.mockTableObj, hCellPadding=1, vCellPadding=1)
		self.fetched: list[tuple[int, int]] = []

	def _installIA2Table(self, spans: dict | None = None) -> None:
		"""Give the table an IAccessibleTable2 whose cellAt records its lookups.

		``spans`` maps a requested coordinate to the coordinate of the cell that
		actually covers it, standing in for a merged cell.
		"""
		spans = spans or {}

		def cellAt(rowIndex, colIndex):
			self.fetched.append((rowIndex, colIndex))
			return (rowIndex, colIndex)

		ia2Table = Mock()
		ia2Table.cellAt.side_effect = cellAt
		self.mockTableObj.IAccessibleTable2Object = ia2Table

		def makeCell(raw):
			rowIndex, colIndex = spans.get(raw, raw)
			cell = Mock(spec=NVDAObject)
			cell.rowNumber = rowIndex + 1
			cell.columnNumber = colIndex + 1
			cell.name = "ab"
			cell.columnSpan = 1
			return cell

		self.tableInstance._makeCellFromIA2 = makeCell

	def test_only_the_visible_window_is_fetched(self):
		self._installIA2Table()

		cells = list(self.tableInstance.getTableCells(0, 0, maxCellsPerRow=6, maxRows=5))

		self.assertEqual(len(cells), 30)
		self.assertEqual(len(self.fetched), 30)
		self.assertEqual(max(col for _row, col in self.fetched), 5)
		self.assertEqual(max(row for row, _col in self.fetched), 4)

	def test_the_window_is_offset_by_the_scroll_position(self):
		self._installIA2Table()

		list(self.tableInstance.getTableCells(10, 5, maxCellsPerRow=6, maxRows=5))

		self.assertEqual(min(self.fetched), (5, 10))
		self.assertEqual(max(self.fetched), (9, 15))

	def test_the_window_is_clamped_to_the_table(self):
		"""A window running off the end must not ask for coordinates that do not exist."""
		self._installIA2Table()

		list(self.tableInstance.getTableCells(22, 13, maxCellsPerRow=6, maxRows=5))

		self.assertEqual(max(row for row, _col in self.fetched), 14)
		self.assertEqual(max(col for _row, col in self.fetched), 24)

	def test_a_merged_cell_is_yielded_once(self):
		"""cellAt answers for every coordinate a merged cell spans."""
		self._installIA2Table(spans={(0, 1): (0, 0), (1, 0): (0, 0), (1, 1): (0, 0)})

		cells = list(self.tableInstance.getTableCells(0, 0, maxCellsPerRow=2, maxRows=2))

		self.assertEqual(len(cells), 1)

	def test_a_failing_cell_does_not_lose_the_draw(self):
		self._installIA2Table()
		self.mockTableObj.IAccessibleTable2Object.cellAt.side_effect = lambda rowIndex, colIndex: (
			(_ for _ in ()).throw(RuntimeError("hidden"))
			if (rowIndex, colIndex) == (0, 0)
			else (rowIndex, colIndex)
		)

		cells = list(self.tableInstance.getTableCells(0, 0, maxCellsPerRow=3, maxRows=2))

		# Six: the five the table served, plus a blank standing in for the one
		# it refused, so the row does not stop short of the others.
		self.assertEqual(len(cells), 6)
		self.assertEqual(
			sorted((c.rowNumber, c.columnNumber) for c in cells),
			[(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)],
			"every visible coordinate should be covered exactly once",
		)

	def test_a_table_without_the_interface_still_walks_rows(self):
		# A bare Mock answers every attribute, so the interfaces have to be
		# denied explicitly or the window fetch is taken for a table that has no
		# such interface at all.
		self.mockTableObj.IAccessibleTable2Object = None
		self.mockTableObj.IAccessibleTableObject = None
		rows = []
		for rowNumber in range(1, 4):
			cell = Mock(spec=NVDAObject)
			cell.rowNumber = rowNumber
			cell.columnNumber = 1
			cell.name = "ab"
			cell.columnSpan = 1
			row = Mock()
			row.role = table.ROLE_TABLEROW
			row.children = [cell]
			rows.append(row)
		self.mockTableObj.children = rows

		cells = list(self.tableInstance.getTableCells(0, 0, maxCellsPerRow=6, maxRows=5))

		self.assertEqual(len(cells), 3)


if __name__ == "__main__":
	unittest.main()
