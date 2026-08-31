# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated

"""
Presentation renderer for DotPad tactile display.

This module provides PresentationRenderer that coordinates the presentation
system: listening to events, selecting presentations, and rendering to display.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

import addonHandler
from baseObject import AutoPropertyObject
from logHandler import log

if TYPE_CHECKING:
	from ..brailleDisplayDrivers.dotPad.driver import Display
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from . import PresentationManager, ScreenCaptureProvider
	from ..extension_points.review_tracking import (
		reviewMove,
		browseModeMove,
		caretMove,
		coreCycle,
		navigatorObjectValueChange,
		TriggerReason,
	)

# Runtime imports using NVDA's addon module loading
else:
	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	DpTactileGraphicsBuffer = addon.loadModule(
		"brailleDisplayDrivers.dotPad.tactileBuffer",
	).DpTactileGraphicsBuffer
	review_tracking_extension_points = addon.loadModule("extension_points.review_tracking")
	reviewMove = review_tracking_extension_points.reviewMove
	browseModeMove = review_tracking_extension_points.browseModeMove
	caretMove = review_tracking_extension_points.caretMove
	coreCycle = review_tracking_extension_points.coreCycle
	navigatorObjectValueChange = review_tracking_extension_points.navigatorObjectValueChange


class PresentationRenderer(AutoPropertyObject):
	"""Coordinate presentation system for DotPad tactile display.

	This class coordinates the presentation system by:
	- Listening to review tracking events
	- Selecting appropriate presentations via PresentationManager
	- Rendering presentations once per coreCycle
	- Managing display I/O (queueing, threading)
	"""

	display: Display
	queuedWrite: list[int] | DpTactileGraphicsBuffer | None = None
	queuedWriteLock: threading.Lock
	forceRefresh: bool
	_presentationManager: PresentationManager
	_screenCaptureProvider: ScreenCaptureProvider
	_needsRender: bool

	def __init__(self, display: Display):
		"""Initialize the presentation renderer.

		:param display: The display to render to.
		"""
		self.display = display
		self.queuedWriteLock = threading.Lock()
		self.forceRefresh = False
		self._needsRender = False
		self._isTerminating = False

		# Initialize Presentation Manager - handles all presentation types
		self._initPresentationManager()

		# Subscribe to review tracking events
		reviewMove.register(self.onReviewMove)
		browseModeMove.register(self.onReviewMove)
		caretMove.register(self.onReviewMove)
		navigatorObjectValueChange.register(self.onReviewMove)
		coreCycle.register(self._handleCoreCycle)

		# Initial display
		self.initialDisplay()

	def terminate(self) -> None:
		"""Clean up event subscriptions and cascade to presentation manager."""
		# Set termination flag first to guard against concurrent event handling
		self._isTerminating = True

		# Unregister from events
		reviewMove.unregister(self.onReviewMove)
		navigatorObjectValueChange.unregister(self.onReviewMove)
		browseModeMove.unregister(self.onReviewMove)
		caretMove.unregister(self.onReviewMove)
		coreCycle.unregister(self._handleCoreCycle)

		# Cascade termination to presentation manager
		if self._presentationManager is not None:  # pyright: ignore[reportUnnecessaryComparison]
			self._presentationManager.terminate()
			self._presentationManager = None  # type: ignore[assignment]

		# Clear provider reference
		self._screenCaptureProvider = None  # type: ignore[assignment]

		# Clear queued write data
		with self.queuedWriteLock:
			self.queuedWrite = None

	def initialDisplay(self) -> None:
		"""Trigger initial display update."""
		try:
			self.onReviewMove()
		except Exception:
			log.debugWarning("Error in initial display", exc_info=True)

	def _initPresentationManager(self) -> None:
		"""Initialize the PresentationManager with providers.

		Providers are registered in priority order:
		1. ScreenCaptureProvider (highest priority - when toggled, wins)
		2. ChartProvider
		3. TableProvider
		4. BrailleProvider (fallback - always yields)
		"""
		# Import presentation modules at runtime using addon.loadModule
		# This works in both real NVDA and unit tests (via FakeAddon)
		addon_obj: addonHandler.Addon = cast(addonHandler.Addon, addonHandler.getCodeAddon())
		PresentationManager = addon_obj.loadModule("presentations.manager").PresentationManager
		ScreenCaptureProvider = addon_obj.loadModule("presentations.screenCapture").ScreenCaptureProvider
		ChartProvider = addon_obj.loadModule("presentations.chart").ChartProvider
		TableProvider = addon_obj.loadModule("presentations.table").TableProvider
		BrailleProvider = addon_obj.loadModule("presentations.braille").BrailleProvider

		# Create the presentation manager
		self._presentationManager = PresentationManager(self.display)

		# Create and store the screen capture provider for toggle access
		self._screenCaptureProvider = ScreenCaptureProvider()

		GraphicProvider = addon_obj.loadModule("presentations.graphic").GraphicProvider

		# Register providers in priority order (highest priority first)
		self._presentationManager.registerProvider(self._screenCaptureProvider, moveToStart=True)
		self._presentationManager.registerProvider(ChartProvider())
		self._presentationManager.registerProvider(TableProvider())
		self._presentationManager.registerProvider(GraphicProvider())
		# BrailleProvider creates its own presentation with buffer
		self._presentationManager.registerProvider(BrailleProvider())

	@property
	def presentationManager(self):
		"""Access the presentation manager."""
		return self._presentationManager

	@property
	def screenCaptureProvider(self):
		"""Access the screen capture provider."""
		return self._screenCaptureProvider

	def onReviewMove(self, triggerReason: TriggerReason | None = None) -> None:
		"""Handle navigation events by updating presentation selection.

		This method is called when the review cursor, browse mode, caret, or
		navigator object changes. It updates the PresentationManager to select
		the appropriate presentation but does not render (deferred to coreCycle).

		On ``"graphic" → other`` presentation transitions, invokes
		``previousPresentation.terminate()`` to clear the tactile area.
		Auto-entry and same-graphic re-renders are handled implicitly by
		``GraphicPresentation.render()`` running on the next coreCycle.

		:param triggerReason: The triggering event (e.g. ``TriggerReason.CARET_MOVE``),
			or ``None`` when no discrete navigation event applies (programmatic
			refresh, mode toggle, initial paint). Forwarded to the active
			presentation's ``isStillValid`` so it can react to specific event types.
		"""
		# Guard against calls during termination
		if self._isTerminating:
			return

		import api

		navObj = api.getNavigatorObject()

		# Store previous presentation for transition detection
		previousPresentation = self._presentationManager.activePresentation

		# Update the presentation manager - it will select the appropriate presentation
		self._presentationManager.update(navObj, triggerReason=triggerReason)

		# Transition detection. Each name may be ``None`` (no presentation
		# active before the update, or no provider matched after).
		activePresentation = self._presentationManager.activePresentation
		previousName = previousPresentation.name if previousPresentation else None
		activeName = activePresentation.name if activePresentation else None
		if previousName != activeName:
			# Presentation type changed - force refresh
			self.forceRefresh = True
			# Auto-exit: when leaving graphic mode, ask the outgoing
			# presentation to clear the tactile area. Wrapped so any
			# failure leaves the rendering flow intact.
			if previousName == "graphic" and previousPresentation is not None:
				try:
					previousPresentation.terminate()
				except Exception:
					log.exception("Graphic presentation terminate failed; continuing")

		# Mark that we need to render on next coreCycle
		self._needsRender = True

	def _handleCoreCycle(self) -> None:
		"""Handle core cycle event - render once per cycle.

		Calls optional handleCoreCycle() on active presentation, then renders
		if presentation changed or returned True.
		"""
		# Guard against calls during termination
		if self._isTerminating:
			return

		# Call handleCoreCycle() on active presentation
		needsRender = self._needsRender
		activePresentation = self._presentationManager.activePresentation
		if activePresentation is not None:
			presentationNeedsRender = activePresentation.handleCoreCycle()
			needsRender = needsRender or presentationNeedsRender

		# Render if needed and clear flag
		if needsRender:
			self._needsRender = False
			self.update()

	def update(self) -> None:
		"""Update the display with the current presentation's rendered content.

		Delegates to the PresentationManager to render the active presentation
		and sends the result to the display. If the active presentation
		returns ``None``, it has signalled that it manages the display
		directly (e.g. ``GraphicPresentation`` whose tactile output comes
		via TactileDisplayAPI's SimulateDisplay path) — skip the renderer's
		write entirely so we don't overwrite the presentation's content.
		"""
		# Use the presentation manager to render the active presentation
		buffer = self._presentationManager.render()

		if buffer is None:
			# Active presentation manages the display directly (currently
			# only GraphicPresentation does this). Nothing to write here.
			return

		# Non-braille presentation (tactile graphics buffer from screen capture, table, or chart)
		self._cells = buffer
		self._cursorPos = None  # No cursor for tactile graphics

		self._updateDisplay()

	def _updateDisplay(self) -> None:
		"""Send the current cells to the display.

		Determines whether to show the cursor based on the active presentation type.
		"""
		activePresentation = self._presentationManager.activePresentation
		# Only show cursor for braille presentations
		showCursor: bool = activePresentation is not None and activePresentation.name == "braille"
		self._displayWithCursor(showCursor=showCursor)

	def _displayWithCursor(self, showCursor: bool = True) -> None:
		if not self._cells:
			return

		cells: list[int] | DpTactileGraphicsBuffer
		if isinstance(self._cells, DpTactileGraphicsBuffer):  # type: ignore
			cells = self._cells
		else:
			cells = list(self._cells)
			if showCursor and self._cursorPos is not None:
				import config

				cells[self._cursorPos] |= config.conf["braille"]["cursorShapeReview"]  # type: ignore
			cells = self._normalizeCellArraySize(
				cells,
				self.display.numCells,
				self.display.numRows,
				self.display.numCells,
				self.display.numRows,
			)
		with self.queuedWriteLock:
			alreadyQueued = self.queuedWrite
			self.queuedWrite = cells
		# If a write was already queued, we don't need to queue another;
		# we just replace the data.
		# This means that if multiple writes occur while an earlier write
		# is still in progress,
		# we skip all but the last.
		if not alreadyQueued and not self.display.awaitingAck:
			# Queue a call to the background thread.
			self._writeCellsInBackground()

	def _writeCellsInBackground(self):
		"""Writes cells to a braille display in the background
		by queuing a function to the i/o thread."""
		import hwIo

		hwIo.bgThread.queueAsApc(self._bgThreadExecutor)

	def _bgThreadExecutor(self, _param: int):
		"""Executed as APC when cells have to be written to a display asynchronously."""
		if self.display.awaitingAck:
			# Do not write cells while awaiting ACK
			return
		with self.queuedWriteLock:
			data = self.queuedWrite
			self.queuedWrite = None
		if not data:
			return
		forceRefresh: bool = self.forceRefresh
		self.forceRefresh = False
		if isinstance(data, DpTactileGraphicsBuffer):
			self.display.display(data, forceRefresh)
		else:
			self.display.displayBraille(data, forceRefresh)
		# TODO: handle ACK timeouts  # noqa: FIX002

	def _normalizeCellArraySize(
		self,
		oldCells: list[int],
		oldCellCount: int,
		oldNumRows: int,
		newCellCount: int,
		newNumRows: int,
	) -> list[int]:
		"""
		Given a list of braille cells of length oldCell Count layed out in sequencial rows of oldNumRows,
		return a list of braille cells of length newCellCount layed out in sequencial rows of newNumRows,
		padding or truncating the rows and columns as necessary.
		"""
		oldNumCols = oldCellCount // oldNumRows
		newNumCols = newCellCount // newNumRows
		if len(oldCells) < oldCellCount:
			log.warning("Braille cells are shorter than the display size. Padding with blank cells.")
			oldCells.extend([0] * (oldCellCount - len(oldCells)))
		newCells = []
		if newCellCount != oldCellCount or newNumRows != oldNumRows:
			for rowIndex in range(newNumRows):
				if rowIndex < oldNumRows:
					start = rowIndex * oldNumCols
					rowLen = min(oldNumCols, newNumCols)
					end = start + rowLen
					row = oldCells[start:end]
					if rowLen < newNumCols:
						row.extend([0] * (newNumCols - rowLen))
				else:
					row = [0] * newNumCols
				newCells.extend(row)
		else:
			newCells = oldCells
		return newCells

	def scrollBack(self) -> None:
		"""Scroll the active presentation backward.

		Delegates to the PresentationManager which handles the appropriate
		scrolling behavior based on the active presentation type.
		Rendering is deferred to the next coreCycle.
		"""
		self._presentationManager.scrollBack()
		self._needsRender = True

	def scrollForward(self) -> None:
		"""Scroll the active presentation forward.

		Delegates to the PresentationManager which handles the appropriate
		scrolling behavior based on the active presentation type.
		Rendering is deferred to the next coreCycle.
		"""
		self._presentationManager.scrollForward()
		self._needsRender = True

	def setScreenCaptureMode(self, enabled: bool) -> None:
		"""Set Screen Capture Mode state.

		Delegates to the ScreenCaptureProvider to manage the enabled state.

		When enabling, clear any forced presentation first so Screen Capture takes
		precedence: ``PresentationManager.update`` reuses a forced presentation before
		consulting providers, and a forced library-bytes view (forced braille/graphic)
		is permanently valid — without this it would shadow the toggle and the library's
		autonomous braille would keep showing.
		"""
		if enabled:
			self._presentationManager.clearForced()
		self._screenCaptureProvider.setEnabled(enabled)
		self.onReviewMove()

	def toggleScreenCaptureMode(self) -> bool:
		"""Toggle Screen Capture Mode and return new state.

		Uses the ScreenCaptureProvider's toggle method. When the toggle turns Screen
		Capture on, clear any forced presentation first so it takes precedence (see
		``setScreenCaptureMode``).
		"""
		newState = self._screenCaptureProvider.toggle()
		if newState:
			self._presentationManager.clearForced()
		self.onReviewMove()
		return newState
