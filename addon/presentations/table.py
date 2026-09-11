# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated

"""
Table presentation for DotPad tactile display.

This module provides TablePresentation and TableProvider for rendering
table content to the tactile display.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import TYPE_CHECKING

import addonHandler
import api
import inputCore
from globalCommands import SCRCAT_BRAILLE
from logHandler import log
from scriptHandler import script
from textInfos import FieldCommand

from .base import Presentation, PresentationProvider, getActiveRenderer

if TYPE_CHECKING:
	from locationHelper import RectLTRB
	from NVDAObjects import NVDAObject

	from ..brailleDisplayDrivers.dotPad.driver import Display
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from ..extension_points.review_tracking import TriggerReason
	from ..utils import reviewFields
	from ..utils.table import TABLE_CELL_ROLES, TABLE_ROLES, ExcelTable, Table, findAncestorWithRole

# Runtime imports using NVDA's addon module loading
if not TYPE_CHECKING:
	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	DpTactileGraphicsBuffer = addon.loadModule(
		"brailleDisplayDrivers.dotPad.tactileBuffer",
	).DpTactileGraphicsBuffer
	reviewFields = addon.loadModule("utils.reviewFields")
	table_module = addon.loadModule("utils.table")
	Table = table_module.Table
	ExcelTable = table_module.ExcelTable
	TABLE_ROLES = table_module.TABLE_ROLES
	TABLE_CELL_ROLES = table_module.TABLE_CELL_ROLES
	findAncestorWithRole = table_module.findAncestorWithRole

addonHandler.initTranslation()


def getUnderlyingObject(obj: NVDAObject) -> tuple[NVDAObject, bool]:
	"""Get the underlying object for table detection, handling TreeInterceptors.

	If the object has an active TreeInterceptor, returns the NVDAObjectAtStart
	from the review position (the underlying document element). Otherwise
	returns the original object.

	:param obj: The navigator object to check.
	:returns: Tuple of (underlying_object, is_from_tree_interceptor).
		The flag indicates whether TreeInterceptor path was used.
	"""
	treeInterceptor = getattr(obj, "treeInterceptor", None)
	if treeInterceptor is None:
		return obj, False

	# Check TreeInterceptor is ready and alive
	if not getattr(treeInterceptor, "isReady", False):
		return obj, False
	if not getattr(treeInterceptor, "isAlive", True):
		return obj, False

	# Get underlying object via review position
	try:
		reviewPos = api.getReviewPosition()
		if reviewPos is None:  # type: ignore[reportUnnecessaryComparison]
			log.debug("TreeInterceptor present but review position is None")
			return obj, False

		underlyingObj = getattr(reviewPos, "NVDAObjectAtStart", None)
		if underlyingObj is None:
			log.debug("TreeInterceptor present but NVDAObjectAtStart is None")
			return obj, False

		return underlyingObj, True
	except (NotImplementedError, AttributeError, RuntimeError):
		log.debugWarning("Failed to get underlying object from TreeInterceptor", exc_info=True)
		return obj, False


class TablePresentation(Presentation):
	"""Presentation that renders table content to the tactile display.

	This presentation wraps an existing Table object and converts it to
	tactile graphics format for display on the DotPad.
	"""

	def __init__(
		self,
		tableObj: NVDAObject,
		display: Display,
		forcedFrom: NVDAObject | None = None,
	):
		"""Initialize a table presentation.

		:param tableObj: The NVDA table object to render.
		:param display: The display to render to.
		:param forcedFrom: The original navigator object (cell) used to initialize
			the active cell position. If provided, its rowNumber and columnNumber
			are used to set the initial cursor position.
		"""
		super().__init__()
		self._tableObj = tableObj
		self._display = display
		self._forcedFrom = forcedFrom

		# Use ExcelTable for Excel worksheets, Table for everything else
		if hasattr(tableObj, "excelWorksheetObject"):
			TableClass = ExcelTable
		else:
			TableClass = Table

		self._tableData: Table = TableClass(
			tableObj,
			hCellPadding=display.horizontalCellSpacing,
			vCellPadding=display.verticalCellSpacing,
		)

		# Track last known cell position to detect navigation vs scrolling
		self._lastCellRow: int | None = None
		self._lastCellCol: int | None = None

		# Initialize current cell position from forcedFrom if available
		# This ensures the active cell is marked on the first render
		if forcedFrom is not None:
			row, col = self._getCellPosition(forcedFrom)
			if row is not None and col is not None:
				self._tableData.tableCurrentRow = row - 1  # Convert to 0-based
				self._tableData.tableCurrentCol = col - 1
				self._lastCellRow = row - 1
				self._lastCellCol = col - 1

	def _getCellPosition(self, obj: NVDAObject) -> tuple[int | None, int | None]:
		"""Get the row and column position for an object.

		If the object itself doesn't have rowNumber/columnNumber attributes,
		scans up the parent chain to find a containing table cell.
		As a fallback (e.g., for empty cells in Word tables), parses the
		review position's getTextWithFields() for table cell information.

		:param obj: The NVDA object to get position for.
		:returns: Tuple of (rowNumber, columnNumber), both None if not found.
		"""
		row = None
		col = None

		# Try direct attributes first
		try:
			row = getattr(obj, "rowNumber", None)
			col = getattr(obj, "columnNumber", None)
		except NotImplementedError:
			pass
		if row is not None and col is not None:
			return row, col

		# Scan for a cell ancestor
		cell = findAncestorWithRole(obj, TABLE_CELL_ROLES, maxDepth=10, includeSelf=False)
		if cell is not None:
			try:
				row = getattr(cell, "rowNumber", None)
				col = getattr(cell, "columnNumber", None)
			except NotImplementedError:
				pass
			if row is not None and col is not None:
				return row, col

		# TextFields fallback: parse review position's getTextWithFields()
		# This handles empty cells in Word tables where NVDAObjectAtStart returns the table
		row, col = self._getCellPositionViaTextFields()
		if row is not None and col is not None:
			return row, col

		return None, None

	def _getCellPositionViaTextFields(self) -> tuple[int | None, int | None]:
		"""Get cell position from review position's getTextWithFields().

		Parses the field commands to find table cell info with row/column numbers.
		Iterates in reverse order to handle nested tables (innermost cell is last).

		:returns: Tuple of (rowNumber, columnNumber) 1-based, both None if not found.
		"""
		from controlTypes import Role

		try:
			reviewPos = api.getReviewPosition()
			if reviewPos is None:  # type: ignore[reportUnnecessaryComparison]
				log.debug("_getCellPositionViaTextFields: no review position")
				return None, None

			fields = reviewFields.getTextWithFields(reviewPos)

			# Look for a controlStart field with TABLECELL role
			# Iterate in reverse to find innermost cell first (handles nested tables)
			for field in reversed(fields):
				if not isinstance(field, FieldCommand):
					continue
				if field.command != "controlStart":
					continue
				fieldData = field.field
				if fieldData is None:
					continue
				if fieldData.get("role") != Role.TABLECELL:
					continue

				# Found a table cell - extract row/column (already 1-based)
				rowValue = fieldData.get("table-rownumber")  # pyright: ignore[reportUnknownVariableType]
				colValue = fieldData.get("table-columnnumber")  # pyright: ignore[reportUnknownVariableType]
				if isinstance(rowValue, int) and isinstance(colValue, int):
					return rowValue, colValue
			return None, None

		except Exception:
			log.debug("_getCellPositionViaTextFields: exception", exc_info=True)
			return None, None

	def _getRelevantObject(self) -> NVDAObject:
		"""Get the relevant object for position/validity tracking.

		Handles TreeInterceptor context automatically via getUnderlyingObject().

		:returns: The underlying NVDAObject for position tracking.
		"""
		obj, _ = getUnderlyingObject(api.getNavigatorObject())
		return obj

	def render(self, display: Display) -> DpTactileGraphicsBuffer:
		"""Render the table to a tactile graphics buffer.

		Updates cursor position from current navigator before drawing,
		ensuring the view centers on the active cell and highlights it.
		If the current cell moved (user navigated) and is outside the visible
		area, resets scroll position to trigger auto-centering. This preserves
		manual scroll position when the user scrolls away from the current cell.

		:param display: The display to render to.
		:returns: A tactile graphics buffer containing the rendered table.
		"""
		# Update cursor position from current navigator
		navObj = self._getRelevantObject()
		row, col = self._getCellPosition(navObj)
		if row is not None and col is not None:
			currentRow = row - 1  # Convert to 0-based
			currentCol = col - 1

			# Check if cell position changed (user navigated to a different cell)
			cellMoved = currentRow != self._lastCellRow or currentCol != self._lastCellCol

			self._tableData.tableCurrentRow = currentRow
			self._tableData.tableCurrentCol = currentCol
			self._lastCellRow = currentRow
			self._lastCellCol = currentCol

			# Only reset scroll if the cell actually moved AND is outside visible area
			# This ensures keyboard navigation auto-follows while preserving manual scroll
			if cellMoved:
				td = self._tableData
				if td.numVisibleRows is not None and td.numVisibleCols is not None:
					firstRow = td.firstVisibleRow or 0
					firstCol = td.firstVisibleCol or 0
					rowInView = firstRow <= currentRow < firstRow + td.numVisibleRows
					colInView = firstCol <= currentCol < firstCol + td.numVisibleCols
					# Per axis, not both together. Resetting both meant stepping
					# down out of view also re-centred the columns, throwing the
					# view back to the left of the row; following the cursor
					# down should move straight down, the way panning a graphic
					# does. None asks drawTable to auto-centre that axis.
					if not rowInView:
						td.firstVisibleRow = None
					if not colInView:
						td.firstVisibleCol = None

		buffer = DpTactileGraphicsBuffer(display.physicalNumCols, display.physicalNumRows)
		self._tableData.draw(buffer)
		return buffer

	def scrollForward(self) -> bool:
		"""Scroll the table forward.

		:returns: True if scrolling occurred, False if at end.
		"""
		return self._tableData.scrollForward()

	def scrollBack(self) -> bool:
		"""Scroll the table back.

		:returns: True if scrolling occurred, False if at beginning.
		"""
		return self._tableData.scrollBack()

	def isStillValid(self, triggerReason: TriggerReason | None = None) -> bool:
		"""Check if this presentation is still valid for current navigator position.

		A table presentation is valid if the navigator is still within the table.
		This is checked by:
		1. Window handle comparison (detects application switch)
		2. For Excel: worksheet name comparison (detects worksheet switch)
		3. Trying `navObj.table == self._tableObj` (cheap check)
		4. Falling back to bounds check using `location` property

		:returns: True if the presentation is still valid, False otherwise.
		"""
		navObj = self._getRelevantObject()

		# Check 1: Window handle must match (detects app switch)
		tableWindowHandle = getattr(self._tableObj, "windowHandle", None)
		navWindowHandle = getattr(navObj, "windowHandle", None)
		if tableWindowHandle is not None and navWindowHandle is not None:
			if tableWindowHandle != navWindowHandle:
				log.debug(
					"Table invalid: window handle mismatch (%s != %s)",
					tableWindowHandle,
					navWindowHandle,
				)
				return False

		# Check 2: For Excel, verify same worksheet (detects worksheet switch)
		tableWorksheet = getattr(self._tableObj, "excelWorksheetObject", None)
		if tableWorksheet is not None:
			# This is an Excel table - check worksheet identity.
			#
			# A COM failure here is deliberately not caught. Excel refuses calls
			# whenever it is busy, which includes the moment the user types in a
			# cell, and answering False would report a worksheet switch that did
			# not happen — dropping a forced table or lifting a dismissal in the
			# middle of reading one. ``PresentationManager._stillValid`` is the
			# only caller of this method; it turns a raise into "could not tell"
			# and asks again on the next event, which is the truthful answer.
			# Swallowing it here is what made that third answer unreachable on
			# the one table type it was written for.
			#
			# Get worksheet from navigator or its parent (cells are direct children of worksheet)
			navWorksheet = getattr(navObj, "excelWorksheetObject", None)
			if navWorksheet is None:
				parent = getattr(navObj, "parent", None)
				if parent is not None:
					navWorksheet = getattr(parent, "excelWorksheetObject", None)

			if navWorksheet is not None:
				# Compare worksheet names (more reliable than COM object identity)
				if tableWorksheet.Name != navWorksheet.Name:
					log.debug(
						"Table invalid: worksheet changed (%s != %s)",
						tableWorksheet.Name,
						navWorksheet.Name,
					)
					return False

		# Check 3: Quick check - does NVDA think we're in the same table?
		try:
			if navObj.table == self._tableObj:  # type: ignore
				return True
		except (NotImplementedError, AttributeError):
			pass

		# Check 4: Fallback bounds check
		tableLocation: RectLTRB | None = getattr(self._tableObj, "location", None)
		navLocation: RectLTRB | None = getattr(navObj, "location", None)

		if tableLocation and navLocation:
			# Check if navigator is within table bounds
			return (
				tableLocation.left <= navLocation.left
				and tableLocation.top <= navLocation.top
				and tableLocation.right >= navLocation.right
				and tableLocation.bottom >= navLocation.bottom
			)

		return False

	@property
	def tableObj(self) -> NVDAObject | None:
		"""The table NVDAObject this presentation is rendering."""
		return self._tableObj

	def terminate(self) -> None:
		"""Clean up resources held by this presentation.

		Clears references to NVDA objects and table data.
		"""
		self._tableObj = None
		self._tableData = None  # type: ignore[assignment]
		self._forcedFrom = None

	@property
	def name(self) -> str:
		return "table"

	def _afterScroll(self, moved: bool) -> None:
		"""Follow a viewport move with the navigator move and a redraw.

		Nothing happens when the viewport did not move -- at an edge there is
		neither a new cell to move to nor anything to redraw.

		The navigator move honours the user's ``tableNavigatorAfterScroll``
		setting, which defaults to leaving the navigator alone; it lived only on
		``scrollForward`` / ``scrollBack`` before these gestures existed.

		A presentation holds no renderer reference, so the redraw goes through
		the driver. Silent no-op when there is no renderer to ask.
		"""
		if not moved:
			return
		self._tableData.moveNavigatorAfterScroll()
		renderer = getActiveRenderer()
		if renderer is None:
			return
		renderer.requestRender()

	# The layout mirrors GraphicPresentation, so muscle memory carries between
	# modes and both match the [DotPad320X Keys] map the library ships.
	#
	# f2+f4, f1+f3, f2+f3 and the longPress mode switches are deliberately left
	# unbound, so they keep falling through to the driver.

	@script(
		# Translators: description of the table command to show the columns to the left.
		description=_("Show the previous screenful of table columns"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f1",
	)
	def script_pageLeft(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollLeft())

	@script(
		# Translators: description of the table command to show the rows above.
		description=_("Show the previous screenful of table rows"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f2",
	)
	def script_pageUp(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollUp())

	@script(
		# Translators: description of the table command to show the rows below.
		description=_("Show the next screenful of table rows"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f3",
	)
	def script_pageDown(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollDown())

	@script(
		# Translators: description of the table command to show the columns to the right.
		description=_("Show the next screenful of table columns"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f4",
	)
	def script_pageRight(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollRight())

	@script(
		# Translators: description of the table command to move up one row.
		description=_("Move the table view up one row"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f1+f2",
	)
	def script_rowUp(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollByRows(-1))

	@script(
		# Translators: description of the table command to move down one row.
		description=_("Move the table view down one row"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f3+f4",
	)
	def script_rowDown(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollByRows(1))

	@script(
		# Translators: description of the table command to move one column left.
		description=_("Move the table view left one column"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):panLeft+f1",
	)
	def script_columnLeft(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollByCols(-1))

	@script(
		# Translators: description of the table command to move one column right.
		description=_("Move the table view right one column"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):panRight+f4",
	)
	def script_columnRight(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollByCols(1))

	@script(
		# Translators: description of the table command to jump to the first column.
		description=_("Jump the table view to the first column"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f1)",
	)
	def script_jumpToFirstColumn(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollToFirstCol())

	@script(
		# Translators: description of the table command to jump to the first row.
		description=_("Jump the table view to the first row"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f2)",
	)
	def script_jumpToFirstRow(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollToFirstRow())

	@script(
		# Translators: description of the table command to jump to the last row.
		description=_("Jump the table view to the last row"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f3)",
	)
	def script_jumpToLastRow(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollToLastRow())

	@script(
		# Translators: description of the table command to jump to the last column.
		description=_("Jump the table view to the last column"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f4)",
	)
	def script_jumpToLastColumn(self, _gesture: inputCore.InputGesture) -> None:
		self._afterScroll(self._tableData.scrollToLastCol())


class DetectionPath(StrEnum):
	"""Which branch of ``_findTable`` answered.

	Detection is the expensive half of arbitration and runs on every navigation
	event, so the debug line reports which branch paid for it - that is what
	says where an optimisation belongs.
	"""

	NOT_FOUND = "not found"
	SELF = "self"
	OBJ_TABLE = "obj.table"
	VBUF = "vbuf"
	VBUF_MISS = "vbuf (miss)"
	PARENT_WALK = "parent walk"
	REVIEW_POSITION = "review position"
	REVIEW_POSITION_TABLE = "review position .table"
	REVIEW_POSITION_PARENT_WALK = "review position parent walk"


class TableProvider(PresentationProvider):
	"""Provider that creates table presentations.

	This provider detects tables and creates TablePresentation instances.
	It supports auto-detection and forced mode with parent scanning.
	"""

	@property
	def name(self) -> str:
		return "table"

	validityIsAuthoritative = True
	"""Table detection walks parents and document structure, which is far more
	expensive than ``TablePresentation.isStillValid``. Availability is a property
	of the object being navigated, not of this provider, so the presentation's
	own validity check is the complete answer."""

	AUTO_DETECT_PARENT_DEPTH: int = 3
	"""Maximum number of parent levels to scan during auto-detection."""
	MAX_PARENT_SCAN_DEPTH: int = 20
	"""Maximum number of parent levels to scan when forcing table mode."""

	def __init__(self) -> None:
		"""Initialize the table provider with cache variables."""
		# Cache for canProvide -> _doCreatePresentation flow
		# Avoids expensive _findTable being called twice
		self._cachedTable: NVDAObject | None = None
		self._cachedForObj: NVDAObject | None = None
		self._lastDetectionPath: DetectionPath | None = None
		"""Which branch of _findTable resolved the last lookup, for the debug line."""

	def canProvide(self, obj: NVDAObject) -> bool:
		"""Check if this provider can create a presentation for the object.

		Caches the found table for use in _doCreatePresentation.

		:param obj: The NVDA object to check.
		:returns: True if a table can be found within AUTO_DETECT_PARENT_DEPTH.
		"""
		# NVDA fires onReviewMove twice per keypress with the same navigator
		# object instance. Reuse the cached result from the first call to avoid
		# a second expensive lookup.
		if obj is self._cachedForObj:
			return self._cachedTable is not None
		detectionStarted = time.perf_counter()
		tableObj = self._findTable(obj, maxDepth=self.AUTO_DETECT_PARENT_DEPTH)
		if log.isEnabledFor(log.DEBUG):
			log.debug(
				# %r on the role: Role is an IntEnum, so %s prints the bare number.
				"Table detection: %s in %.1fms via %s (role %r)",
				"found" if tableObj is not None else "not found",
				(time.perf_counter() - detectionStarted) * 1000,
				self._lastDetectionPath,
				getattr(obj, "role", None),
			)
		# Cache for use in _doCreatePresentation
		self._cachedTable = tableObj
		self._cachedForObj = obj
		return tableObj is not None

	def _doCreatePresentation(self, obj: NVDAObject, display: Display) -> TablePresentation:
		"""Create a table presentation for the object.

		Uses cached table from canProvide if available.

		:param obj: The NVDA object to create a presentation for.
		:param display: The display to render to.
		:returns: A TablePresentation instance.
		"""
		# Use cached table if available and for same object
		if self._cachedForObj is obj and self._cachedTable is not None:
			tableObj = self._cachedTable
		else:
			# Fallback (shouldn't happen in normal flow)
			tableObj = self._findTable(obj, maxDepth=self.AUTO_DETECT_PARENT_DEPTH)
			if tableObj is None:
				raise RuntimeError("No table found for object")

		# Get cell object for row/column numbers - try review position first
		cellObj = self._getCellObject(obj)
		presentation = TablePresentation(tableObj, display, forcedFrom=cellObj)

		# Clear cache after use
		self._cachedTable = None
		self._cachedForObj = None

		return presentation

	def forceForObject(
		self,
		obj: NVDAObject,
		display: Display,
	) -> TablePresentation | None:
		"""Try to force a table presentation for the given object.

		Uses deep parent scanning (MAX_PARENT_SCAN_DEPTH levels).

		:param obj: The NVDA object to create a presentation for.
		:param display: The display to render to.
		:returns: A TablePresentation instance, or None if no table found.
		"""
		tableObj = self._findTable(obj)  # Uses MAX_PARENT_SCAN_DEPTH
		if tableObj:
			# Get cell object for row/column numbers - try review position first
			cellObj = self._getCellObject(obj)
			return TablePresentation(tableObj, display, forcedFrom=cellObj)
		return None

	def _getCellObject(self, obj: NVDAObject) -> NVDAObject:
		"""Get the best object for extracting cell row/column numbers.

		Tries review position first (for UIA and TreeInterceptor contexts),
		then falls back to the original object.

		:param obj: The navigator object.
		:returns: The object most likely to have rowNumber/columnNumber.
		"""
		# Try review position first - works for Word UIA and TreeInterceptors
		reviewObj = self._getObjectFromReviewPosition()
		if reviewObj is not None and self._hasRowNumber(reviewObj):
			return reviewObj

		# Try underlying object via TreeInterceptor
		underlyingObj, fromTreeInterceptor = getUnderlyingObject(obj)
		if fromTreeInterceptor and underlyingObj is not obj:
			if self._hasRowNumber(underlyingObj):
				return underlyingObj

		# Fall back to original object
		return obj

	def _hasRowNumber(self, obj: NVDAObject) -> bool:
		"""Check if an object has a valid rowNumber attribute.

		:param obj: The object to check.
		:returns: True if rowNumber is accessible and not None.
		"""
		try:
			return getattr(obj, "rowNumber", None) is not None
		except (NotImplementedError, AttributeError):
			return False

	def _findTable(self, obj: NVDAObject, maxDepth: int | None = None) -> NVDAObject | None:
		"""Find a table for the given object.

		Checks in order:
		1. If obj itself is a table, returns it
		2. If obj has a .table attribute (NVDA-provided), returns that
		   This works for native table support (Word, etc.)
		3a. Virtual buffer (treeInterceptor exposes getNVDAObjectFromIdentifier): in-memory lookup
		    via _findTableViaVbuf — zero IA2 COM calls in the not-found case.
		3b. Everything else, non-virtual-buffer TreeInterceptors (Excel, Word)
		    included: IA2 parent walk on obj's parent chain
		4. Gets underlying object via review position (handles Word UIA)
		5. If underlying obj is a table or has .table attribute, returns that
		6. Scans underlying object's parent chain for a table

		:param obj: The starting NVDA object.
		:param maxDepth: Maximum parent levels to scan (steps 3b/6). None = MAX_PARENT_SCAN_DEPTH.
		    Ignored for the virtual buffer path (step 3a) which always searches the full ancestor chain.
		    A non-virtual-buffer TreeInterceptor takes the parent-walk path, not 3a.
		:returns: The table NVDAObject if found, None otherwise.
		"""
		depth = maxDepth if maxDepth is not None else self.MAX_PARENT_SCAN_DEPTH

		self._lastDetectionPath = DetectionPath.NOT_FOUND

		# 1. If obj IS a table, return it
		if obj.role in TABLE_ROLES:
			self._lastDetectionPath = DetectionPath.SELF
			return obj

		# 2. Try obj.table attribute first (works for Word IAccessible, native tables).
		# Validate the role: UIA resolves .table via the GridItemContainingGrid
		# property, which can return a non-table container (e.g. the Windows 11
		# alt+tab switcher is a LIST exposing the Grid pattern). TableClass rejects
		# anything outside TABLE_ROLES, so honour that contract here.
		try:
			table = getattr(obj, "table", None)
			if table is not None and table.role in TABLE_ROLES:
				self._lastDetectionPath = DetectionPath.OBJ_TABLE
				return table
		except (NotImplementedError, AttributeError):
			pass

		# 3a. Virtual buffers only: use their in-memory field data — no IA2 COM calls.
		# The vbuf already has the full parsed ancestor chain; steps 4-6 (review
		# position parent walk) are unnecessary and skipped for this path.
		# A TreeInterceptor that is not a virtual buffer cannot resolve a node
		# identifier - Excel worksheets and Word documents attach one of those -
		# so treating "has a TreeInterceptor" as "is browse mode" would strand
		# every Excel cell on the fast path and never find its worksheet.
		treeInterceptor = getattr(obj, "treeInterceptor", None)
		if treeInterceptor is not None and hasattr(treeInterceptor, "getNVDAObjectFromIdentifier"):
			tableObj = self._findTableViaVbuf(obj)
			self._lastDetectionPath = DetectionPath.VBUF if tableObj is not None else DetectionPath.VBUF_MISS
			return tableObj

		# 3b. Non-browse: scan obj's IA2 parent chain
		table = findAncestorWithRole(obj, TABLE_ROLES, maxDepth=depth, includeSelf=False)
		if table is not None:
			self._lastDetectionPath = DetectionPath.PARENT_WALK
			return table

		# 4. Try review position's underlying object (handles Word UIA)
		underlyingObj = self._getObjectFromReviewPosition()
		if underlyingObj is None or underlyingObj is obj:
			return None

		# 5. Check if underlying obj is a table
		if underlyingObj.role in TABLE_ROLES:
			self._lastDetectionPath = DetectionPath.REVIEW_POSITION
			return underlyingObj

		# Try underlying obj.table attribute (same role-validation as step 2).
		try:
			table = getattr(underlyingObj, "table", None)
			if table is not None and table.role in TABLE_ROLES:
				self._lastDetectionPath = DetectionPath.REVIEW_POSITION_TABLE
				return table
		except (NotImplementedError, AttributeError):
			pass

		# 6. Scan underlying object's parent chain
		table = findAncestorWithRole(underlyingObj, TABLE_ROLES, maxDepth=depth, includeSelf=False)
		if table is not None:
			self._lastDetectionPath = DetectionPath.REVIEW_POSITION_PARENT_WALK
		return table

	def _findTableViaVbuf(self, obj: NVDAObject) -> NVDAObject | None:
		"""Find a table ancestor using the virtual buffer's in-memory field data.

		Called only when obj.treeInterceptor is a virtual buffer - a plain
		BrowseModeTreeInterceptor emits neither the controlIdentifier fields nor
		the getNVDAObjectFromIdentifier method this needs. Uses the review
		position's getTextWithFields() — the same proven path used by
		_getCellPositionViaTextFields — so zero IA2 COM calls in the not-found
		case (most links and paragraphs) and one accChild COM call in the
		found case to materialise the table NVDAObject.

		Layout tables are not excluded, matching the existing IA2 parent-walk
		behaviour in steps 3b/6.

		:param obj: The navigator object (treeInterceptor must be a virtual buffer).
		:returns: The table NVDAObject if found, None otherwise.
		"""
		try:
			reviewPos = api.getReviewPosition()
			if reviewPos is None:  # type: ignore[reportUnnecessaryComparison]
				return None
			fields = reviewFields.getTextWithFields(reviewPos)
		except Exception:
			log.debugWarning("_findTableViaVbuf: failed to get review position fields", exc_info=True)
			return None

		vbuf = getattr(obj, "treeInterceptor", None)
		if vbuf is None:
			return None

		# Walk fields in reverse order (innermost ancestor first) to find a table
		# role. DATAGRID counts as well as TABLE: an ARIA role="grid" surfaces as
		# the former, and TableClass accepts both.
		for field in reversed(fields):
			if not isinstance(field, FieldCommand):
				continue
			if field.command != "controlStart":
				continue
			fieldData = field.field
			if fieldData is None:
				continue
			if fieldData.get("role") not in TABLE_ROLES:
				continue

			# Found a table control field — materialise the NVDAObject.
			docHandle = fieldData.get("controlIdentifier_docHandle")  # pyright: ignore[reportUnknownVariableType]
			nodeId = fieldData.get("controlIdentifier_ID")  # pyright: ignore[reportUnknownVariableType]
			if docHandle is None or nodeId is None:
				continue
			try:
				tableObj = vbuf.getNVDAObjectFromIdentifier(int(docHandle), int(nodeId))
			except Exception:
				log.debugWarning("_findTableViaVbuf: getNVDAObjectFromIdentifier failed", exc_info=True)
				continue
			return tableObj

		return None

	def _getObjectFromReviewPosition(self) -> NVDAObject | None:
		"""Get the NVDAObject at the review position.

		This is useful for accessing the underlying object in virtual buffers
		(TreeInterceptors) and UIA contexts like Word.

		:returns: The NVDAObject at review position, or None if unavailable.
		"""
		try:
			reviewPos = api.getReviewPosition()
			if reviewPos is None:  # type: ignore[reportUnnecessaryComparison]
				return None
			return getattr(reviewPos, "NVDAObjectAtStart", None)
		except (NotImplementedError, AttributeError, RuntimeError):
			log.debugWarning("Failed to get object from review position", exc_info=True)
			return None
