# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Graphic presentation provider for DotPad tactile display.

Detects ``Role.GRAPHIC`` objects (or any object via ``forceForObject``)
and renders them to the DotPad's tactile area.

Two render paths are available, selected per call by ``_useNvdaDrivenRender``:

- **Library-driven** (default): calls ``ExecuteOperation(
  SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE)`` so the library resolves what to
  render using its own UIA/MSAA cursor knowledge. Active when the NVDA
  navigator object and the system focus are the same object — i.e. the user
  is not exploring content independently of focus.
- **NVDA-driven** (fallback): reads the navigator object's screen bounding
  box and passes it to ``DrawScreenRegion + Show``. Active when the navigator
  object differs from focus — e.g. while the review cursor is moving through
  a browser virtual document, or when the user has explicitly routed the
  review cursor away from the focused element.

This presentation owns the full graphic-mode lifecycle via the three
``Presentation`` lifecycle methods: ``isStillValid`` for reuse-vs-recreate,
``render`` for content delivery, and ``terminate`` for cleanup on exit.

The library worker, wrapper, and callback server are constructed and owned
by ``BrailleDisplayDriver``. This presentation borrows them at every call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import addonHandler
import api
import braille
import controlTypes
import inputCore
from globalCommands import SCRCAT_BRAILLE
from logHandler import log
from NVDAObjects import NVDAObject
from scriptHandler import script

from ..utils.logOnce import warnFailureOnce
from .base import Presentation, PresentationProvider

if TYPE_CHECKING:
	from .. import configuration
	from ..brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver, Display
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from ..extension_points.review_tracking import TriggerReason
	from ..tactileDisplayAPI.comInterface import BrailleInputOperation
	from ..tactileDisplayAPI.libraryModes import LibraryModes

# Runtime import: cross-package addon module via NVDA's addon loader.
# Sibling-relative would need a parent-relative ``..`` which the addon
# import convention reserves for TYPE_CHECKING (NVDA doesn't load addon
# modules under a single ``addon`` namespace at runtime — see CLAUDE.md).
if not TYPE_CHECKING:
	_addon = addonHandler.getCodeAddon()
	BrailleInputOperation = _addon.loadModule("tactileDisplayAPI.comInterface").BrailleInputOperation
	TriggerReason = _addon.loadModule("extension_points.review_tracking").TriggerReason
	LibraryModes = _addon.loadModule("tactileDisplayAPI.libraryModes").LibraryModes
	configuration = _addon.loadModule("configuration")

addonHandler.initTranslation()


LIBRARY_DRAW_TIMEOUT_S: float = 1.0


def _libraryModesOf(driver: object) -> LibraryModes | None:
	"""What ``driver`` last heard from the library, if it is a Dot Pad that can say."""
	modes = getattr(driver, "libraryModes", None)
	return modes if isinstance(modes, LibraryModes) else None


def _getLibraryModes() -> LibraryModes | None:
	"""What the attached driver last heard from the library."""
	try:
		display = braille.handler.display  # type: ignore[union-attr]
	except Exception:
		return None
	return _libraryModesOf(display)


class GraphicPresentation(Presentation):
	"""Presentation for objects with graphic content.

	Owns the full graphic-mode lifecycle via the ``Presentation`` API:
	``isStillValid`` for reuse-vs-recreate, ``render`` for content,
	``terminate`` for cleanup. See module docstring for the design.
	"""

	@property
	def name(self) -> str:
		return "graphic"

	def __init__(self, obj: NVDAObject, display: Display) -> None:
		super().__init__()
		self._obj = obj
		self._display = display
		self._libraryModeActivated: bool = False
		self._requestedSerial: int | None = None
		"""The mode report serial current when our library operation finished, once it has."""

	def isStillValid(self, triggerReason: TriggerReason | None = None) -> bool:
		"""Whether graphic mode still applies to the navigator object.

		On the library-driven path (navigator is focus) the library decides when graphic
		mode ends, so once it has reported after our operation, that report is the answer.
		A library that cannot report keeps the old guess: it reverts to braille on a caret
		move.
		"""
		try:
			nav = api.getNavigatorObject()
			focus = api.getFocusObject()
			if self._obj != nav:
				return False
			if nav is not focus:
				return True
			modes = _libraryModesOf(self._getActiveDriver())
			if modes is None:
				return triggerReason != TriggerReason.CARET_MOVE
			if self._requestedSerial is None or modes.serial <= self._requestedSerial:
				# Nothing reported since the operation finished; the image may be about to appear.
				return True
			return modes.graphics
		except Exception:
			return False

	def _noteOperationFinished(self) -> None:
		"""Mark where mode reports start to describe our operation's result, and ask for one."""
		modes = _libraryModesOf(self._getActiveDriver())
		self._requestedSerial = modes.serial if modes is not None else 0
		driver = self._getActiveDriver()
		if driver is not None:
			driver.requestLibraryModeRefresh()

	def _useNvdaDrivenRender(self) -> bool:
		"""True when the NVDA-driven bounding-box path should be used for this render.

		Returns True when the navigator object is not the same Python object as
		the system focus — indicating the user is exploring content independently
		of focus (e.g. review cursor in a virtual document). In that case the
		library has no focus to follow autonomously, so the add-on supplies the
		screen coordinates explicitly.

		Returns True on any exception (safe fallback to NVDA-driven path).
		"""
		try:
			nav = api.getNavigatorObject()
			focus = api.getFocusObject()
			return nav is not focus
		except Exception:
			return True

	def render(self, display: Display) -> DpTactileGraphicsBuffer | None:
		"""Render graphic content to the tactile area.

		Dispatches to one of two paths based on ``_useNvdaDrivenRender``:

		- Library-driven: submits ``ExecuteOperation(
		  SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE)`` so the library resolves
		  what to render via UIA/MSAA. No screen coordinates required.
		- NVDA-driven: submits ``DrawScreenRegion + Show`` using the navigator
		  object's screen bounding box. Requires a valid non-zero location.

		Returns ``None`` in both cases — the library's ``TactileDisplayUpdated``
		callback is the sole writer to the display. Silent no-op when the driver
		or library is unavailable.
		"""
		driver = self._getActiveDriver()
		if driver is None or not getattr(driver, "_libraryReady", False):
			return None

		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			return None

		if self._useNvdaDrivenRender():
			location = getattr(self._obj, "location", None)
			if location is None or location.width <= 0 or location.height <= 0:
				return None

			def onShowFailure(exception: BaseException) -> None:
				warnFailureOnce("GraphicPresentation: show", exception)

			def onDrawSuccess(_result: object) -> None:
				worker.submitAndReport(
					tda.show,
					timeout=LIBRARY_DRAW_TIMEOUT_S,
					onSuccess=lambda _r: driver.requestLibraryModeRefresh(),
					onFailure=onShowFailure,
				)

			def onDrawFailure(exception: BaseException) -> None:
				warnFailureOnce("GraphicPresentation: drawScreenRegion", exception)

			worker.submitAndReport(
				tda.drawScreenRegion,
				int(location.left),
				int(location.top),
				int(location.width),
				int(location.height),
				timeout=LIBRARY_DRAW_TIMEOUT_S,
				onSuccess=onDrawSuccess,
				onFailure=onDrawFailure,
			)
		else:
			# Library-driven: trigger once to enter graphic mode; the library then
			# follows the cursor autonomously via setRegisterEvents, reverting to
			# braille on non-graphic cursor positions as intended.
			if not self._libraryModeActivated:
				self._libraryModeActivated = True

				def onLibraryFailure(exception: BaseException) -> None:
					log.warning(
						"GraphicPresentation: SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE failed: %r",
						exception,
					)
					# Otherwise the presentation waits for a result that is not coming, and stays.
					self._noteOperationFinished()

				worker.submitAndReport(
					tda.executeOperation,
					BrailleInputOperation.SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE,
					timeout=LIBRARY_DRAW_TIMEOUT_S,
					onSuccess=lambda _r: self._noteOperationFinished(),
					onFailure=onLibraryFailure,
				)
		return None

	def terminate(self) -> None:
		"""Clear the tactile area when leaving graphic mode. Best-effort silent no-op."""
		driver = self._getActiveDriver()
		if driver is None or not getattr(driver, "_libraryReady", False):
			return
		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			return
		modes = _libraryModesOf(self._getActiveDriver())
		if (
			self._requestedSerial is not None
			and modes is not None
			and modes.serial > self._requestedSerial
			and not modes.graphics
		):
			# The library left graphic mode by itself; clearing now would wipe what it drew next.
			return
		try:
			worker.submit(tda.clear)
		except Exception:
			log.exception("GraphicPresentation: clear submission raised; continuing")

	def scrollForward(self) -> bool:
		return False

	def scrollBack(self) -> bool:
		return False

	def _submitOperation(self, operation: BrailleInputOperation) -> None:
		"""Fire-and-forget ``ExecuteOperation`` submission for viewport pan/zoom scripts."""
		driver = self._getActiveDriver()
		if driver is None or not getattr(driver, "_libraryReady", False):
			return
		worker = driver._libraryWorker  # pyright: ignore[reportPrivateUsage]
		tda = driver._tda  # pyright: ignore[reportPrivateUsage]
		if worker is None or tda is None:
			return

		def onFailure(exc: BaseException) -> None:
			warnFailureOnce(f"GraphicPresentation: ExecuteOperation({operation!r})", exc)

		worker.submitAndReport(
			tda.executeOperation,
			operation,
			timeout=LIBRARY_DRAW_TIMEOUT_S,
			onSuccess=lambda _r: None,
			onFailure=onFailure,
		)

	# --- @script handlers ---
	#
	# Thin wrappers submitting viewport operations via ``_submitOperation``.
	# Routed here by ``BrailleDisplayDriver.getScript`` when this presentation
	# is active; driver gestures take over otherwise.
	#
	# Layout: single-key f1/f2/f3/f4 = page-step LEFT/UP/DOWN/RIGHT
	# (mnemonic for the hardware button layout). Small steps on
	# panLeft+f1 / panRight+f4 (left/right) and f1+f2 / f3+f4 (up/down).
	# longPress of a single key = jump to the corresponding edge
	# (HOME/TOP/BOTTOM/END). Zoom on f1+f4 (out) / f2+f3 (in). Recenter
	# on panLeft+panRight, which also takes over the driver's refresh on that
	# chord. Everything but the long presses matches the
	# [DotPad320X Keys] map the library ships, so TactileDisplayAPI, JAWS
	# and NVDA agree on one set of chords.

	@script(
		# Translators: description of the pan-left command on the tactile graphic.
		description=_("Pan the tactile graphic viewport left by one page-step"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f1",
	)
	def script_panViewportLeft(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_LEFT)

	@script(
		# Translators: description of the pan-up command on the tactile graphic.
		description=_("Pan the tactile graphic viewport up by one page-step"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f2",
	)
	def script_panViewportUp(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_UP)

	@script(
		# Translators: description of the pan-down command on the tactile graphic.
		description=_("Pan the tactile graphic viewport down by one page-step"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f3",
	)
	def script_panViewportDown(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_DOWN)

	@script(
		# Translators: description of the pan-right command on the tactile graphic.
		description=_("Pan the tactile graphic viewport right by one page-step"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f4",
	)
	def script_panViewportRight(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_RIGHT)

	@script(
		# Translators: description of the small pan-left command on the tactile graphic.
		description=_("Pan the tactile graphic viewport left by a few dots"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):panLeft+f1",
	)
	def script_panViewportLeftSmall(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_LEFT_SMALL)

	@script(
		# Translators: description of the small pan-up command on the tactile graphic.
		description=_("Pan the tactile graphic viewport up by a few dots"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f1+f2",
	)
	def script_panViewportUpSmall(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_UP_SMALL)

	@script(
		# Translators: description of the small pan-down command on the tactile graphic.
		description=_("Pan the tactile graphic viewport down by a few dots"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f3+f4",
	)
	def script_panViewportDownSmall(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_DOWN_SMALL)

	@script(
		# Translators: description of the small pan-right command on the tactile graphic.
		description=_("Pan the tactile graphic viewport right by a few dots"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):panRight+f4",
	)
	def script_panViewportRightSmall(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_RIGHT_SMALL)

	@script(
		# Translators: description of the jump-to-left-edge command on the tactile graphic.
		description=_("Jump the tactile graphic viewport to the left edge"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f1)",
	)
	def script_panViewportHome(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_HOME)

	@script(
		# Translators: description of the jump-to-top-edge command on the tactile graphic.
		description=_("Jump the tactile graphic viewport to the top edge"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f2)",
	)
	def script_panViewportTop(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_TOP)

	@script(
		# Translators: description of the jump-to-bottom-edge command on the tactile graphic.
		description=_("Jump the tactile graphic viewport to the bottom edge"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f3)",
	)
	def script_panViewportBottom(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_BOTTOM)

	@script(
		# Translators: description of the jump-to-right-edge command on the tactile graphic.
		description=_("Jump the tactile graphic viewport to the right edge"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f4)",
	)
	def script_panViewportEnd(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_END)

	@script(
		# Translators: description of the recenter command on the tactile graphic.
		description=_("Recenter the tactile graphic viewport and refresh the display"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):panLeft+panRight",
	)
	def script_panViewportCenter(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.PAN_VIEWPORT_CENTER)
		# The library exposes no viewport state, so we cannot tell whether the view was
		# already centered; refresh unconditionally. Not waiting for the recenter is safe:
		# a refresh leaves row.lastWritten alone, so the sender drops any queued refresh
		# packet for a row the recentered frame rewrites.
		driver = self._getActiveDriver()
		if driver is not None:
			driver.refreshDisplays()

	@script(
		# Translators: description of the zoom-in command on the tactile graphic.
		description=_("Zoom the tactile graphic in"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f2+f3",
	)
	def script_zoomViewportIn(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.ZOOM_VIEWPORT_IN)

	@script(
		# Translators: description of the zoom-out command on the tactile graphic.
		description=_("Zoom the tactile graphic out"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f1+f4",
	)
	def script_zoomViewportOut(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.ZOOM_VIEWPORT_OUT)

	@script(
		# Translators: description of the invert command on the tactile graphic.
		description=_("Invert the tactile graphic image (swap raised and blank dots)"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f1+f2+f3+f4",
	)
	def script_invertLastTactileImage(self, _gesture: inputCore.InputGesture) -> None:
		self._submitOperation(BrailleInputOperation.INVERT_LAST_TACTILE_IMAGE)

	def _getActiveDriver(self) -> BrailleDisplayDriver | None:
		"""Return the active BrailleDisplayDriver, or None if unavailable."""
		try:
			return cast("BrailleDisplayDriver | None", braille.handler.display)  # type: ignore[union-attr]
		except Exception:
			return None


class GraphicProvider(PresentationProvider):
	"""Provider that detects objects with graphic roles.

	Auto-detects ``Role.GRAPHIC`` objects with a valid screen location and
	creates a ``GraphicPresentation``. ``forceForObject`` accepts any
	object with a valid location (used by the manual force gesture).
	"""

	@property
	def name(self) -> str:
		return "graphic"

	def canProvide(self, obj: NVDAObject) -> bool:
		"""True when the object has the GRAPHIC role and a non-zero screen location."""
		if obj.role != controlTypes.Role.GRAPHIC:
			return False
		location = obj.location  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
		if location is None:
			return False
		width = cast(int, location.width)
		height = cast(int, location.height)
		return width > 0 and height > 0

	def _doCreatePresentation(self, obj: NVDAObject, display: Display) -> GraphicPresentation:
		"""Create a GraphicPresentation for the object."""
		return GraphicPresentation(obj, display)

	def forceForObject(
		self,
		obj: NVDAObject,
		display: Display,
	) -> GraphicPresentation | None:
		"""Force a GraphicPresentation for any object with a valid location."""
		location = obj.location  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
		if location is not None and location.width > 0 and location.height > 0:
			return GraphicPresentation(obj, display)
		return None


class HybridPrintPresentation(GraphicPresentation):
	"""The tactile area while the library draws hybrid print for the focused control.

	The library draws it unasked, so this draws nothing. What it takes from
	``GraphicPresentation`` is the rest: the pan and zoom bindings, library frames
	passing the byte gate, and those frames staying out of the braille replay.
	"""

	@property
	def name(self) -> str:
		# Not "graphic": leaving that clears the tactile area, and here the library keeps drawing.
		return "hybridPrint"

	def isStillValid(self, triggerReason: TriggerReason | None = None) -> bool:
		"""Always; whether the library still draws print is the provider's call, asked on every update."""
		return True

	def render(self, display: Display) -> DpTactileGraphicsBuffer | None:
		return None

	def terminate(self) -> None:
		"""Nothing to clear: the library draws whatever comes next."""

	@script(
		# Translators: description of the braille chord that does nothing in hybrid print mode.
		description=_("Does nothing: print stays in text fields while hybrid mode is on"),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f2+f4",
	)
	def script_suppressDismissal(self, _gesture: inputCore.InputGesture) -> None:
		# Unbound, the chord reaches the driver's dismissal, which switches the bindings to
		# braille while the library keeps drawing print.
		pass


class HybridPrintProvider(PresentationProvider):
	"""Claims the tactile area while the library reports drawing hybrid print.

	The library decides which controls get print, so nothing here looks at the object.
	Library-driven braille only: that is the one mode in which the library draws by itself.
	"""

	@property
	def name(self) -> str:
		return "hybridPrint"

	def canProvide(self, obj: NVDAObject) -> bool:
		if configuration.getBrailleSource(fromCache=True) != configuration.BrailleSource.LIBRARY:
			return False
		modes = _getLibraryModes()
		# The hybrid getter only reflects the setting; graphics mode is what says print is on the pins.
		return modes is not None and modes.hybrid and modes.graphics

	def _doCreatePresentation(self, obj: NVDAObject, display: Display) -> HybridPrintPresentation:
		return HybridPrintPresentation(obj, display)
