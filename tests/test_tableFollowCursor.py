# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for how the table view follows the cursor out of the visible window.

Moving the cursor off the visible window asks ``drawTable`` to re-centre by
setting the viewport origin to None. Doing that for both axes at once meant
stepping down out of view also re-centred the columns, throwing the view back
to the left of the row; following the cursor down should move straight down,
the way panning a graphic does.
"""

import unittest
from unittest.mock import MagicMock, patch

import controlTypes

from addon.presentations.table import TablePresentation


def makePresentation(numVisibleRows=4, numVisibleCols=3, firstRow=0, firstCol=6):
	"""A table presentation with a viewport scrolled away from the origin."""
	tableObj = MagicMock()
	tableObj.role = controlTypes.Role.TABLE
	tableObj.name = "Test Table"
	# Not an Excel worksheet, so the plain Table model is used.
	del tableObj.excelWorksheetObject
	display = MagicMock()
	display.horizontalCellSpacing = 1
	display.verticalCellSpacing = 2
	display.physicalNumCols = 30
	display.physicalNumRows = 10
	presentation = TablePresentation(tableObj, display)

	tableData = presentation._tableData
	tableData.numVisibleRows = numVisibleRows
	tableData.numVisibleCols = numVisibleCols
	tableData.firstVisibleRow = firstRow
	tableData.firstVisibleCol = firstCol
	# A previous position, so the next render counts as a move.
	presentation._lastCellRow = 0
	presentation._lastCellCol = 6
	return presentation, display


def renderAtCell(presentation, display, row, col):
	"""Render with the cursor reported at a 1-based (row, col)."""
	with (
		patch.object(presentation, "_getRelevantObject", return_value=MagicMock()),
		patch.object(presentation, "_getCellPosition", return_value=(row, col)),
		patch.object(presentation._tableData, "draw"),
	):
		presentation.render(display)


class TestFollowingTheCursorPerAxis(unittest.TestCase):
	def test_stepping_below_the_window_leaves_the_columns_alone(self):
		"""The reported bug: scrolling down jumped back to the left of the row."""
		presentation, display = makePresentation()

		# Row 9 (0-based 8) is below the window; column 7 (0-based 6) is inside it.
		renderAtCell(presentation, display, row=9, col=7)

		tableData = presentation._tableData
		self.assertIsNone(tableData.firstVisibleRow, "the row axis should re-centre")
		self.assertEqual(tableData.firstVisibleCol, 6, "the column axis should not move")

	def test_stepping_right_of_the_window_leaves_the_rows_alone(self):
		presentation, display = makePresentation(firstRow=4)
		presentation._lastCellRow = 4

		# Column 20 (0-based 19) is right of the window; row 5 (0-based 4) is inside it.
		renderAtCell(presentation, display, row=5, col=20)

		tableData = presentation._tableData
		self.assertEqual(tableData.firstVisibleRow, 4, "the row axis should not move")
		self.assertIsNone(tableData.firstVisibleCol, "the column axis should re-centre")

	def test_leaving_the_window_diagonally_re_centres_both(self):
		presentation, display = makePresentation()

		renderAtCell(presentation, display, row=9, col=20)

		tableData = presentation._tableData
		self.assertIsNone(tableData.firstVisibleRow)
		self.assertIsNone(tableData.firstVisibleCol)

	def test_a_cursor_still_inside_the_window_moves_nothing(self):
		"""Manual scrolling must survive a cursor move that stays in view."""
		presentation, display = makePresentation()

		renderAtCell(presentation, display, row=2, col=8)

		tableData = presentation._tableData
		self.assertEqual(tableData.firstVisibleRow, 0)
		self.assertEqual(tableData.firstVisibleCol, 6)


if __name__ == "__main__":
	unittest.main()
