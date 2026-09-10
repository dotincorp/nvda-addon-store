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

import time
from abc import ABC
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, cast

import api
import core
import eventHandler
import textInfos
from baseObject import AutoPropertyObject
from IAccessibleHandler import IA2
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
from NVDAObjects.IAccessible import IAccessible
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


_CellT = TypeVar("_CellT")


def _timeIteration(cells: Iterable[_CellT], stats: TableDrawStats) -> Iterator[_CellT]:
	"""Yield from ``cells``, accumulating the time spent producing each one.

	Fetching cells is a separate cost from drawing them, and on a table the
	application serves out of process it dominates. Timing it here rather than
	inside the producer keeps every producer path measured the same way.
	"""
	iterator = iter(cells)
	while True:
		started = time.perf_counter()
		try:
			cell = next(iterator)
		except StopIteration:
			stats.cellFetchSeconds += time.perf_counter() - started
			return
		stats.cellFetchSeconds += time.perf_counter() - started
		stats.cellsMaterialised += 1
		yield cell


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
class TableDrawStats:
	"""What one ``drawTable`` pass cost, for the debug line it emits.

	``rowsMaterialised`` is the number this exists for: NVDA builds an
	NVDAObject for every child it hands us, so a table that exposes hundreds of
	rows costs hundreds of object constructions to draw the handful that fit on
	the display. Comparing it against ``cellsDrawn`` says whether a slow table
	is slow in row collection or somewhere else.
	"""

	cellsDrawn: int = 0
	cellsMaterialised: int = 0
	rowsMaterialised: int = 0
	cellFetchSeconds: float = 0.0
	cellTextSeconds: float = 0.0
	totalSeconds: float = 0.0


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
		self.lastDrawStats = TableDrawStats()

		if obj.role in TABLE_ROLES:
			self.tableObj = obj
			if hasattr(obj, "_currentRow") and hasattr(obj, "_currentCol"):
				self.tableCurrentRow = cast(int, obj._currentRow)  # type: ignore
				self.tableCurrentCol = cast(int, obj._currentCol)  # type: ignore
		else:
			raise ValueError(f"table must be an NVDA object with a table role, got {obj.role}")

		# Stripped: a name of " " is truthy, and draw() would reserve five dot
		# rows for it and then paint nothing there - a blank band above the
		# table that reads as the view starting a row too low.
		self.tableCaption = (self.tableObj.name or obj.description or "").strip()
		self.hCellPadding = hCellPadding
		self.vCellpadding = vCellPadding

	def _makeCellFromIA2(self, rawCell: Any) -> NVDAObject:
		"""Wrap a raw IAccessible cell pointer in an NVDAObject.

		Split out so tests can exercise the window fetch without COM.
		"""
		return IAccessible(
			IAccessibleObject=rawCell.QueryInterface(IA2.IAccessible2),
			IAccessibleChildID=0,
		)

	def _getIA2CellAccessor(self) -> Callable[[int, int], Any] | None:
		"""Return a ``(rowIndex, colIndex) -> raw cell`` callable, or None.

		Both IAccessibleTable2 and its predecessor can hand back a single cell by
		coordinate. Mirrors what NVDA's own table navigation does in
		``NVDAObjects.IAccessible.ia2Web``.
		"""
		table2: Any = getattr(self.tableObj, "IAccessibleTable2Object", None)
		if table2 is not None:
			return table2.cellAt

		table1: Any = getattr(self.tableObj, "IAccessibleTableObject", None)
		if table1 is not None:
			return table1.accessibleAt

		return None

	def _getCellWindow(
		self,
		startAtCol: int,
		startAtRow: int,
		maxCellsPerRow: int,
		maxRows: int | None,
	) -> list[NVDAObject] | None:
		"""Fetch just the cells that will be drawn, one lookup each.

		Walking rows instead means asking for ``row.children``, which NVDA builds
		eagerly: the whole row is turned into NVDAObjects however few columns fit
		on the display. On a table served out of process that is the entire cost
		of a draw — measured at ~11ms per cell object in Google Sheets, so a
		25-column table cost ~1.7s to show six columns of it.

		:returns: The cells in the window, or None if the table cannot serve
			cells by coordinate and the caller should walk rows instead. A window
			that should have held cells but yielded none also returns None, so a
			table that exposes the interface but refuses every lookup gets the
			row walk rather than an empty frame. That is a second chance, not a
			guarantee: a window covered entirely by one cell spanning in from
			outside it comes back empty from either path.
		"""
		accessor = self._getIA2CellAccessor()
		if accessor is None:
			return None

		endCol = startAtCol + maxCellsPerRow
		if self.tableColumnCount is not None:
			endCol = min(endCol, self.tableColumnCount)
		endRow = startAtRow + maxRows if maxRows is not None else self.tableRowCount
		if endRow is None:
			# No row count to bound an open-ended request; walking rows at least
			# terminates on its own.
			return None
		if self.tableRowCount is not None:
			endRow = min(endRow, self.tableRowCount)

		cells: list[NVDAObject] = []
		seen: set[tuple[Any, Any]] = set()
		covered: set[tuple[int, int]] = set()
		for rowIndex in range(startAtRow, endRow):
			for colIndex in range(startAtCol, endCol):
				try:
					rawCell = accessor(rowIndex, colIndex)
					if rawCell is None:
						continue
					cell = cast(Any, self._makeCellFromIA2(rawCell))
					# A merged cell answers for every coordinate it spans, so the
					# same cell comes back more than once; drawTable expects each
					# one only once and handles the span itself.
					key = (cell.rowNumber, cell.columnNumber)
					# This coordinate is spoken for, whether or not the cell is
					# drawn below. The probe is the authority rather than the
					# cell's span: a merged cell answers at every coordinate it
					# covers, so recording the coordinate we asked about needs
					# no span attributes and cannot disagree with them.
					covered.add((rowIndex, colIndex))
				except Exception:
					# Ragged rows, hidden cells and out-of-range coordinates all
					# raise here. One missing cell must not lose the whole draw.
					continue
				if key in seen:
					continue
				seen.add(key)
				# A cell spanning into the window from above or to the left
				# answers for these coordinates but starts outside them, so
				# drawTable would place it at a negative offset and paint a
				# fragment of it over the first visible row or column. The row
				# walk never produced such a cell; skip it for parity.
				if (cell.rowNumber - 1) < startAtRow or (cell.columnNumber - 1) < startAtCol:
					continue
				cells.append(cell)
		if not cells and endRow > startAtRow and endCol > startAtCol:
			return None
		cells.extend(
			cast("list[NVDAObject]", self._fillEmptyCells(covered, startAtRow, endRow, startAtCol, endCol)),
		)
		return cells

	@staticmethod
	def _fillEmptyCells(
		covered: set[tuple[int, int]],
		startAtRow: int,
		endRow: int,
		startAtCol: int,
		endCol: int,
	) -> list[FakeNVDAObjectCell]:
		"""Blank cells for coordinates the table served nothing for.

		A ragged table - Google Sheets' screen-reader view has one, where the
		header row holds fewer cells than the data rows below it - leaves gaps
		inside the window. Drawing nothing there draws no border either, so the
		short row visibly stopped partway across while every row under it ran
		the full width. A reader cannot tell a missing cell from an empty one,
		and the inconsistent grid is what misleads, so the gaps are filled.

		Narrowing the window to the shortest row instead would hide real data,
		the same way bounding an Excel sheet by its used range did.
		"""
		return [
			FakeNVDAObjectCell(rowNumber=rowIndex + 1, columnNumber=colIndex + 1, name="")
			for rowIndex in range(startAtRow, endRow)
			for colIndex in range(startAtCol, endCol)
			if (rowIndex, colIndex) not in covered
		]

	def getTableCells(
		self,
		startAtCol: int = 0,
		startAtRow: int = 0,
		maxCellsPerRow: int = 20,
		maxRows: int | None = None,
	) -> Iterator[FakeNVDAObjectCell]:
		window = self._getCellWindow(startAtCol, startAtRow, maxCellsPerRow, maxRows)
		if window is not None:
			yield from cast(list[FakeNVDAObjectCell], window)
			return

		rows: list[NVDAObject] = []
		for c in self.tableObj.children:
			if c.role == ROLE_TABLEROW:
				rows.append(c)
			elif c.role == ROLE_GROUPING:
				for gc in c.children:
					if gc.role == ROLE_TABLEROW:
						rows.append(gc)
		self.lastDrawStats.rowsMaterialised = len(rows)

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

	def invalidateExtentCache(self) -> None:
		"""Drop any cached row/column count before a draw.

		A no-op here, because the base getters read the object every time.
		Subclasses that cache a COM round trip override it.
		"""

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
		drawStarted = time.perf_counter()
		self.lastDrawStats = TableDrawStats()
		# The extent can change under us - the user types into a cell past the
		# end - and the presentation this table belongs to survives the whole
		# visit, so anything cached on it is cached effectively forever.
		self.invalidateExtentCache()

		if height is None:
			height = buffer.height
		if width is None:
			width = buffer.width

		# -1 because adjacent cells share a border: a cell is drawn from its
		# origin through origin + cellHeight inclusive (drawCell puts the bottom
		# border at topY + tableCellHeight), so N cells span N * cellHeight + 1
		# dots, not N * cellHeight. Without it the last row's bottom border fell
		# one dot outside the buffer and was clipped away. Same on both axes.
		self.numVisibleRows = numVisibleRows = max(0, (height - 1) // self.tableCellHeight)
		self.numVisibleCols = numVisibleCols = max(0, (width - 1) // self.tableCellWidth)

		if firstRow is None:
			firstRow = 0

			if self.tableCurrentRow and self.tableCurrentRow not in range(
				firstRow,
				firstRow + numVisibleRows,
			):
				# Center the current row
				firstRow = self.tableCurrentRow - (numVisibleRows // 2)
				log.debug(
					"Centering row %s in %s visible rows: firstRow=%s",
					self.tableCurrentRow,
					numVisibleRows,
					firstRow,
				)

				# self.tableRowCount, not self.tableObj.rowCount: the subclass is
				# where a truthful extent lives. An Excel worksheet reports
				# 1,048,576 rows (and NVDA's ExcelWorksheet exposes no rowCount at
				# all), so reading the raw object skipped this clamp entirely and
				# disagreed with the one the edge jumps use.
				rowCount: int | None = self.tableRowCount

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

		cellsToDraw = self.getTableCells(
			firstCol,
			firstRow,
			maxCellsPerRow=numVisibleCols,
			maxRows=numVisibleRows,
		)
		for cell in _timeIteration(cellsToDraw, self.lastDrawStats):
			rowNum = cell.rowNumber - 1
			colNum = cell.columnNumber - 1
			# makeTextInfo is a cross-process call, and the name usually carries
			# the text already.
			textStarted = time.perf_counter()
			text = cell.name
			if not text:
				textInfo: textInfos.TextInfo | None = None
				if isinstance(cell, NVDAObject):
					textInfo = cell.makeTextInfo(textInfos.POSITION_ALL)
				text = getattr(textInfo, "text", "  ")
			text = _filterCellText(cast(str, text))
			self.lastDrawStats.cellTextSeconds += time.perf_counter() - textStarted
			self.lastDrawStats.cellsDrawn += 1
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

		stats = self.lastDrawStats
		stats.totalSeconds = time.perf_counter() - drawStarted
		if log.isEnabledFor(log.DEBUG):
			# One line per draw, and only when debug logging is on: this is the
			# measurement a slow-table report is diagnosed from, and re-deriving
			# it means shipping the user another instrumented build.
			try:
				tableSize = "%sx%s" % (self.tableRowCount, self.tableColumnCount)
			except Exception:
				# Both are COM reads, and an application that is busy can refuse
				# them. A diagnostic must never be able to break a render.
				tableSize = "unknown"
			log.debug(
				"Table draw: %d cells in %.1fms (fetch %.1fms, cell text %.1fms), "
				"%d cells and %d rows materialised for %sx%s visible at r%s c%s, "
				"cursor r%s c%s, table %s, caption %r, instance %s",
				stats.cellsDrawn,
				stats.totalSeconds * 1000,
				stats.cellFetchSeconds * 1000,
				stats.cellTextSeconds * 1000,
				stats.cellsMaterialised,
				stats.rowsMaterialised,
				numVisibleRows,
				numVisibleCols,
				firstRow,
				firstCol,
				self.tableCurrentRow,
				self.tableCurrentCol,
				tableSize,
				self.tableCaption,
				# A changing id means the presentation was rebuilt and the
				# viewport was reset rather than scrolled.
				id(self),
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
		colCount = self.tableColumnCount
		# A table that does not report its width cannot say where a row ends, so
		# there is nothing to wrap at; the plain right step still refuses safely.
		if colCount is not None and firstVisibleCol + self.numVisibleCols >= colCount:
			# At end of row, wrap to first column of next row
			if self.scrollDown():
				self.firstVisibleCol = 0
				self.moveNavigatorAfterScroll()
				return True
			return False
		else:
			result = self.scrollRight()
			if result:
				self.moveNavigatorAfterScroll()
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
				self.moveNavigatorAfterScroll()
				return True
			return False
		else:
			result = self.scrollLeft()
			if result:
				self.moveNavigatorAfterScroll()
			return result

	def scrollRight(self) -> bool:
		"""Scrolls the table presentation to the right by the number of visible columns.

		Returns:
			bool: True if the table was scrolled, False if it was already at the end.
		"""
		if self.numVisibleCols is None or self.tableColumnCount is None:
			return False
		firstVisibleCol: int = self.firstVisibleCol or 0
		if firstVisibleCol + self.numVisibleCols >= self.tableColumnCount:
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
		if self.numVisibleRows is None or self.tableRowCount is None:
			return False
		firstVisibleRow: int = self.firstVisibleRow or 0
		if firstVisibleRow + self.numVisibleRows >= self.tableRowCount:
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

	def _lastFullPageStart(self, count: int | None, pageSize: int | None) -> int | None:
		"""First index of the last screenful that still fills the display.

		``count - pageSize`` rather than a page-aligned multiple, so a jump to the
		end shows a full display rather than whatever remainder the table happens
		to end on. Matches how ``drawTable`` clamps when it auto-centres.

		:returns: The index, or None when the extent or the viewport is unknown.
		"""
		if count is None or pageSize is None:
			return None
		return max(0, count - pageSize)

	def _setFirstVisible(self, target: int, vertical: bool) -> bool:
		"""Move one axis of the viewport to ``target``, clamped to the table.

		Clamping rather than refusing means a step that would overshoot still
		lands on the edge, which is what makes repeated presses feel right.

		:param target: Desired first visible row or column, 0-based.
		:param vertical: True for rows, False for columns.
		:returns: True if the viewport moved.
		"""
		# Annotated because the result is assigned back to the attribute it is
		# read from, and pyright cannot infer a type through that cycle.
		current: int
		limit: int | None
		if vertical:
			pageSize = self.numVisibleRows
			current = self.firstVisibleRow or 0
			limit = self._lastFullPageStart(self.tableRowCount, pageSize)
		else:
			pageSize = self.numVisibleCols
			current = self.firstVisibleCol or 0
			limit = self._lastFullPageStart(self.tableColumnCount, pageSize)

		if pageSize is None:
			# Not drawn yet, so there is no viewport to move.
			return False
		if limit is None:
			# The table does not report its extent, so the far edge cannot be
			# clamped. Moving back is still safe; moving forward is not.
			if target > current:
				return False
			limit = current

		# max(limit, current) rather than limit alone: a page step can leave the
		# view past the last full page (scrollRight lands on a partial trailing
		# page), and clamping to limit there would send a *forward* single step
		# backwards.
		newFirst = max(0, min(target, max(limit, current)))
		if newFirst == current:
			return False
		if vertical:
			self.firstVisibleRow = newFirst
		else:
			self.firstVisibleCol = newFirst
		return True

	def scrollByRows(self, rows: int) -> bool:
		"""Move the viewport ``rows`` rows down (negative for up).

		:returns: True if the viewport moved.
		"""
		return self._setFirstVisible((self.firstVisibleRow or 0) + rows, vertical=True)

	def scrollByCols(self, cols: int) -> bool:
		"""Move the viewport ``cols`` columns right (negative for left).

		:returns: True if the viewport moved.
		"""
		return self._setFirstVisible((self.firstVisibleCol or 0) + cols, vertical=False)

	def scrollToFirstRow(self) -> bool:
		"""Jump the viewport to the top of the table.

		:returns: True if the viewport moved.
		"""
		return self._setFirstVisible(0, vertical=True)

	def scrollToLastRow(self) -> bool:
		"""Jump the viewport to the last full screenful of rows.

		:returns: True if the viewport moved.
		"""
		limit = self._lastFullPageStart(self.tableRowCount, self.numVisibleRows)
		if limit is None:
			return False
		return self._setFirstVisible(limit, vertical=True)

	def scrollToFirstCol(self) -> bool:
		"""Jump the viewport to the left edge of the table.

		:returns: True if the viewport moved.
		"""
		return self._setFirstVisible(0, vertical=False)

	def scrollToLastCol(self) -> bool:
		"""Jump the viewport to the last full screenful of columns.

		:returns: True if the viewport moved.
		"""
		limit = self._lastFullPageStart(self.tableColumnCount, self.numVisibleCols)
		if limit is None:
			return False
		return self._setFirstVisible(limit, vertical=False)

	def moveNavigatorAfterScroll(self) -> None:
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

		if self._selectCellAt(targetRow, targetCol):
			return

		log.debug("Could not find cell at row %s, col %s", targetRow, targetCol)

	def _selectCellAt(self, targetRow: int, targetCol: int) -> bool:
		"""Move to the cell at a 0-based coordinate.

		Split from the scan it replaces because every scroll gesture runs this,
		and fetching the whole visible window to find one cell in it cost a
		second pass over cells the redraw is about to fetch again - on a table
		served out of process, tens of cross-process calls per keypress.

		:returns: True if the navigator or focus moved.
		"""
		cell = self._getCellAt(targetRow, targetCol)
		if cell is not None:
			return self._selectCell(cell, targetRow, targetCol)

		# No lookup by coordinate on this table, so the window is the only way
		# to reach a cell object.
		if self.numVisibleCols is None or self.numVisibleRows is None:
			return False
		for candidate in self.getTableCells(
			self.firstVisibleCol or 0,
			self.firstVisibleRow or 0,
			self.numVisibleCols,
			self.numVisibleRows,
		):
			# getTableCells uses 1-based, we calculated 0-based
			if candidate.rowNumber - 1 == targetRow and candidate.columnNumber - 1 == targetCol:
				return self._selectCell(candidate, targetRow, targetCol)
		return False

	def _getCellAt(self, row: int, col: int) -> Any:
		"""One cell by 0-based coordinate, or None if this table cannot serve one.

		:returns: A cell object, or None to fall back to scanning the window.
		"""
		accessor = self._getIA2CellAccessor()
		if accessor is None:
			return None
		try:
			rawCell = accessor(row, col)
		except Exception:
			log.debug("No cell at row %s, col %s", row, col, exc_info=True)
			return None
		if rawCell is None:
			return None
		return self._makeCellFromIA2(rawCell)

	def _selectCell(self, cell: FakeNVDAObjectCell | None, row: int, col: int) -> bool:
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
			log.debug("Cell at row %s, col %s is not an NVDAObject", row, col)
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
						log.debug("UIA Grid pattern failed for row %s, col %s", row, col, exc_info=True)

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
				log.debug("Deferred cell selection failed for row %s, col %s", row, col, exc_info=True)

		# Queue for next core cycle (approximately 10ms)
		core.callLater(10, doMove)

		return True


class ExcelTable(Table):
	_usedRangeBounds: tuple[int | None, int | None] | None = None
	"""Cached ``(lastRow, lastColumn)`` from the worksheet's used range."""

	def _getUsedRangeBounds(self) -> tuple[int | None, int | None]:
		"""Return the worksheet's last used row and column, 1-based.

		A worksheet reports itself as 1,048,576 x 16,384 whatever it contains, so
		the sheet's own counts would send a jump to the last row a million rows
		into empty space and make paging walk through all of it. The used range is
		the extent a reader cares about.

		It does not have to start at A1 — data in C5:H20 gives a used range whose
		Row is 5 and Rows.Count is 16 — so the last row is the first plus the
		count, less one.

		Cached: this is a COM round trip and ``drawTable`` plus every scroll step
		asks for it. ``Table`` does not enable NVDA's property cache, so nothing
		else would.

		Only a successful read is cached. Excel refuses COM calls freely while it
		is busy, and caching that refusal would leave the extent unknown for the
		life of the presentation - which the reuse shortcut keeps alive for the
		whole worksheet visit - permanently disabling every forward scroll.
		"""
		if self._usedRangeBounds is not None:
			return self._usedRangeBounds
		try:
			usedRange = self.tableObj.excelWorksheetObject.UsedRange  # type: ignore
			lastRow = int(usedRange.Row) + int(usedRange.Rows.Count) - 1
			lastCol = int(usedRange.Column) + int(usedRange.Columns.Count) - 1
		except Exception:
			# A worksheet may also not expose a used range at all. An unknown
			# extent is handled everywhere it is read; the next call retries.
			log.debug("ExcelTable: could not read the worksheet used range", exc_info=True)
			return (None, None)
		# Never report an extent that excludes where the user is. UsedRange
		# lags: it does not grow until Excel notices the edit, so navigating to
		# or typing in a cell past the end would otherwise clamp the viewport
		# behind the cursor and the view would stop following.
		lastRow = max(lastRow, (self.tableCurrentRow or 0) + 1)
		lastCol = max(lastCol, (self.tableCurrentCol or 0) + 1)
		bounds: tuple[int | None, int | None] = (lastRow, lastCol)
		self._usedRangeBounds = bounds
		return bounds

	def _get_tableColumnCount(self) -> int | None:
		return self._getUsedRangeBounds()[1]

	def _get_tableRowCount(self) -> int | None:
		return self._getUsedRangeBounds()[0]

	def invalidateExtentCache(self) -> None:
		self._usedRangeBounds = None

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

	def _selectCellAt(self, targetRow: int, targetCol: int) -> bool:
		"""Go straight to the COM selection, with no cell object at all.

		``_selectCell`` below re-fetches the cell from these coordinates in its
		deferred callback and never reads the object it is handed, so finding
		one first was pure cost - and on Excel the only way to find one is to
		build the whole visible window out of COM round trips.
		"""
		return self._selectCell(None, targetRow, targetCol)

	def _selectCell(self, cell: FakeNVDAObjectCell | None, row: int, col: int) -> bool:
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
				log.debug("Excel worksheet not available for cell at row %s, col %s", row, col)
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
					log.debug(
						"Activated Excel cell at row %s, col %s via Application.Goto (deferred)",
						row,
						col,
					)
					comCallSucceeded = True
				except Exception as e:
					log.debug("Application.Goto failed for cell at row %s, col %s: %s", row, col, e)
					# Fallback to direct Activate if Goto fails
					try:
						excelCell = ws.Cells(excelRow, excelCol)  # type: ignore
						excelCell.Activate()
						log.debug(
							"Activated Excel cell at row %s, col %s via Activate fallback (deferred)",
							row,
							col,
						)
						comCallSucceeded = True
					except Exception:
						log.debug(
							"Deferred activation failed for cell at row %s, col %s",
							row,
							col,
							exc_info=True,
						)

				# After successful COM call, explicitly notify NVDA of the focus change
				# This mirrors NVDA's own Excel navigation which manually fires gainFocus events
				if comCallSucceeded:
					try:
						# Get the active cell as an NVDA ExcelCell object
						activeCellObj = tableObj._getActiveCell()  # type: ignore
						eventHandler.executeEvent("gainFocus", activeCellObj)
						log.debug("Fired gainFocus event for Excel cell at row %s, col %s", row, col)
					except Exception:
						log.debug("Could not fire gainFocus event for Excel cell", exc_info=True)

			# Queue with delay to allow scroll operation to complete fully
			# and NVDA event system to settle before triggering focus change
			core.callLater(100, doSelect)

			return True
		except (AttributeError, NotImplementedError, Exception):
			log.debug("Could not prepare Excel cell selection at row %s, col %s", row, col, exc_info=True)
			return False
