# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated, NV Access Limited

"""
Braille presentation for DotPad tactile display.

This module provides BraillePresentation and BrailleProvider for rendering
braille content to the tactile display.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

import config
from braille import Region
from logHandler import log
from tactile.braille import drawBrailleCells

from .base import Presentation, PresentationProvider

if TYPE_CHECKING:
	from NVDAObjects import NVDAObject

	from ..brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver, Display
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from ..configuration import BrailleSource
	from ..extension_points.review_tracking import TriggerReason
	from ..tactileDisplayAPI.comInterface import BrailleInputOperation

	def getBrailleSource(fromCache: bool = False) -> BrailleSource: ...


# Runtime imports using NVDA's addon module loading. Translation init for the
# fallback ui.message string lives here so the addon's gettext catalogue picks
# it up under test and at runtime alike.
if not TYPE_CHECKING:
	import addonHandler

	addonHandler.initTranslation()
	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	DpTactileGraphicsBuffer = addon.loadModule(
		"brailleDisplayDrivers.dotPad.tactileBuffer",
	).DpTactileGraphicsBuffer
	_configurationModule = addon.loadModule("configuration")
	BrailleSource = _configurationModule.BrailleSource
	getBrailleSource = _configurationModule.getBrailleSource
	BrailleInputOperation = addon.loadModule(
		"tactileDisplayAPI.comInterface",
	).BrailleInputOperation

# Used for the library-not-ready fallback notification. Lazily imported so unit
# tests can patch ``addon.presentations.braille.ui``.
import ui  # must follow the runtime-import block above


class BraillePresentation(Presentation):
	"""Presentation that renders braille content to the tactile display.

	This presentation owns a BrailleBuffer and manages all buffer lifecycle:
	regions, pending updates, and navigation changes.
	"""

	def __init__(self, display: Display):
		"""Initialize a braille presentation.

		:param display: The display to render to.
		"""
		super().__init__()
		# Imported at runtime so unit tests can patch it.
		from braille import BrailleBuffer

		self._buffer = BrailleBuffer(self)
		self._display = display
		self._regionsPendingUpdate: set[Region] = set()
		self._lastNavObj = None
		self._lastReviewPos = None

	# BrailleBuffer expects these properties on the handler
	@property
	def buffer(self):
		"""Return the internal braille buffer.

		NVDA's BrailleBuffer.updateDisplay() checks `self.handler.buffer` to determine
		if this buffer is the handler's current buffer. Required for scroll operations.
		"""
		return self._buffer

	@property
	def display(self):
		return self._display

	@property
	def displaySize(self) -> int:
		return self._display.numCells

	@property
	def displayDimensions(self):
		from braille import DisplayDimensions

		return DisplayDimensions(
			numRows=self._display.numRows,
			numCols=self._display.numCols,
		)

	def update(self) -> None:
		"""Handle buffer update request from BrailleBuffer.updateDisplay().

		NVDA's BrailleBuffer.updateDisplay() calls `self.handler.update()` when scrolling
		succeeds to refresh the display. Our driver's core pump handles rendering via
		`render()`, so this is a no-op.
		"""

	def handleCoreCycle(self) -> bool:
		"""Handle core cycle event - process pending buffer updates.

		Detects navigation changes and updates buffer accordingly.
		Returns True if buffer changed and needs rendering.

		:returns: True if buffer changed, False otherwise.
		"""
		import api
		from braille import getFocusRegions

		# Get current navigator state
		navObj = api.getNavigatorObject()
		reviewPos = api.getReviewPosition()

		# Detect if navigator changed to new object
		if self._lastNavObj != navObj:
			# New object - set up regions
			self._doNewObject(getFocusRegions(reviewPos.obj, review=True))  # type: ignore
			self._lastNavObj = navObj
			self._lastReviewPos = reviewPos
			return True  # Buffer changed, needs render

		# Same object - check if review position changed
		regions = cast("list[Region]", self._buffer.regions)
		region: Region | None = regions[-1] if regions else None
		regionObj = getattr(region, "obj", None)

		if region and regionObj == reviewPos.obj:
			# Mark region for update
			from braille import TextInfoRegion

			if isinstance(region, TextInfoRegion):
				region.pendingCaretUpdate = True
				self._regionsPendingUpdate.add(region)

		# Process pending updates
		if self._regionsPendingUpdate:
			return self._handlePendingUpdate()

		return False  # No changes

	def _doNewObject(self, regions: Iterable[Region]) -> None:
		"""Set up buffer for a new object.

		Clears the buffer and populates it with regions for the new object.

		:param regions: List of Region objects for the new object.
		"""
		self._buffer.clear()
		region: Region | None = None
		for region in regions:
			self._buffer.regions.append(region)
		self._buffer.update()
		if region:
			self._buffer.focus(region)
			self._scrollToCursorOrSelection(region)

	def _handlePendingUpdate(self) -> bool:
		"""Handle pending region updates.

		Processes pending region updates and scrolls to cursor if needed.

		:returns: True if updates were processed, False otherwise.
		"""
		from braille import TextInfoRegion
		from logHandler import log
		from treeInterceptorHandler import TreeInterceptor

		if not self._regionsPendingUpdate:
			return False

		try:
			scrollTo: TextInfoRegion | None = None
			self._buffer.saveWindow()
			for region in self._regionsPendingUpdate:
				if isinstance(region.obj, TreeInterceptor) and not region.obj.isAlive:  # type: ignore
					continue
				try:
					region.update()
				except Exception:
					log.debugWarning(
						f"Region update failed for {region}, object probably died",
						exc_info=True,
					)
					continue
				if isinstance(region, TextInfoRegion) and region.pendingCaretUpdate:
					scrollTo = region
					region.pendingCaretUpdate = False
			self._buffer.update()
			self._buffer.restoreWindow()
			if scrollTo is not None:
				self._scrollToCursorOrSelection(scrollTo)
			return True
		finally:
			self._regionsPendingUpdate.clear()

	def _scrollToCursorOrSelection(self, region: Region) -> None:
		"""Scroll buffer to cursor or selection.

		:param region: The region to scroll to.
		"""
		from braille import TextInfoRegion

		if region.brailleCursorPos is not None:
			self._buffer.scrollTo(region, region.brailleCursorPos)
		elif not isinstance(region, TextInfoRegion) or not region.obj.isTextSelectionAnchoredAtStart:
			# It is unknown where the selection is anchored,
			# or it is anchored at the end.
			if region.brailleSelectionStart is not None:
				self._buffer.scrollTo(region, region.brailleSelectionStart)
			elif region.brailleSelectionEnd is not None:
				# The selection is anchored at the start.
				self._buffer.scrollTo(region, region.brailleSelectionEnd - 1)

	def render(self, display: Display) -> DpTactileGraphicsBuffer:
		"""Render braille cells to a tactile graphics buffer.

		Converts the braille cells from the internal buffer to a tactile
		graphics format and optionally renders the cursor.

		:param display: The display to render to.
		:returns: A tactile graphics buffer containing the rendered braille.
		"""
		buffer = DpTactileGraphicsBuffer(display.physicalNumCols, display.physicalNumRows)

		# Get braille cells from internal buffer
		cells = self._buffer.windowBrailleCells  # type: ignore

		# Use Display to format cells with proper row splitting
		display.drawBrailleCells(buffer, cells)

		# Draw cursor if present
		cursorPos = self._buffer.cursorWindowPos  # type: ignore
		if cursorPos is not None:
			self._drawCursor(buffer, cursorPos, display)

		return buffer

	def _drawCursor(self, buffer: DpTactileGraphicsBuffer, cursorPos: int, display: Display) -> None:
		"""Draw the cursor at the specified position.

		The cursor is rendered by OR-ing the cursor shape with the braille cell
		at the cursor position.

		:param buffer: The tactile graphics buffer to draw on.
		:param cursorPos: The window position of the cursor.
		:param display: The display being rendered to.
		"""
		# Get the cursor shape from NVDA config
		cursorShape: int = config.conf["braille"]["cursorShapeReview"]  # type: ignore

		# Use Display to calculate correct position
		x, y = display.getBrailleCellPosition(cursorPos)

		# Draw the cursor shape as braille dots
		drawBrailleCells(buffer, x, y, [cursorShape])

	def scrollForward(self) -> bool:
		"""Scroll the braille buffer forward.

		:returns: True (braille can always attempt to scroll).
		"""
		self._buffer.scrollForward()
		return True

	def scrollBack(self) -> bool:
		"""Scroll the braille buffer back.

		:returns: True (braille can always attempt to scroll).
		"""
		self._buffer.scrollBack()
		return True

	def terminate(self) -> None:
		"""Clean up resources held by this presentation.

		Clears the braille buffer and releases references to NVDA objects.
		"""
		if self._buffer:
			self._buffer.clear()
		self._regionsPendingUpdate.clear()
		self._lastNavObj = None
		self._lastReviewPos = None

	def isStillValid(self, triggerReason: TriggerReason | None = None) -> bool:
		"""Invalidate when the user has switched to library-driven source.

		``PresentationManager.update()`` re-picks via providers when this
		returns ``False``, so a config change applied via the settings
		panel takes effect on the next focus / review event instead of
		requiring a full NVDA restart.
		"""
		try:
			return getBrailleSource() == BrailleSource.NVDA
		except Exception:
			# Defensive — never block the manager's update loop on a config
			# read failure. Stay valid; the next cycle will retry.
			log.debug("BraillePresentation: getBrailleSource raised", exc_info=True)
			return True

	@property
	def name(self) -> str:
		return "braille"


def _getActiveDotPadDriver() -> BrailleDisplayDriver | None:
	"""Return the currently-attached DotPad ``BrailleDisplayDriver``, or ``None``.

	Reads ``braille.handler.display``. Returns ``None`` when (a) NVDA's
	braille handler is absent (rare; mostly during shutdown), (b) no
	display is attached, or (c) the attached display is not the addon's
	driver (e.g., the user picked a different braille display). Module-
	level so unit tests can patch it directly via
	``patch("addon.presentations.braille._getActiveDotPadDriver", ...)``.
	"""
	try:
		import braille

		display = braille.handler.display  # type: ignore[union-attr]
	except Exception:
		return None
	if display is None:
		return None
	# Only the DotPad driver carries ``_libraryReady`` etc. — defensive
	# duck-typing avoids importing the driver module from here.
	if not hasattr(display, "_libraryReady"):
		return None
	return cast("BrailleDisplayDriver", display)


class LibraryBraillePresentation(Presentation):
	"""Library-driven multi-line braille.

	Near-passive marker — ``render()`` returns ``None`` so the renderer
	skips its own write; the library autonomously emits braille bytes via
	``TactileDisplayUpdated`` (consumed by
	``simulatedDisplay.renderTactileBytes``, which writes them through to
	the multi-line area when this presentation is active).

	Its job is to (a) let the byte gate know library bytes should pass
	through (the gate's ``isinstance`` check picks this class up),
	(b) forward F1/F4 scrolling intent via
	``ExecuteOperation(PAN_VIEWPORT_UP/DOWN)``, and (c) clear the
	library's display state on teardown.
	"""

	def __init__(self, display: Display) -> None:
		"""Initialize a library-driven braille presentation.

		Submits ``AddFocusedControl()`` to the library worker on
		construction so the library renders the currently-focused control
		immediately. ``RegisterEvents(True)`` (configured at driver init)
		only catches FUTURE events — without an initial kick-start the
		library has no state for the control that was already focused
		when the presentation was first activated, and emits zero-content
		frames until the user moves focus to something else.

		:param display: The display to render to. Stored for future use; the
			library writes the multi-line area autonomously so we don't need
			it for any active rendering path today.
		"""
		super().__init__()
		self._display = display
		# Bootstrap the library with the current focused control. Same
		# defensive shape as scrollBack — silent no-op when the driver
		# / library aren't available.
		self._bootstrapFocusedControl()

	def _bootstrapFocusedControl(self) -> None:
		"""Force text mode, then enable UIA events.

		Bootstrap:

		1. ``ExecuteOperation(SHOW_OBJECT_AT_CURSOR_AS_BRAILLE)`` switches
		   the library out of graphics mode (the docs document op 18 as
		   "switch back to text mode from graphics mode"). After
		   ``SimulateDisplay`` init the library's default mode isn't
		   documented; this call guarantees we're in text mode before
		   asking for content. Its name also implies it renders the object
		   at the cursor, so it may double as the initial-focus kick-start.

		Then ``RegisterEvents(True)`` is enabled (step 2 below).

		This call blocks, so it MUST run with events OFF — events live during a
		blocking call starve the STA pump and heap-corrupt the library.
		``submit`` is FIFO, so enabling events afterward guarantees they only go
		on once it has drained.

		Two earlier bootstrap calls were dropped after hardware testing showed
		the text-mode switch alone renders the initial focus: a
		``ShowMultilineText`` "warm-up" (a workaround for zero-content frames in
		an older library version) and an explicit ``AddFocusedControl()``
		kick-start. If a future library version leaves the initial focus blank
		until the user moves focus, an ``AddFocusedControl()`` submit — placed
		here, BEFORE ``enableLibraryUiaEvents`` so it runs events-off — restores it.
		"""
		driver = self._getActiveDriver()
		if driver is None or not getattr(driver, "_libraryReady", False):
			return
		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			return

		def onSwitchSuccess(_result: object) -> None:
			log.debug("LibraryBraillePresentation: text-mode switch succeeded")

		def onSwitchFailure(exc: BaseException) -> None:
			log.warning(f"LibraryBraillePresentation: text-mode switch failed: {exc!r}")

		# Step 1: switch the library to text mode. Op 18 per the v1.16 docs.
		worker.submitAndReport(
			tda.executeOperation,
			BrailleInputOperation.SHOW_OBJECT_AT_CURSOR_AS_BRAILLE,
			timeout=1.0,
			onSuccess=onSwitchSuccess,
			onFailure=onSwitchFailure,
		)
		# Step 2: NOW enable the library's autonomous UIA subscription, AFTER the
		# blocking bootstrap above. Enabling it earlier (e.g. at driver init)
		# meant UIA events were live during the blocking ExecuteOperation, which
		# starves the STA pump and heap-corrupts the library. submit() is FIFO,
		# so this runs only once step 1 has drained. From here the library
		# renders braille autonomously via TactileDisplayUpdated; terminate()
		# turns events back off.
		driver.enableLibraryUiaEvents()
		log.debug(
			"LibraryBraillePresentation: bootstrap submitted (text-mode switch + enable UIA events)",
		)

	@property
	def name(self) -> str:
		return "libraryBraille"

	def isStillValid(self, triggerReason: TriggerReason | None = None) -> bool:
		"""Invalidate when the user has switched back to NVDA source or
		when the library becomes unavailable.

		``PresentationManager.update()`` re-picks via providers when this
		returns ``False``, so a config change applied via the settings
		panel takes effect on the next focus / review event without
		requiring a full NVDA restart. Also invalidates when the library
		singleton has gone unhealthy mid-session — that path falls back
		to ``BraillePresentation`` via the provider's library-not-ready
		branch.
		"""
		try:
			if getBrailleSource() != BrailleSource.LIBRARY:
				return False
		except Exception:
			log.debug("LibraryBraillePresentation: getBrailleSource raised", exc_info=True)
			return True  # stay valid; retry next cycle
		driver = _getActiveDotPadDriver()
		return driver is not None and bool(getattr(driver, "_libraryReady", False))

	def render(self, display: Display) -> DpTactileGraphicsBuffer | None:
		"""No-op render — the library writes the multi-line area autonomously.

		Returning ``None`` tells ``PresentationRenderer.update()`` to skip
		its own write to ``graphicDisplay``; the library's
		``TactileDisplayUpdated`` callback path is the single writer.
		"""
		return None

	def scrollBack(self) -> bool:
		"""Pan the library's viewport up by one display height (F1)."""
		return self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_UP)

	def scrollForward(self) -> bool:
		"""Pan the library's viewport down by one display height (F4)."""
		return self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_DOWN)

	def terminate(self) -> None:
		"""Submit ``Clear()`` on the worker to wipe the library's content.

		Best-effort — silent no-op when the driver / library aren't
		available. Mirrors ``GraphicPresentation.terminate``'s shape.
		"""
		driver = self._getActiveDriver()
		if driver is None or not getattr(driver, "_libraryReady", False):
			return
		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			return
		try:
			# Turn the autonomous UIA subscription OFF first, so any later
			# explicit blocking ExecuteOperation (graphics pan/zoom, the next
			# braille bootstrap) runs events-off. FIFO: this precedes clear().
			driver.disableLibraryUiaEvents()
			worker.submit(tda.clear)
		except Exception:
			log.exception("LibraryBraillePresentation: clear submission raised; continuing")

	def _submitOperation(self, operation: BrailleInputOperation) -> bool:
		"""Submit ``ExecuteOperation(<op>)`` on the driver's worker.

		Returns ``True`` if submission was attempted, ``False`` for the
		defensive no-op path (driver absent / library not ready /
		worker / wrapper missing). Same shape as
		``GraphicPresentation._submitOperation``.
		"""
		driver = self._getActiveDriver()
		if driver is None or not getattr(driver, "_libraryReady", False):
			return False
		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			return False

		def onFailure(exc: BaseException) -> None:
			log.warning(
				f"LibraryBraillePresentation: ExecuteOperation({operation!r}) failed: {exc!r}",
			)

		worker.submitAndReport(
			tda.executeOperation,
			operation,
			timeout=1.0,
			onSuccess=lambda _r: None,
			onFailure=onFailure,
		)
		return True

	def _getActiveDriver(self) -> BrailleDisplayDriver | None:
		"""Wrap the module-level lookup so tests can patch this method too."""
		return _getActiveDotPadDriver()


class BrailleProvider(PresentationProvider):
	"""Provider that creates braille presentations.

	The fallback provider — always yields a presentation since braille is
	always available. The concrete subclass is chosen at construction time
	by reading the live ``brailleSource`` config value:

	- ``BrailleSource.NVDA`` → ``BraillePresentation`` (NVDA-driven, the
	  existing behaviour).
	- ``BrailleSource.LIBRARY`` → ``LibraryBraillePresentation`` (library-
	  driven via ``RegisterEvents(true)``).

	When ``LIBRARY`` is selected but the driver's library isn't ready
	(``_libraryReady = False``, no graphic display, etc.), the provider
	falls back to ``BraillePresentation`` and surfaces a one-time
	``ui.message`` per driver lifetime so the user knows their preferred
	mode wasn't honoured.

	No instance caching: each ``_doCreatePresentation`` call constructs a
	fresh presentation, so a config swap takes effect on the next
	presentation construction without bookkeeping overhead.
	"""

	@property
	def name(self) -> str:
		return "braille"

	def canProvide(self, obj: NVDAObject) -> bool:
		"""Braille is always available as the fallback provider."""
		return True

	def _doCreatePresentation(self, obj: NVDAObject, display: Display) -> Presentation:
		"""Construct the braille presentation for the requested source."""
		source = getBrailleSource()
		if source == BrailleSource.NVDA:
			return BraillePresentation(display)
		# source == BrailleSource.LIBRARY
		driver = _getActiveDotPadDriver()
		reason = _libraryUnavailableReason(driver)
		if reason is None:
			return LibraryBraillePresentation(display)
		if getattr(driver, "_librarySetupPending", False):
			# The driver is still in __init__ and the library has not finished starting.
			# Render NVDA-driven for now -- the next update picks up the library -- but
			# say nothing: this is startup ordering, not a failure. Only observable when
			# the driver is constructed off the main thread, i.e. on automatic detection.
			log.debug("BrailleProvider: library still starting; rendering NVDA-driven for now")
			return BraillePresentation(display)
		# Library mode requested but unavailable — fall back to NVDA-driven
		# rendering and announce once per driver lifetime.
		self._announceFallbackOnce(driver, reason)
		return BraillePresentation(display)

	def forceForObject(
		self,
		obj: NVDAObject,
		display: Display,
	) -> Presentation | None:
		"""Force-construct the braille presentation; same branching as
		``_doCreatePresentation``."""
		return self._doCreatePresentation(obj, display)

	def terminate(self) -> None:
		"""No cached state to clean up."""
		return

	def _announceFallbackOnce(self, driver: Any, reason: str) -> None:
		"""Log + announce the library-unavailable fallback at most once per
		driver lifetime.

		The "announced" flag lives on the driver instance so it resets
		naturally when the driver is reattached. With no driver attached
		(``driver is None``) the announcement is suppressed — without a
		stable per-driver context the one-time guarantee can't bind.

		The flag is set BEFORE invoking ``ui.message`` so a failure inside
		``ui.message`` doesn't cause us to keep retrying (which would
		spam the log on every subsequent presentation creation). The
		message itself is dispatched via ``wx.CallAfter`` because the
		fallback path runs from various threads (HwIO ioThread, main
		thread, etc.) and ``ui.message`` schedules a wx timer that
		requires the main thread.
		"""
		# Suppress repeat warnings / announcements within the same driver
		# lifetime — early-return BEFORE any side-effects so a flood of
		# `_doCreatePresentation` calls doesn't spam the log.
		if driver is not None and getattr(driver, "_libraryFallbackAnnounced", False):
			return
		log.warning(
			f"BrailleProvider: library mode requested but unavailable ({reason}); "
			"falling back to NVDA-driven braille presentation",
		)
		if driver is None:
			return
		# Set the flag now so we don't keep retrying if the dispatch fails.
		driver._libraryFallbackAnnounced = True  # pyright: ignore[reportPrivateUsage]
		try:
			# Dispatch to the main thread — ``ui.message`` uses a wx timer
			# which asserts ``wxThread::IsMain()``. ``wx.CallAfter`` is the
			# standard NVDA pattern for cross-thread UI dispatch.
			import wx

			wx.CallAfter(
				ui.message,
				# Translators: announced once when the user selects library-driven
				# braille but the library isn't available for the current device.
				_("DotPad library-driven braille unavailable; falling back to NVDA review mode"),
			)
		except Exception:
			log.exception("BrailleProvider: ui.message dispatch failed; continuing")


def _libraryUnavailableReason(driver: Any) -> str | None:
	"""Return ``None`` if the library is ready, otherwise a short reason string."""
	if driver is None:
		return "no DotPad driver attached"
	if not getattr(driver, "_libraryReady", False):
		return "_libraryReady is False"
	if getattr(driver, "graphicDisplay", None) is None:
		return "driver has no graphic display"
	return None
