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


if __name__ == "__main__":
	unittest.main()
