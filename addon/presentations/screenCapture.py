# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated

"""
Screen capture presentation for DotPad tactile display.

This module provides ScreenCapturePresentation and ScreenCaptureProvider for rendering
parent+sibling hierarchy views to the tactile display. Screen capture mode shows
the current navigator object's context by displaying the parent object with all
its children (siblings of the navigator object), with the current object highlighted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import api
import braille
import config
from logHandler import log
from tactile.braille import drawBrailleCells as drawBrailleCellsOnTactileBuffer

from .base import Presentation, PresentationProvider

if TYPE_CHECKING:
	from NVDAObjects import NVDAObject

	from .. import configuration
	from ..brailleDisplayDrivers.dotPad.driver import Display
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from ..utils.braille import translateTextToBraille

# Runtime imports using NVDA's addon module loading
if not TYPE_CHECKING:
	import addonHandler

	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	DpTactileGraphicsBuffer = addon.loadModule(
		"brailleDisplayDrivers.dotPad.tactileBuffer",
	).DpTactileGraphicsBuffer
	configuration = addon.loadModule("configuration")
	translateTextToBraille = addon.loadModule("utils.braille").translateTextToBraille

# Display layout constants.
# Inter-line spacing is owned by the display (``Display.verticalCellSpacing``) — the single
# source of truth — so it is read from the display at render time, not duplicated here. Line
# height in dots = ``display.cellHeight + display.verticalCellSpacing``.
CHILD_INDENT: int = 2  # Number of spaces to indent child objects


class ScreenCapturePresentation(Presentation):
	"""Presentation that renders screen capture (hierarchy) view to the tactile display.

	Screen capture mode shows the parent object and its children (siblings of the
	navigator object) with the current navigator object highlighted. This provides
	context about where the user is in the object hierarchy.

	The viewport is a sticky page: it stays where it is while the navigator moves
	inside it, and flips to the next or previous page — without overlap — when the
	navigator steps off an edge. Bidirectional expansion around the navigator is
	only used to seed the first page, or to recentre after a jump that lands
	somewhere else entirely. The same page can also be turned by hand with the
	scroll gestures.
	"""

	def __init__(self, display: Display):
		"""Initialize a screen capture presentation.

		:param display: The display to render to.
		"""
		super().__init__()
		self._display = display
		# Viewport state - list of objects currently visible
		self._visibleObjects: list[NVDAObject] = []
		# Index of navigator object within _visibleObjects (-1 if not visible)
		self._navigatorIndex: int = -1
		# Parent object being displayed
		self._parent: NVDAObject | None = None
		# Cached navigator object for detecting changes
		self._navObj: NVDAObject | None = None
		# Layout the current viewport was measured against. A kept page is not
		# re-measured on every move, so a settings change would otherwise leave it
		# built for one line budget and drawn against another.
		self._viewportLayout: tuple[int, int, bool, int] | None = None
		# Whether the last draw actually put the navigator object on the display
		self._navigatorWasDrawn: bool = False

	def _getPositionInfo(self, obj: NVDAObject) -> int | None:
		"""Get position index from object's positionInfo if available.

		:param obj: The NVDA object to check.
		:returns: 1-based index from positionInfo, or None if not available.
		"""
		positionInfo = getattr(obj, "positionInfo", None)
		if positionInfo and "indexInGroup" in positionInfo:
			return positionInfo["indexInGroup"]
		return None

	def _buildViewport(
		self,
		centerObj: NVDAObject,
		parent: NVDAObject,
		availableLines: int,
	) -> None:
		"""Build the viewport by expanding bidirectionally from center object.

		Used to seed the first page, and to recentre after the navigator jumps
		somewhere the current page cannot be turned to. Stepping between adjacent
		objects pages instead; see :meth:`_updateViewportForNavigator`.

		:param centerObj: The object to center the viewport on.
		:param parent: The parent object (for context).
		:param availableLines: Number of lines available for child objects.
		"""
		simpleMode = cast(bool, config.conf["reviewCursor"]["simpleReviewMode"])  # pyright: ignore[reportArgumentType, reportOptionalSubscript, reportIndexIssue, reportCallIssue]
		maxLinesPerObject = configuration.getScreenCaptureMaxLinesPerObject()
		showObjectNumbers = configuration.getScreenCaptureShowObjectNumbers()
		maxLineLength = self._display.numCols

		self._visibleObjects = []
		self._navigatorIndex = -1
		self._parent = parent
		self._viewportLayout = (availableLines, maxLinesPerObject, showObjectNumbers, maxLineLength)

		if availableLines <= 0:
			return

		# Calculate lines for center object
		centerLines = self._calculateObjectLineCount(
			centerObj,
			None,
			isActive=True,
			indent=CHILD_INDENT,
			showNumbers=showObjectNumbers,
			maxLineLength=maxLineLength,
			maxLinesPerObject=maxLinesPerObject,
		)

		if centerLines > availableLines:
			# Center object alone exceeds space
			self._visibleObjects = [centerObj]
			self._navigatorIndex = 0
			return

		# Start with center object
		self._visibleObjects = [centerObj]
		self._navigatorIndex = 0
		totalLinesUsed = centerLines

		# Expand bidirectionally
		upwardObj = centerObj
		downwardObj = centerObj

		while totalLinesUsed < availableLines:
			addedObject = False

			# Try adding object above (previous sibling)
			if upwardObj:
				prevObj: NVDAObject | None = upwardObj.simplePrevious if simpleMode else upwardObj.previous  # type: ignore[reportAttributeAccessIssue]
				if prevObj:
					prevLines = self._calculateObjectLineCount(
						prevObj,
						None,
						isActive=False,
						indent=CHILD_INDENT,
						showNumbers=showObjectNumbers,
						maxLineLength=maxLineLength,
						maxLinesPerObject=maxLinesPerObject,
					)
					if totalLinesUsed + prevLines <= availableLines:
						self._visibleObjects.insert(0, prevObj)
						self._navigatorIndex += 1  # Navigator shifted right
						totalLinesUsed += prevLines
						upwardObj = prevObj  # type: ignore[reportUnknownVariableType]
						addedObject = True
					else:
						upwardObj = None
				else:
					upwardObj = None

			# Try adding object below (next sibling)
			if downwardObj and totalLinesUsed < availableLines:
				nextObj: NVDAObject | None = downwardObj.simpleNext if simpleMode else downwardObj.next  # type: ignore
				if nextObj:
					nextLines = self._calculateObjectLineCount(
						nextObj,
						None,
						isActive=False,
						indent=CHILD_INDENT,
						showNumbers=showObjectNumbers,
						maxLineLength=maxLineLength,
						maxLinesPerObject=maxLinesPerObject,
					)
					if totalLinesUsed + nextLines <= availableLines:
						self._visibleObjects.append(nextObj)
						totalLinesUsed += nextLines
						downwardObj = nextObj  # pyright: ignore[reportUnknownVariableType]
						addedObject = True
					else:
						downwardObj = None
				else:
					downwardObj = None

			if not addedObject:
				break

	def _buildViewportFromFirst(
		self,
		firstObj: NVDAObject,
		navObj: NVDAObject,
		parent: NVDAObject,
		availableLines: int,
	) -> None:
		"""Build viewport starting from a specific first object.

		Used when scrolling forward - the first object becomes the new viewport start.

		:param firstObj: The object to start the viewport at.
		:param navObj: The current navigator object.
		:param parent: The parent object.
		:param availableLines: Number of lines available.
		"""
		simpleMode = cast(bool, config.conf["reviewCursor"]["simpleReviewMode"])  # pyright: ignore[reportArgumentType, reportOptionalSubscript, reportIndexIssue, reportCallIssue]
		maxLinesPerObject = configuration.getScreenCaptureMaxLinesPerObject()
		showObjectNumbers = configuration.getScreenCaptureShowObjectNumbers()
		maxLineLength = self._display.numCols

		self._visibleObjects = []
		self._navigatorIndex = -1
		self._parent = parent
		self._viewportLayout = (availableLines, maxLinesPerObject, showObjectNumbers, maxLineLength)

		if availableLines <= 0:
			return

		currentObj: NVDAObject | None = firstObj
		totalLinesUsed = 0

		while currentObj and totalLinesUsed < availableLines:
			isActive = currentObj == navObj  # pyright: ignore[reportUnknownVariableType]
			objLines = self._calculateObjectLineCount(
				currentObj,
				None,
				isActive=isActive,
				indent=CHILD_INDENT,
				showNumbers=showObjectNumbers,
				maxLineLength=maxLineLength,
				maxLinesPerObject=maxLinesPerObject,
			)

			if totalLinesUsed + objLines > availableLines:
				break

			self._visibleObjects.append(currentObj)
			if isActive:
				self._navigatorIndex = len(self._visibleObjects) - 1
			totalLinesUsed += objLines

			currentObj = currentObj.simpleNext if simpleMode else currentObj.next  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]

	def _buildViewportFromLast(
		self,
		lastObj: NVDAObject,
		navObj: NVDAObject,
		parent: NVDAObject,
		availableLines: int,
	) -> None:
		"""Build viewport ending at a specific last object.

		Used when scrolling backward - the last object becomes the new viewport end.

		:param lastObj: The object to end the viewport at.
		:param navObj: The current navigator object.
		:param parent: The parent object.
		:param availableLines: Number of lines available.
		"""
		simpleMode = cast(bool, config.conf["reviewCursor"]["simpleReviewMode"])  # pyright: ignore[reportArgumentType, reportOptionalSubscript, reportIndexIssue, reportCallIssue]
		maxLinesPerObject = configuration.getScreenCaptureMaxLinesPerObject()
		showObjectNumbers = configuration.getScreenCaptureShowObjectNumbers()
		maxLineLength = self._display.numCols

		self._visibleObjects = []
		self._navigatorIndex = -1
		self._parent = parent
		self._viewportLayout = (availableLines, maxLinesPerObject, showObjectNumbers, maxLineLength)

		if availableLines <= 0:
			return

		# Collect objects backward from lastObj
		objects: list[NVDAObject] = []
		currentObj: NVDAObject | None = lastObj
		totalLinesUsed = 0

		while currentObj and totalLinesUsed < availableLines:
			isActive = currentObj == navObj  # pyright: ignore[reportUnknownVariableType]
			objLines = self._calculateObjectLineCount(
				currentObj,
				None,
				isActive=isActive,
				indent=CHILD_INDENT,
				showNumbers=showObjectNumbers,
				maxLineLength=maxLineLength,
				maxLinesPerObject=maxLinesPerObject,
			)

			if totalLinesUsed + objLines > availableLines:
				break

			objects.insert(0, currentObj)  # Insert at front to maintain order
			totalLinesUsed += objLines

			currentObj = currentObj.simplePrevious if simpleMode else currentObj.previous  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]

		# Set visible objects and find navigator index
		self._visibleObjects = objects
		for i, obj in enumerate(objects):
			if obj == navObj:
				self._navigatorIndex = i
				break

	def _getParentObject(self, navObj: NVDAObject) -> NVDAObject | None:
		"""Get the parent object respecting simple review mode.

		:param navObj: The navigator object.
		:returns: The parent object, or None if not available.
		"""
		simpleMode = cast(bool, config.conf["reviewCursor"]["simpleReviewMode"])  # pyright: ignore[reportArgumentType, reportOptionalSubscript, reportIndexIssue, reportCallIssue]
		return navObj.simpleParent if simpleMode else navObj.parent  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]

	def render(self, display: Display) -> DpTactileGraphicsBuffer:
		"""Render the screen capture (hierarchy) view to a tactile graphics buffer.

		Shows the parent object at the top, followed by sibling objects with the
		current navigator object highlighted.

		:param display: The display to render to.
		:returns: A tactile graphics buffer containing the rendered hierarchy.
		"""
		buffer = DpTactileGraphicsBuffer(display.physicalNumCols, display.physicalNumRows)

		navObj = api.getNavigatorObject()
		if not navObj:
			log.debug("No navigator object")
			return buffer

		parent = self._getParentObject(navObj)
		if not parent:
			return buffer

		# Check if navigator changed - page, keep or recentre the viewport
		if self._navObj != navObj:
			self._navObj = navObj
			self._updateViewportForNavigator(navObj, parent, display)

		self._drawViewport(buffer, parent, display)

		# A kept page is not re-measured while the navigator moves inside it, so its
		# content can outgrow the display: an object whose label grew now takes more
		# lines than it did when the page was built, and the navigator falls off the
		# bottom. Rather than re-measure on every move, notice it here — where the
		# lines have just been laid out anyway — and recentre. A viewport that never
		# claimed to hold the navigator is left alone: that is a page turned by hand,
		# which is meant to stay put.
		if self._navigatorIndex >= 0 and not self._navigatorWasDrawn:
			self._rebuildViewportCenteredOnNavigator(navObj, parent, display)
			buffer = DpTactileGraphicsBuffer(display.physicalNumCols, display.physicalNumRows)
			self._drawViewport(buffer, parent, display)

		return buffer

	def _drawViewport(
		self,
		buffer: DpTactileGraphicsBuffer,
		parent: NVDAObject,
		display: Display,
	) -> None:
		"""Draw the parent and the current viewport into a buffer.

		Sets :attr:`_navigatorWasDrawn` to whether the navigator object's own line
		made it onto the display.

		:param buffer: The tactile graphics buffer to draw into.
		:param parent: The parent object, drawn first.
		:param display: The display to draw for.
		"""
		maxLinesPerObject = configuration.getScreenCaptureMaxLinesPerObject()
		showObjectNumbers = configuration.getScreenCaptureShowObjectNumbers()
		maxLineLength = display.numCols
		y = 0
		self._navigatorWasDrawn = False

		# Render parent object first
		parentLineCells = self._formatLine(parent, isActive=False, indent=0, showNumbers=showObjectNumbers)
		y = self._renderObjectToBuffer(buffer, parentLineCells, y, maxLineLength, maxLinesPerObject)

		# Render visible objects
		for i, obj in enumerate(self._visibleObjects):
			if y >= buffer.height:
				break

			isActive = i == self._navigatorIndex
			lineCells = self._formatLine(obj, isActive=isActive, showNumbers=showObjectNumbers)
			y = self._renderObjectToBuffer(buffer, lineCells, y, maxLineLength, maxLinesPerObject)
			if isActive:
				self._navigatorWasDrawn = True

	def _updateViewportForNavigator(
		self,
		navObj: NVDAObject,
		parent: NVDAObject,
		display: Display,
	) -> None:
		"""Move the viewport to follow the navigator object.

		The viewport is a sticky page. While the navigator moves inside it nothing
		changes but the highlight; stepping off an edge turns the page, so the list
		advances a screenful at a time instead of sliding one object per keypress.
		Anything else — a jump to an unrelated object, a different parent, a changed
		line budget — rebuilds the page centred on the navigator.

		The decision is made from the page's edges rather than the previous
		navigator index, which is -1 after the page was turned by hand.

		:param navObj: The current navigator object.
		:param parent: The parent object.
		:param display: The display for dimension calculations.
		"""
		if not self._visibleObjects or self._parent != parent:
			self._rebuildViewportCenteredOnNavigator(navObj, parent, display)
			return

		availableLines = self._calculateAvailableLinesForChildren(display, parent)
		if self._viewportLayout != self._currentViewportLayout(availableLines, display):
			# Built against a different line budget; its measurements no longer hold.
			self._rebuildViewportCenteredOnNavigator(navObj, parent, display)
			return

		# Still on the page: keep it, and just move the highlight. Note that the
		# sibling list is not re-walked here, so a sibling removed from the parent
		# stays listed until the page turns. An object added to the parent is not on
		# the page at all, so it takes one of the branches below instead.
		for index, obj in enumerate(self._visibleObjects):
			if obj == navObj:
				self._navigatorIndex = index
				return

		simpleMode = cast(bool, config.conf["reviewCursor"]["simpleReviewMode"])  # pyright: ignore[reportArgumentType, reportOptionalSubscript, reportIndexIssue, reportCallIssue]
		lastObj = self._visibleObjects[-1]
		firstObj = self._visibleObjects[0]
		afterPage = lastObj.simpleNext if simpleMode else lastObj.next  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
		beforePage = firstObj.simplePrevious if simpleMode else firstObj.previous  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]

		if afterPage is not None and afterPage == navObj:
			# Stepped off the bottom: the navigator starts the next page.
			self._buildViewportFromFirst(navObj, navObj, parent, availableLines)
		elif beforePage is not None and beforePage == navObj:
			# Stepped off the top: the navigator ends the previous page.
			self._buildViewportFromLast(navObj, navObj, parent, availableLines)
		else:
			self._rebuildViewportCenteredOnNavigator(navObj, parent, display)
			return

		if self._navigatorIndex == -1:
			# The navigator object alone does not fit the budget. The page builders
			# leave an empty viewport in that case; centring shows it on its own.
			self._rebuildViewportCenteredOnNavigator(navObj, parent, display)

	def _currentViewportLayout(self, availableLines: int, display: Display) -> tuple[int, int, bool, int]:
		"""Return the layout parameters a viewport built now would be measured against.

		:param availableLines: Lines available for child objects.
		:param display: The display for dimension calculations.
		:returns: The tuple stored in :attr:`_viewportLayout` by the viewport builders.
		"""
		return (
			availableLines,
			configuration.getScreenCaptureMaxLinesPerObject(),
			configuration.getScreenCaptureShowObjectNumbers(),
			display.numCols,
		)

	def _renderObjectToBuffer(
		self,
		buffer: DpTactileGraphicsBuffer,
		lineCells: list[int],
		y: int,
		maxLineLength: int,
		maxLinesPerObject: int,
	) -> int:
		"""Render formatted braille cells to buffer, handling multi-line wrapping.

		:param buffer: The tactile graphics buffer to render to.
		:param lineCells: The braille cells to render.
		:param y: The starting y position in dots.
		:param maxLineLength: Maximum cells per line.
		:param maxLinesPerObject: Maximum lines to render per object.
		:returns: The new y position after rendering.
		"""
		lineHeightInDots = self._display.cellHeight + self._display.verticalCellSpacing
		for lineNum in range(maxLinesPerObject):
			if y >= buffer.height:
				break
			startPos = lineNum * maxLineLength
			if startPos >= len(lineCells):
				break
			lineContent = lineCells[startPos : startPos + maxLineLength]
			if not lineContent:
				break
			drawBrailleCellsOnTactileBuffer(buffer, 0, y, lineContent)
			y += lineHeightInDots
		return y

	def _calculateAvailableLinesForChildren(
		self,
		display: Display,
		parent: NVDAObject,
	) -> int:
		"""Calculate how many lines are available for child objects.

		Accounts for:
		- Actual parent line count (not estimated)
		- Trailing spacing optimization (last object doesn't need spacing)

		:param display: The display for dimension calculations.
		:param parent: The parent object to calculate line usage for.
		:returns: Number of lines available for child objects.
		"""
		maxLinesPerObject = configuration.getScreenCaptureMaxLinesPerObject()
		showObjectNumbers = configuration.getScreenCaptureShowObjectNumbers()
		maxLineLength = display.numCols

		# Calculate buffer height and apply trailing spacing optimization.
		# The last object doesn't need trailing spacing, so we can fit more lines:
		# n lines need (n * lineHeight - verticalCellSpacing) dots. Spacing is read from
		# the display (the single source of truth), so this tracks the configured gap.
		verticalCellSpacing = display.verticalCellSpacing
		lineHeight = display.cellHeight + verticalCellSpacing
		bufferHeight = display.physicalNumRows * display.cellHeight
		totalAvailableLines = (bufferHeight + verticalCellSpacing) // lineHeight

		# Calculate actual parent line count
		parentLines = self._calculateObjectLineCount(
			parent,
			None,
			isActive=False,
			indent=0,
			showNumbers=showObjectNumbers,
			maxLineLength=maxLineLength,
			maxLinesPerObject=maxLinesPerObject,
		)

		return max(0, totalAvailableLines - parentLines)

	def _rebuildViewportCenteredOnNavigator(
		self,
		navObj: NVDAObject,
		parent: NVDAObject,
		display: Display,
	) -> None:
		"""Rebuild the viewport centered on the navigator object.

		:param navObj: The current navigator object.
		:param parent: The parent object.
		:param display: The display for dimension calculations.
		"""
		availableLines = self._calculateAvailableLinesForChildren(display, parent)
		self._buildViewport(navObj, parent, availableLines)

	def _formatLine(
		self,
		obj: NVDAObject,
		isActive: bool = False,
		indent: int = CHILD_INDENT,
		showNumbers: bool = True,
	) -> list[int]:
		"""Format an object as a braille line.

		Uses positionInfo from the object when available and showNumbers is True.

		:param obj: The object to format.
		:param isActive: Whether this is the active (navigator) object.
		:param indent: Number of spaces to indent.
		:param showNumbers: Whether to show index numbers from positionInfo.
		:returns: List of braille cells for the formatted line.
		"""
		prefix = indent * " "
		if showNumbers:
			index = self._getPositionInfo(obj)
			if index is not None:
				prefix += f"{index}. "

		objText = braille.getPropertiesBraille(
			name=obj.name,
			role=obj.role,
			roleText=obj.roleTextBraille,  # pyright: ignore[reportAttributeAccessIssue]
			value=obj.value if not braille.NVDAObjectHasUsefulText(obj) else None,
			states=obj.states,
		)

		result = translateTextToBraille(f"{prefix}{objText}")
		if isActive:
			# Highlight active object with a block at the start
			if result:
				result[0] = 0xFF
		return result

	def _calculateObjectLineCount(
		self,
		obj: NVDAObject,
		index: int | None = None,
		isActive: bool = False,
		indent: int = CHILD_INDENT,
		showNumbers: bool = True,
		maxLineLength: int = 0,
		maxLinesPerObject: int = 1,
	) -> int:
		"""Calculate how many lines an object will use when rendered.

		:param obj: The object to measure.
		:param index: Optional index number.
		:param isActive: Whether this is the active object.
		:param indent: Number of spaces to indent.
		:param showNumbers: Whether to show index numbers.
		:param maxLineLength: Maximum characters per line.
		:param maxLinesPerObject: Maximum lines per object.
		:returns: Number of lines the object will use.
		"""
		lineCells = self._formatLine(obj, isActive, indent, showNumbers)
		if len(lineCells) <= maxLineLength:
			return 1
		linesNeeded = (len(lineCells) + maxLineLength - 1) // maxLineLength
		return min(linesNeeded, maxLinesPerObject)

	def scrollForward(self) -> bool:
		"""Scroll the screen capture view forward (down) by one page.

		No overlap - new page starts with the object after the previous last.

		:returns: True if scrolled, False if already at end.
		"""
		if not self._visibleObjects or not self._parent:
			return False

		navObj = api.getNavigatorObject()
		if not navObj:
			return False

		simpleMode = cast(bool, config.conf["reviewCursor"]["simpleReviewMode"])  # pyright: ignore[reportArgumentType, reportOptionalSubscript, reportIndexIssue, reportCallIssue]

		# Get the object after the last visible one
		lastObj = self._visibleObjects[-1]
		nextObj = lastObj.simpleNext if simpleMode else lastObj.next  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]

		if not nextObj:
			# Already at end
			return False

		# Calculate available lines using centralized helper
		availableLines = self._calculateAvailableLinesForChildren(self._display, self._parent)

		# Build new viewport starting from nextObj
		self._buildViewportFromFirst(nextObj, navObj, self._parent, availableLines)

		return True

	def scrollBack(self) -> bool:
		"""Scroll the screen capture view back (up) by one page.

		No overlap - new page ends with the object before the previous first.

		:returns: True if scrolled, False if already at start.
		"""
		if not self._visibleObjects or not self._parent:
			return False

		navObj = api.getNavigatorObject()
		if not navObj:
			return False

		simpleMode = cast(bool, config.conf["reviewCursor"]["simpleReviewMode"])  # pyright: ignore[reportArgumentType, reportOptionalSubscript, reportIndexIssue, reportCallIssue]

		# Get the object before the first visible one
		firstObj = self._visibleObjects[0]
		prevObj = firstObj.simplePrevious if simpleMode else firstObj.previous  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]

		if not prevObj:
			# Already at start
			return False

		# Calculate available lines using centralized helper
		availableLines = self._calculateAvailableLinesForChildren(self._display, self._parent)

		# Build new viewport ending at prevObj
		self._buildViewportFromLast(prevObj, navObj, self._parent, availableLines)

		return True

	def terminate(self) -> None:
		"""Clean up resources held by this presentation.

		Clears references to NVDA objects in the viewport.
		"""
		self._visibleObjects.clear()
		self._parent = None
		self._navObj = None
		self._viewportLayout = None

	@property
	def name(self) -> str:
		return "screenCapture"


class ScreenCaptureProvider(PresentationProvider):
	"""Provider that creates screen capture presentations.

	Screen capture mode is toggled on/off rather than auto-detected.
	When enabled, it shows the parent+sibling hierarchy view.
	"""

	@property
	def name(self) -> str:
		return "screenCapture"

	def __init__(self):
		"""Initialize the screen capture provider."""
		self._enabled: bool = False
		self._presentation: ScreenCapturePresentation | None = None

	@property
	def enabled(self) -> bool:
		"""Whether screen capture mode is currently enabled."""
		return self._enabled

	def toggle(self) -> bool:
		"""Toggle screen capture mode on/off.

		:returns: The new enabled state (True if now enabled, False if disabled).
		"""
		self._enabled = not self._enabled
		if not self._enabled:
			# Clear the presentation when disabling
			self._presentation = None
		return self._enabled

	def setEnabled(self, enabled: bool) -> None:
		"""Set the enabled state of screen capture mode.

		:param enabled: Whether to enable or disable screen capture mode.
		"""
		if self._enabled != enabled:
			self._enabled = enabled
			if not enabled:
				self._presentation = None

	def canProvide(self, obj: NVDAObject) -> bool:
		"""Check if screen capture mode is enabled.

		:param obj: The NVDA object (not used).
		:returns: True if screen capture mode is enabled.
		"""
		return self._enabled

	def _doCreatePresentation(self, obj: NVDAObject, display: Display) -> ScreenCapturePresentation:
		"""Create a screen capture presentation.

		Reuses existing presentation to maintain scroll state.

		:param obj: The NVDA object (used for display context).
		:param display: The display to render to.
		:returns: A ScreenCapturePresentation instance.
		"""
		# Reuse existing presentation to maintain scroll state
		if self._presentation is None:
			self._presentation = ScreenCapturePresentation(display)
		return self._presentation

	def forceForObject(
		self,
		obj: NVDAObject,
		display: Display,
	) -> ScreenCapturePresentation | None:
		"""Try to force a screen capture presentation.

		Screen capture mode is toggled, not forced via this method.

		:param obj: The NVDA object.
		:param display: The display to render to.
		:returns: None (screen capture doesn't support forcing).
		"""
		# Screen capture mode is toggled, not forced
		return None

	def terminate(self) -> None:
		"""Clean up resources held by this provider.

		Terminates and releases the cached presentation.
		"""
		self._enabled = False
		if self._presentation is not None:
			self._presentation.terminate()
			self._presentation = None
