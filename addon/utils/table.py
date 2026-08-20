# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

"""
Table classes for tactile graphics display.

Provides Table and ExcelTable classes for rendering table content to
DpTactileGraphicsBuffer.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import api
import core
import eventHandler
import textInfos
from baseObject import AutoPropertyObject
from controlTypes import (
	ROLE_DATAGRID,
	ROLE_DATAITEM,
	ROLE_GROUPING,
	ROLE_TABLE,
	ROLE_TABLECELL,
	ROLE_TABLECOLUMNHEADER,
	ROLE_TABLEROW,
	ROLE_TABLEROWHEADER,
	Role,
)
from logHandler import log
from NVDAObjects import NVDAObject
from tactile.braille import drawBrailleCells as drawBrailleCellsOnTactileBuffer

if TYPE_CHECKING:
	from .. import configuration
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from .drawing import BRAILLE_CELL_SPACING, BRAILLE_CELL_WIDTH, drawLine, translateTextToBraille

# Runtime imports using NVDA's addon module loading
if not TYPE_CHECKING:
	import addonHandler

	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	configuration = addon.loadModule("configuration")
	DpTactileGraphicsBuffer = addon.loadModule(
		"brailleDisplayDrivers.dotPad.tactileBuffer",
	).DpTactileGraphicsBuffer
	drawing_module = addon.loadModule("utils.drawing")
	BRAILLE_CELL_WIDTH = drawing_module.BRAILLE_CELL_WIDTH
	BRAILLE_CELL_SPACING = drawing_module.BRAILLE_CELL_SPACING
	drawLine = drawing_module.drawLine
	translateTextToBraille = drawing_module.translateTextToBraille


TABLE_ROLES: list[Role] = [
	ROLE_TABLE,
	ROLE_DATAGRID,
]
TABLE_CELL_ROLES: list[Role] = [ROLE_DATAITEM, ROLE_TABLECELL, ROLE_TABLECOLUMNHEADER, ROLE_TABLEROWHEADER]

# Characters to filter from cell text - these are invisible or placeholder characters
# that don't render meaningfully in braille. Add to this set as needed.
CELL_TEXT_FILTER_CHARS: set[str] = {
	"\ufffc",  # Object Replacement Character (used by Google Docs for empty cells)
}


def _filterCellText(text: str) -> str:
	"""Filter invisible/placeholder characters from cell text.

	:param text: Raw cell text.
	:returns: Text with filtered characters replaced by spaces.
	"""
	for char in CELL_TEXT_FILTER_CHARS:
		text = text.replace(char, " ")
	return text


def findAncestorWithRole(
	obj: NVDAObject,
	roles: Iterable[Role],
	maxDepth: int = 10,
	includeSelf: bool = True,
) -> NVDAObject | None:
	"""Find an ancestor with one of the specified roles.

	Scans up the parent chain to find an object matching one of the given roles.
	This is useful for finding containing tables, cells, or other structural elements.

	:param obj: The starting NVDA object.
	:param roles: Roles to match against.
	:param maxDepth: Maximum number of parent levels to scan.
	:param includeSelf: If True, check obj itself before scanning parents.
	:returns: The matching NVDAObject if found, None otherwise.
	"""
	roleSet = set(roles)
	current = obj if includeSelf else obj.parent
	for _ in range(maxDepth):
		if current is None:
			break
		if current.role in roleSet:
			return current
		current = current.parent
	return None


@dataclass
class FakeNVDAObjectCell(ABC):
	rowNumber: int
	columnNumber: int
	name: str
	columnSpan: int = 1
	children: Iterable[NVDAObject] = ()
	sourceObject: Any = None  # For Excel: stores the COM cell object for later resolution


FakeNVDAObjectCell.register(NVDAObject)


class Table(AutoPropertyObject):
	tableCellHeight: int
	"Height of each table cell (including border) in dots."
	tableCellWidth: int
	"Width of each table cell (including border) in dots."
	maxCharsPerCell = 2
	"Maximum number of braille characters per cell."
	tableCellBorder: int = 1
	"Width of the border around each table cell in dots."
	tableColumnCount: int | None
	tableRowCount: int | None

	def _get_tableCellWidth(self) -> int:
		"""
		Returns the width of each table cell (including border) in dots.
		"""
		return self._calculateCellWidth(self.tableCellBorder, self.maxCharsPerCell)

	def _calculateCellWidth(self, border: int, textLength: int) -> int:
		"""
		Calculates the width of each table cell (including border) in dots.

		Args:
			border: The width of the border around each table cell in dots.
			textLength: The length of the text in the cell (in number of braille cells).

		Returns:
			int: The width of each table cell in dots.
		"""
		return (BRAILLE_CELL_WIDTH + BRAILLE_CELL_SPACING) * textLength + border * 2 + self.hCellPadding

	def _get_tableCellHeight(self) -> int:
		return self._calculateCellHeight(self.tableCellBorder)

	def _calculateCellHeight(self, border: int) -> int:
		"""
		Returns the height of each table cell (including border) in dots.

		Args:
			border: The width of the border around each table cell in dots.

		Returns:
			int: The height of each table cell in dots.
		"""
		# 4 dots for a line of braille, vCellPadding below, 1 dot above that and the border
		return 5 + self.vCellpadding + border * 2

	def __init__(
		self,
		obj: NVDAObject,
		hCellPadding: int = 1,
		vCellPadding: int = 1,
		firstVisibleRow: int | None = None,
		firstVisibleCol: int | None = None,
	):
		super().__init__()
		self.tableCurrentRow: int | None = None
		self.tableCurrentCol: int | None = None
		self.firstVisibleRow = firstVisibleRow
		self.firstVisibleCol = firstVisibleCol
		self.numVisibleCols: int | None = None
		self.numVisibleRows: int | None = None

		if obj.role in TABLE_ROLES:
			self.tableObj = obj
			if hasattr(obj, "_currentRow") and hasattr(obj, "_currentCol"):
				self.tableCurrentRow = cast(int, obj._currentRow)  # type: ignore
				self.tableCurrentCol = cast(int, obj._currentCol)  # type: ignore
		else:
			raise ValueError(f"table must be an NVDA object with a table role, got {obj.role}")

		self.tableCaption = self.tableObj.name or obj.description
		self.hCellPadding = hCellPadding
		self.vCellpadding = vCellPadding

	def getTableCells(
		self,
		startAtCol: int = 0,
		startAtRow: int = 0,
		maxCellsPerRow: int = 20,
		maxRows: int | None = None,
	) -> Iterator[FakeNVDAObjectCell]:
		rows: list[NVDAObject] = []
		for c in self.tableObj.children:
			if c.role == ROLE_TABLEROW:
				rows.append(c)
			elif c.role == ROLE_GROUPING:
				for gc in c.children:
					if gc.role == ROLE_TABLEROW:
						rows.append(gc)

		endCol = startAtCol + maxCellsPerRow
		endRow = startAtRow + maxRows if maxRows is not None else None
		foundRows = False

		# Skip rows before startAtRow (rows are in logical order)
		for row in rows[startAtRow:]:
			cellsYielded = 0
			for cell in row.children:
				try:
					colNum = cell.columnNumber - 1  # type: ignore
					cellRowNum = cell.rowNumber - 1  # type: ignore
				except (AttributeError, NotImplementedError):
					continue
				# Skip cells before target column range
				if colNum < startAtCol:
					continue
				# Stop iterating this row if past target column range
				if colNum >= endCol:
					break
				# Stop entirely if past target row range
				if endRow is not None and cellRowNum >= endRow:
					return
				yield cast(FakeNVDAObjectCell, cell)
				foundRows = True
				cellsYielded += 1
				if cellsYielded >= maxCellsPerRow:
					break

		# Handle datagrids and Word UIA tables, which contain only cells directly
		# Skip this path if we already found rows with the row-based iteration
		if foundRows:
			return

		cellsPerRow: dict[int, int] = {}
		for cell in self.tableObj.children:
			if cell.role in TABLE_CELL_ROLES:
				try:
					colNum = cell.columnNumber - 1  # type: ignore
					rowNum = cell.rowNumber - 1  # type: ignore
				except (AttributeError, NotImplementedError):
					continue
				# Skip cells outside target range
				if colNum < startAtCol or colNum >= endCol or rowNum < startAtRow:
					continue
				# Stop if past target row range
				if endRow is not None and rowNum >= endRow:
					continue
				# Limit cells yielded per row
				if cellsPerRow.get(rowNum, 0) >= maxCellsPerRow:
					continue
				yield cast(FakeNVDAObjectCell, cell)
				cellsPerRow[rowNum] = cellsPerRow.get(rowNum, 0) + 1

	tableCells: Iterator[FakeNVDAObjectCell]

	def _get_tableCells(self) -> Iterator[FakeNVDAObjectCell]:
		return self.getTableCells(self.firstVisibleCol, self.firstVisibleRow)  # type: ignore

	def _get_tableColumnCount(self) -> int | None:
		colCount: int | None = None

		try:
			colCount = cast(int, self.tableObj.columnCount)  # type: ignore
		except (NotImplementedError, AttributeError):
			pass

		return colCount

	def _get_tableRowCount(self) -> int | None:
		rowCount: int | None = None
		try:
			rowCount = cast(int, self.tableObj.rowCount)  # type: ignore
		except (NotImplementedError, AttributeError):
			pass

		return rowCount

	def drawTable(
		self,
		buffer: DpTactileGraphicsBuffer,
		x: int,
		y: int,
		height: int | None = None,
		width: int | None = None,
		firstRow: int | None = None,
		firstCol: int | None = None,
	):
		if height is None:
			height = buffer.height
		if width is None:
			width = buffer.width

		self.numVisibleRows = numVisibleRows = height // self.tableCellHeight
		self.numVisibleCols = numVisibleCols = width // self.tableCellWidth

		if firstRow is None:
			firstRow = 0

			log.debug(
				f"First row before centering: {firstRow}, numVisibleRows: {numVisibleRows}, tableCurrentRow: {self.tableCurrentRow}",
			)
			if self.tableCurrentRow and self.tableCurrentRow not in range(
				firstRow,
				firstRow + numVisibleRows,
			):
				# Center the current row
				log.debug(f"Centering current row {self.tableCurrentRow} in visible rows {numVisibleRows}")
				firstRow = self.tableCurrentRow - (numVisibleRows // 2)
				log.debug(f"First row after centering: {firstRow}")

				rowCount: int | None = None

				try:
					rowCount = cast(int, self.tableObj.rowCount)  # type: ignore
				except (NotImplementedError, AttributeError):
					pass

				if rowCount is not None and (firstRow + numVisibleRows) > rowCount:
					firstRow = rowCount - numVisibleRows

				# Ensure firstRow is not negative
				firstRow = max(firstRow, 0)

		if firstCol is None:
			firstCol = 0

			if self.tableCurrentCol and self.tableCurrentCol not in range(
				firstCol,
				firstCol + numVisibleCols,
			):
				# Center the current column
				firstCol = self.tableCurrentCol - (numVisibleCols // 2)

				colCount = self.tableColumnCount

				if colCount is not None and (firstCol + numVisibleCols) > colCount:
					firstCol = colCount - numVisibleCols

				# Ensure firstCol is not negative
				firstCol = max(firstCol, 0)

		self.firstVisibleCol = firstCol
		self.firstVisibleRow = firstRow

		for cell in self.getTableCells(
			firstCol,
			firstRow,
			maxCellsPerRow=numVisibleCols,
			maxRows=numVisibleRows,
		):
			rowNum = cell.rowNumber - 1
			colNum = cell.columnNumber - 1
			textInfo: textInfos.TextInfo | None = None
			if isinstance(cell, NVDAObject):
				textInfo = cell.makeTextInfo(textInfos.POSITION_ALL)
			text = _filterCellText(
				cast(
					str,
					cell.name or getattr(textInfo, "text", "  "),
				),
			)
			if len(text) > self.maxCharsPerCell:
				text = text.strip()
			if len(text) < self.maxCharsPerCell:
				text = text.ljust(self.maxCharsPerCell)
			cellLeftX = x + ((colNum - firstCol) * self.tableCellWidth)
			cellTopY = y + ((rowNum - firstRow) * self.tableCellHeight)
			borderBottom = self.tableCellBorder
			if rowNum == self.tableCurrentRow and colNum == self.tableCurrentCol:
				borderBottom += 1
			self.drawCell(
				buffer,
				cellLeftX,
				cellTopY,
				text,
				border=self.tableCellBorder,
				borderBottom=borderBottom,
				colspan=cell.columnSpan,
			)

	def drawCell(
		self,
		buffer: DpTactileGraphicsBuffer,
		leftX: int,
		topY: int,
		text: str,
		width: int | None = None,
		border: int = 0,
		borderTop: int | None = None,
		borderLeft: int | None = None,
		borderBottom: int | None = None,
		borderRight: int | None = None,
		colspan: int = 1,
	):
		brailleText = translateTextToBraille(text)
		if not width:
			width = self._calculateCellWidth(border, self.maxCharsPerCell * colspan + (colspan - 1) * border)
		innerWidth = width - (border * 2) - self.hCellPadding
		if (len(brailleText) * 3) > innerWidth:
			brailleText = brailleText[: innerWidth // 3]
		if border > 0 or borderTop or borderLeft or borderBottom or borderRight:
			borderTop = border if borderTop is None else borderTop
			borderLeft = border if borderLeft is None else borderLeft
			borderBottom = border if borderBottom is None else borderBottom
			borderRight = border if borderRight is None else borderRight

			for x in range(borderLeft):
				drawLine(buffer, leftX + x, topY, self.tableCellHeight, vertical=True)
			for x in range(borderRight):
				drawLine(buffer, leftX + width - x, topY, self.tableCellHeight + 1, vertical=True)
			for y in range(borderTop):
				drawLine(buffer, leftX, topY + y, width, vertical=False)
			for y in range(borderBottom):
				drawLine(buffer, leftX, topY + self.tableCellHeight - y, width, vertical=False)

			drawBrailleCellsOnTactileBuffer(
				buffer,
				leftX + border + self.hCellPadding,
				topY + border + 1,
				brailleText,
			)

	def draw(self, buffer: DpTactileGraphicsBuffer):
		x = 0
		y = 0
		maxBrailleLineLength = buffer.width // (2 + self.hCellPadding)
		if self.tableCaption:
			truncatedCaption = self.tableCaption[0:maxBrailleLineLength]
			if len(self.tableCaption) > len(truncatedCaption):
				truncatedCaption = truncatedCaption[0:-3] + "..."
			captionCells = translateTextToBraille(truncatedCaption)
			drawBrailleCellsOnTactileBuffer(buffer, 0, 0, captionCells)
			y = y + 4 + self.vCellpadding

		height = buffer.height - y

		self.drawTable(buffer, x, y, height, firstCol=self.firstVisibleCol, firstRow=self.firstVisibleRow)

	def scrollTo(self, row: int, col: int):
		"""
		Scrolls the table presentation to the specified row and column.

		Args:
			row (int): The row number to scroll to.
			col (int): The column number to scroll to.
		"""
		self.firstVisibleRow = row
		self.firstVisibleCol = col

	def scrollForward(self) -> bool:
		"""Scrolls the table presentation forward by the number of visible columns or down by the number of visible rows if already at the right end of the table.

		Returns:
			bool: True if the table was scrolled, False if it was already at the end or not yet drawn.
		"""
		firstVisibleCol: int = self.firstVisibleCol or 0
		if self.numVisibleCols is None or self.numVisibleRows is None:
			# Table not yet drawn
			return False
		if firstVisibleCol + self.numVisibleCols >= self.tableColumnCount:  # type: ignore
			# At end of row, wrap to first column of next row
			if self.scrollDown():
				self.firstVisibleCol = 0
				self._moveNavigatorAfterScroll()
				return True
			return False
		else:
			result = self.scrollRight()
			if result:
				self._moveNavigatorAfterScroll()
			return result

	def scrollBack(self) -> bool:
		"""Scrolls the table presentation back by the number of visible columns or up by the number of visible rows if already at the left edge of the table.

		Returns:
			bool: True if the table was scrolled, False if it was already at the beginning or not yet drawn.
		"""
		if self.numVisibleCols is None or self.numVisibleRows is None:
			# Table not yet drawn
			return False
		firstVisibleCol: int = self.firstVisibleCol or 0
		if firstVisibleCol == 0:
			# At start of row, wrap to last column of previous row
			if self.scrollUp():
				colCount = self.tableColumnCount
				if colCount is not None:
					# Calculate last page of columns
					lastPageStart = ((colCount - 1) // self.numVisibleCols) * self.numVisibleCols
					self.firstVisibleCol = lastPageStart
				self._moveNavigatorAfterScroll()
				return True
			return False
		else:
			result = self.scrollLeft()
			if result:
				self._moveNavigatorAfterScroll()
			return result

	def scrollRight(self) -> bool:
		"""Scrolls the table presentation to the right by the number of visible columns.

		Returns:
			bool: True if the table was scrolled, False if it was already at the end.
		"""
		if self.numVisibleCols is None:
			return False
		firstVisibleCol: int = self.firstVisibleCol or 0
		if firstVisibleCol + self.numVisibleCols >= self.tableColumnCount:  # type: ignore
			return False
		self.firstVisibleCol = firstVisibleCol + self.numVisibleCols
		return True

	def scrollLeft(self) -> bool:
		"""Scrolls the table presentation to the left by the number of visible columns.

		Returns:
			bool: True if the table was scrolled, False if it was already at the beginning.
		"""
		firstVisibleCol: int = self.firstVisibleCol or 0
		if self.numVisibleCols is None:
			return False
		if firstVisibleCol == 0:
			return False
		if firstVisibleCol - self.numVisibleCols < 0:
			# Scroll to the left edge
			self.firstVisibleCol = 0
			return True
		self.firstVisibleCol = firstVisibleCol - self.numVisibleCols
		return True

	def scrollDown(self) -> bool:
		"""Scrolls the table presentation down by the number of visible rows.

		Returns:
			bool: True if the table was scrolled, False if it was already at the end.
		"""
		if self.numVisibleRows is None:
			return False
		firstVisibleRow: int = self.firstVisibleRow or 0
		if firstVisibleRow + self.numVisibleRows >= self.tableRowCount:  # type: ignore
			return False
		self.firstVisibleRow = firstVisibleRow + self.numVisibleRows
		return True

	def scrollUp(self) -> bool:
		"""Scrolls the table presentation up by the number of visible rows.

		Returns:
			bool: True if the table was scrolled, False if it was already at the beginning.
		"""
		if self.numVisibleRows is None:
			return False
		firstVisibleRow: int = self.firstVisibleRow or 0
		if firstVisibleRow == 0:
			return False
		if firstVisibleRow - self.numVisibleRows < 0:
			# Scroll to the top
			self.firstVisibleRow = 0
			return True
		self.firstVisibleRow = firstVisibleRow - self.numVisibleRows
		return True

	def _moveNavigatorAfterScroll(self) -> None:
		"""Move navigator object after scroll based on user setting.

		Reads the tableNavigatorAfterScroll configuration and moves the
		NVDA navigator object to either the first visible cell or center cell.
		Fails silently if target cell cannot be found.
		"""
		setting = configuration.getTableNavigatorAfterScroll(fromCache=True)
		if setting == configuration.TableNavigatorAfterScroll.DO_NOTHING:
			return

		# Must have visible dimensions to calculate target
		if self.numVisibleRows is None or self.numVisibleCols is None:
			return

		# Calculate target position (0-based)
		firstRow = self.firstVisibleRow or 0
		firstCol = self.firstVisibleCol or 0
		if setting == configuration.TableNavigatorAfterScroll.FIRST_CELL:
			targetRow = firstRow
			targetCol = firstCol
		else:  # CENTER_CELL
			# Calculate center of actual visible content (not window size)
			# When table is smaller than window, center the actual cells
			rowCount = self.tableRowCount
			colCount = self.tableColumnCount
			actualVisibleRows = self.numVisibleRows
			actualVisibleCols = self.numVisibleCols
			if rowCount is not None:
				actualVisibleRows = min(self.numVisibleRows, rowCount - firstRow)
			if colCount is not None:
				actualVisibleCols = min(self.numVisibleCols, colCount - firstCol)
			targetRow = firstRow + (actualVisibleRows // 2)
			targetCol = firstCol + (actualVisibleCols // 2)

		# Find target cell
		for cell in self.getTableCells(
			self.firstVisibleCol or 0,
			self.firstVisibleRow or 0,
			self.numVisibleCols,
			self.numVisibleRows,
		):
			# getTableCells uses 1-based, we calculated 0-based
			if cell.rowNumber - 1 == targetRow and cell.columnNumber - 1 == targetCol:
				# Try to move navigator/focus to the target cell
				if self._selectCell(cell, targetRow, targetCol):
					return

		log.debug(f"Could not find cell at row {targetRow}, col {targetCol}")

	def _selectCell(self, cell: FakeNVDAObjectCell, row: int, col: int) -> bool:
		"""Select/navigate to a table cell.

		For virtual buffers in browse mode (web tables, Word browse mode),
		moves the browse mode caret via TreeInterceptor.
		For UIA objects in focus mode (Word focus mode), uses setFocus().
		For regular tables, sets the navigator object to the cell.
		For Excel tables, this is overridden to use COM selection.

		The movement is deferred to the next core cycle to allow NVDA's
		event system to finish processing the scroll event.

		:param cell: The table cell to select.
		:param row: The 0-based row number (for logging).
		:param col: The 0-based column number (for logging).
		:returns: True if successful, False otherwise.
		"""
		# For regular tables, cell is already a real NVDAObject (cast to FakeNVDAObjectCell interface)
		if not isinstance(cell, NVDAObject):
			log.debug(f"Cell at row {row}, col {col} is not an NVDAObject")
			return False

		targetObj = cell

		# Defer the movement to the next core cycle
		# This allows NVDA's event system to finish processing the current
		# scroll event before we move the caret/navigator
		def doMove():
			try:
				# Check if this cell is in a virtual buffer (TreeInterceptor)
				treeInterceptor = getattr(targetObj, "treeInterceptor", None)
				treeInterceptorReady = treeInterceptor is not None and getattr(
					treeInterceptor,
					"isReady",
					False,
				)
				# Check if in browse mode (not passThrough) vs focus mode (passThrough)
				passThrough = getattr(treeInterceptor, "passThrough", True) if treeInterceptor else True
				inBrowseMode = treeInterceptorReady and not passThrough

				if inBrowseMode:
					# Browse mode (web or Word browse mode): move caret via TreeInterceptor
					# Type assertion: inBrowseMode implies treeInterceptorReady which implies treeInterceptor is not None
					assert treeInterceptor is not None
					try:
						# Create TextInfo at the cell's position in the virtual buffer
						textInfo = treeInterceptor.makeTextInfo(targetObj)
						# Collapse to a point (no text selection) - just move caret
						textInfo.collapse()
						# Move the browse mode caret by setting selection
						treeInterceptor.selection = textInfo
						return
					except (NotImplementedError, AttributeError, RuntimeError):
						pass  # Fall through to other methods

				# Focus mode or no TreeInterceptor (e.g., Word UIA tables):
				# Use UIA Grid pattern to get cell and set document selection
				if treeInterceptor is None:
					import UIAHandler

					try:
						# Get the table's UIA element and Grid pattern
						tableUIAElement = getattr(self.tableObj, "UIAElement", None)
						if tableUIAElement is not None:
							punk = tableUIAElement.GetCurrentPattern(UIAHandler.UIA_GridPatternId)
							if punk:
								gridPattern = punk.QueryInterface(UIAHandler.IUIAutomationGridPattern)
								cellElement = gridPattern.GetItem(row, col)
								if cellElement:
									document = getattr(self.tableObj, "parent", None)
									if document is not None and hasattr(document, "makeTextInfo"):
										cellTextInfo = document.makeTextInfo(cellElement)
										cellTextInfo.collapse()
										document.selection = cellTextInfo
										return
					except Exception:
						# COMError subclasses Exception, so one handler covers both.
						log.debug(f"UIA Grid pattern failed for row {row}, col {col}", exc_info=True)

				# Fallback: try setFocus on the original target object
				if hasattr(targetObj, "setFocus"):
					try:
						targetObj.setFocus()
						return
					except Exception:
						pass  # Fall through to navigator fallback

				# Fallback: move navigator object
				api.setNavigatorObject(targetObj)
			except Exception:
				log.debug(f"Deferred cell selection failed for row {row}, col {col}", exc_info=True)

		# Queue for next core cycle (approximately 10ms)
		core.callLater(10, doMove)

		return True


class ExcelTable(Table):
	def _get_tableColumnCount(self) -> int | None:
		try:
			return cast(int, self.tableObj.excelWorksheetObject.columns.count)  # type: ignore
		except AttributeError:
			return None

	def _get_tableRowCount(self) -> int | None:
		try:
			return cast(int, self.tableObj.excelWorksheetObject.rows.count)  # type: ignore
		except AttributeError:
			return None

	def getTableCells(
		self,
		startAtCol: int = 0,
		startAtRow: int = 0,
		maxCellsPerRow: int = 20,
		maxRows: int | None = None,
	) -> Iterator[FakeNVDAObjectCell]:
		cellsToIgnore: list[tuple[int, int]] = []
		try:
			ws = self.tableObj.excelWorksheetObject  # type: ignore
		except AttributeError:
			raise ValueError("ExcelTable requires an NVDA object with an excelWorksheetObject attribute.")

		# Ensure non-negative start positions (Excel uses 1-based indexing)
		startAtCol = max(0, startAtCol)
		startAtRow = max(0, startAtRow)

		# Get worksheet bounds to avoid accessing invalid cells
		maxRow = cast(int, ws.rows.count)
		maxCol = cast(int, ws.columns.count)

		endRow = min(startAtRow + maxRows, maxRow) if maxRows is not None else maxRow
		endCol = min(startAtCol + maxCellsPerRow, maxCol)

		for row in range(startAtRow + 1, endRow + 1):
			for col in range(startAtCol + 1, endCol + 1):
				if (row, col) in cellsToIgnore:
					continue
				try:
					excelCell = ws.cells(row, col)  # type: ignore
				except Exception:
					# Skip cells that can't be accessed (e.g., protected, invalid)
					continue
				if excelCell is None:
					break
				cell = self._makeFakeCell(excelCell)
				if cell.columnSpan > 1:
					# If the cell is merged, we need to skip the other cells in the merge area
					for mergeCol in range(col + 1, col + cell.columnSpan):
						cellsToIgnore.append((row, mergeCol))
				yield cell

	def _makeFakeCell(self, excelCell) -> FakeNVDAObjectCell:  # type: ignore
		"""
		Creates a FakeNVDAObjectCell from an Excel cell object.

		Args:
			excelCell: The Excel cell object to convert.

		Returns:
			FakeNVDAObjectCell: A fake NVDA object representing the Excel cell.
		"""
		return FakeNVDAObjectCell(
			rowNumber=excelCell.row,
			columnNumber=excelCell.column,
			name=excelCell.text,
			columnSpan=excelCell.mergeArea.columns.count or 1,
			sourceObject=excelCell,  # Store for later resolution to NVDA object
		)

	def _selectCell(self, cell: FakeNVDAObjectCell, row: int, col: int) -> bool:
		"""Select an Excel cell via COM.

		Excel fake cells aren't real NVDA objects. Instead, we use Excel's COM
		interface to select the cell, which automatically moves focus.

		The focus change is deferred to the next core cycle to allow NVDA's
		event system to process properly.

		:param cell: The fake cell with row/column information and COM source object.
		:param row: The 0-based row number (for logging).
		:param col: The 0-based column number (for logging).
		:returns: True if successful, False otherwise.
		"""
		try:
			# Get worksheet for re-fetching the cell in the deferred callback
			ws = self.tableObj.excelWorksheetObject  # type: ignore
			if ws is None:
				log.debug(f"Excel worksheet not available for cell at row {row}, col {col}")
				return False

			# Use 1-based Excel coordinates
			excelRow = row + 1
			excelCol = col + 1

			# Capture tableObj for use in the deferred callback
			tableObj = self.tableObj

			# Defer the selection to the next core cycle
			# This allows NVDA's event system to finish processing the current
			# scroll event before we trigger the focus change
			def doSelect() -> None:
				comCallSucceeded = False
				try:
					# Re-fetch cell to ensure valid COM reference (avoids stale object issues)
					excelCell = ws.Cells(excelRow, excelCol)  # type: ignore
					# Use Application.Goto which handles worksheet activation automatically
					# This is more reliable than Range.Activate() which requires the worksheet
					# to already be active. Arguments are positional: (Reference, Scroll)
					# Scroll=False to avoid interfering with DotPad scrolling.
					excelCell.Application.Goto(excelCell, False)
					log.debug(f"Activated Excel cell at row {row}, col {col} via Application.Goto (deferred)")
					comCallSucceeded = True
				except Exception as e:
					log.debug(f"Application.Goto failed for cell at row {row}, col {col}: {e}")
					# Fallback to direct Activate if Goto fails
					try:
						excelCell = ws.Cells(excelRow, excelCol)  # type: ignore
						excelCell.Activate()
						log.debug(
							f"Activated Excel cell at row {row}, col {col} via Activate fallback (deferred)",
						)
						comCallSucceeded = True
					except Exception:
						log.debug(
							f"Deferred activation failed for cell at row {row}, col {col}",
							exc_info=True,
						)

				# After successful COM call, explicitly notify NVDA of the focus change
				# This mirrors NVDA's own Excel navigation which manually fires gainFocus events
				if comCallSucceeded:
					try:
						# Get the active cell as an NVDA ExcelCell object
						activeCellObj = tableObj._getActiveCell()  # type: ignore
						eventHandler.executeEvent("gainFocus", activeCellObj)
						log.debug(f"Fired gainFocus event for Excel cell at row {row}, col {col}")
					except Exception:
						log.debug("Could not fire gainFocus event for Excel cell", exc_info=True)

			# Queue with delay to allow scroll operation to complete fully
			# and NVDA event system to settle before triggering focus change
			core.callLater(100, doSelect)

			return True
		except (AttributeError, NotImplementedError, Exception):
			log.debug(f"Could not prepare Excel cell selection at row {row}, col {col}", exc_info=True)
			return False
