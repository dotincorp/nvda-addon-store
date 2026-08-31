# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Pythonic facade over the ITactileDisplayAPI COM interface.

This wrapper exposes camelCase Python methods that delegate to PascalCase COM
methods. Two backends are supported:

* **Bundled path** (default): loads the bundled ``TactileDisplayAPI.dll``
  via ``DllGetClassObject`` and returns a typed ``POINTER(ITactileDisplayAPI)``
  (vtable dispatch). comtypes handles BSTR allocation, HRESULT auto-raise, and
  refcount management.

* **System path** (opt-in via settings): obtains an ``IDispatch`` pointer from
  the system-registered COM server and wraps it in :class:`.DispatchProxy`.
  Method calls are resolved by name via ``IDispatch.GetIDsOfNames``, making
  them immune to future mid-vtable insertions by the vendor.

Threading-ownership: an instance of this class MUST be constructed and
destroyed on the LibraryWorker thread. Cross-thread access violates the
STA apartment invariant the worker maintains.
"""

from __future__ import annotations

import enum
from types import TracebackType
from typing import Any

from comtypes.automation import VARIANT

from .comInterface import BrailleInputOperation
from .comLoader import (
	createSystemTactileDisplayApi,
	createTactileDisplayApi,
	getBundledDllVersion,
	liblouisTablePathContext,
)
from .dispatchProxy import DispatchProxy


class DPConnectionPreference(enum.IntEnum):
	"""Device connection preference for Connect()."""

	AUTO = 0
	USB = 1
	BLUETOOTH = 2
	BOTH = 3


class DPFillKind(enum.IntEnum):
	"""Fill pattern for Fill()."""

	SOLID = 0
	DOTTED = 1
	HORIZONTAL_STRIPE = 2
	VERTICAL_STRIPE = 3


class TactileDisplayAPI:
	"""Pythonic facade over the ITactileDisplayAPI COM interface.

	Usage::

		with TactileDisplayAPI() as tda:
			tda.connect(DPConnectionPreference.AUTO)
			tda.drawLine(0, 0, 59, 39)
			tda.show()
			tda.disconnect()

	Threading: see module docstring.
	"""

	# Holds a typed POINTER(ITactileDisplayAPI) on the bundled path or a
	# DispatchProxy on the system path.  Both expose the same PascalCase COM
	# method names; _iface returns this as Any so callers need no per-line
	# type-ignore pragmas.
	_comObj: Any

	def __init__(self) -> None:
		self._comObj = None

	def _ensureInitialized(self) -> None:
		"""Lazily acquire the COM object on first use."""
		if self._comObj is not None:
			return
		try:
			from .. import configuration as _cfg

			useSystem = _cfg.getUseSystemLibrary(fromCache=True)
		except Exception:
			useSystem = False
		if useSystem:
			try:
				self._comObj = DispatchProxy(createSystemTactileDisplayApi())
				return
			except OSError:
				from logHandler import log as _log

				_log.warning(
					"dotPad: system TactileDisplayAPI not available; falling back to bundled DLL.",
					exc_info=True,
				)
		self._comObj = createTactileDisplayApi()

	@property
	def libraryDescription(self) -> str:
		"""Human-readable version/path string for log messages."""
		if isinstance(self._comObj, DispatchProxy):
			return "system (version unknown)"
		return f"{getBundledDllVersion()} (bundled)"

	@property
	def _iface(self) -> Any:
		"""Return the COM backend for method dispatch.

		On the bundled path this is a typed ``POINTER(ITactileDisplayAPI)``
		cast to ``Any`` (pyright can't follow comtypes' dynamic ``_methods_``
		generation). On the system path this is a ``DispatchProxy`` whose
		``__getattr__`` forwards to ``comtypes.client.dynamic``. Both expose
		the same PascalCase COM method names.
		"""
		assert self._comObj is not None
		return self._comObj

	def __enter__(self) -> "TactileDisplayAPI":
		self._ensureInitialized()
		return self

	def __exit__(
		self,
		exc_type: type[BaseException] | None,
		exc_val: BaseException | None,
		exc_tb: TracebackType | None,
	) -> None:
		self.close()

	def close(self) -> None:
		"""Drop the COM object reference.

		Best-effort ``Disconnect`` first. For the system path, calls
		``DispatchProxy.release()`` to drop the ``IDispatch`` reference.
		For the bundled path, clearing the typed pointer lets comtypes'
		refcount decrement on the next GC pass.
		"""
		if self._comObj is not None:
			try:
				self._iface.Disconnect()
			except Exception:
				pass
			if isinstance(self._comObj, DispatchProxy):
				self._comObj.release()
		self._comObj = None

	def __del__(self) -> None:
		try:
			self.close()
		except Exception:
			pass

	# --- Connection ---

	def connect(self, preference: DPConnectionPreference = DPConnectionPreference.AUTO) -> int:
		"""Connect to a DotPad device.

		Returns:
			0 on success, non-zero on failure (library-specific status code).
		"""
		return self._iface.Connect(int(preference))

	def disconnect(self) -> None:
		"""Disconnect from the DotPad device."""
		self._iface.Disconnect()

	def simulateDisplay(
		self,
		displayName: str,
		tactileDotsX: int,
		tactileDotsY: int,
		totalBrailleCellCount: int,
		lineCount: int,
		callbacks: Any,
	) -> None:
		"""Switch the library to caller-managed transport (v1.16).

		In SimulateDisplay mode the library does not connect to a device;
		instead it calls back into ``callbacks`` (an ``ITactileDisplayCallbacks``
		implementation) when content needs to be rendered. The caller is
		responsible for delivering the bytes to the actual device.

		Buffered-mode flush semantics carry over from the Connect
		path: the caller must explicitly call ``show()`` after a batch of
		draw operations to trigger the render callbacks.

		Args:
			displayName: Device model name used for keymap section lookup
				(e.g. ``"DotPad300A"``).
			tactileDotsX: Width of the graphic area in dots (not cells).
			tactileDotsY: Height of the graphic area in dots.
			totalBrailleCellCount: Number of cells in the dedicated braille
				text area (use 0 for graphics-only devices).
			lineCount: Number of rows in the braille text area (use 0 for
				graphics-only devices).
			callbacks: A ``TactileDisplayCallbacks`` instance from
				:mod:`callbackServer`. Cast to ``Any`` here because comtypes'
				COM-server objects are not strictly typed at the wrapper
				layer.
		"""
		if isinstance(self._comObj, DispatchProxy):
			# lazybind.Dispatch packs every argument into a VARIANT. VARIANT._set_value
			# cannot convert a Python COMObject server automatically; extract the typed
			# COM pointer from _com_pointers_ and cast to IUnknown (VT_UNKNOWN) so the
			# VARIANT setter can handle it. The library QIs for ITactileDisplayCallbacks.
			import ctypes as _ctypes

			from comtypes import IUnknown as _IUnknown

			from .comInterface import ITactileDisplayCallbacks as _ITC

			itcPtr = callbacks._com_pointers_.get(_ITC._iid_)  # type: ignore[attr-defined]
			if itcPtr is not None:
				callbacks = _ctypes.cast(itcPtr, _ctypes.POINTER(_IUnknown))
		self._iface.SimulateDisplay(
			displayName,
			tactileDotsX,
			tactileDotsY,
			totalBrailleCellCount,
			lineCount,
			callbacks,
		)

	def getDimensions(self) -> tuple[int, int]:
		"""Get the display dimensions in dots.

		Returns:
			Tuple of (width, height) in dots.
		"""
		# comtypes returns [out] params as a tuple.
		x, y = self._iface.GetDimensions()
		return x, y

	# --- Drawing primitives ---

	def drawLine(self, x1: int, y1: int, x2: int, y2: int) -> None:
		"""Draw a line from (x1,y1) to (x2,y2)."""
		self._iface.DrawLine(x1, y1, x2, y2)

	def drawBox(self, x: int, y: int, width: int, height: int) -> None:
		"""Draw a rectangle outline."""
		self._iface.DrawBox(x, y, width, height)

	def drawCircle(self, xCenter: int, yCenter: int, radius: int) -> None:
		"""Draw a circle."""
		self._iface.DrawCircle(xCenter, yCenter, radius)

	def drawPoly(
		self,
		xCenter: int,
		yCenter: int,
		radius: int,
		num_sides: int,
		startAngle: float = 0.0,
	) -> None:
		"""Draw a regular polygon."""
		self._iface.DrawPoly(xCenter, yCenter, radius, num_sides, startAngle)

	def fill(self, x: int, y: int, fillKind: DPFillKind = DPFillKind.SOLID) -> None:
		"""Flood-fill from an interior point."""
		self._iface.Fill(x, y, int(fillKind))

	def invertRect(self, x: int, y: int, width: int, height: int) -> None:
		"""Invert all dots in a rectangle."""
		self._iface.InvertRect(x, y, width, height)

	def drawBrailleLabel(self, x: int, y: int, brailleUnicode: str) -> None:
		"""Draw pre-translated braille Unicode characters at a position."""
		self._iface.DrawBrailleLabel(x, y, brailleUnicode)

	def drawTextLabel(self, x: int, y: int, text: str) -> None:
		"""Draw text auto-translated to braille via liblouis."""
		with liblouisTablePathContext():
			self._iface.DrawTextLabel(x, y, text)

	# --- Math graphing ---

	def graphMathEquation(
		self,
		expression: str,
		xMin: int = -10,
		xMax: int = 10,
		dotsPerTick: int = 5,
		showLabel: int = 1,
	) -> None:
		"""Graph a math equation on the display."""
		with liblouisTablePathContext():
			self._iface.GraphMathEquation(expression, xMin, xMax, dotsPerTick, showLabel)

	# --- Image display ---

	def drawImage(self, filename: str, aiParams: str = "", magnification: int = 1) -> None:
		"""Display a JPG/BMP image on the tactile display."""
		self._iface.DrawImage(filename, aiParams, magnification)

	def drawAsciiBrailleImage(self, filename: str) -> None:
		"""Display a .asc braille art file."""
		self._iface.DrawASCIIBrailleImage(filename)

	def drawScreenRegion(
		self,
		x: int,
		y: int,
		width: int,
		height: int,
		magnification: int = 1,
	) -> None:
		"""Capture and display a screen region."""
		self._iface.DrawScreenRegion(x, y, width, height, magnification)

	# --- Text display ---

	def showMultilineText(self, text: str) -> None:
		"""Display text wrapped across multiple braille lines."""
		with liblouisTablePathContext():
			self._iface.ShowMultilineText(text)

	def showStatusText(self, text: str) -> None:
		"""Display text on the 20-cell status display."""
		with liblouisTablePathContext():
			self._iface.ShowStatusText(text)

	# --- Display control ---

	def clear(self) -> None:
		"""Clear the display."""
		self._iface.Clear()

	def show(self) -> None:
		"""Flush the drawing buffer to the device.

		Returns S_FALSE (0x00000001, positive) when no device is connected;
		comtypes only auto-raises on negative HRESULT, so S_FALSE is harmless.
		"""
		self._iface.Show()

	def undoLastDraw(self) -> None:
		"""Undo the last drawing operation."""
		self._iface.UndoLastDraw()

	def setDrawingMode(self, immediate: bool) -> None:
		"""Set whether drawing commands are buffered or immediate."""
		self._iface.SetDrawingMode(1 if immediate else 0)

	def setBrailleLinePadding(self, padding: int) -> None:
		"""Set the line spacing on the tactile multi-line area (slot 12, v1.22).

		Args:
			padding: Vendor-defined integer; 0 = auto (default). Consult vendor
			         docs for the full enum (normal density / double spacing).
		"""
		self._iface.SetBrailleLinePadding(padding)

	def forceSixDotBraille(self, enable: bool) -> None:
		"""Force six-dot braille mode on the tactile multi-line area (slot 13, v1.22).

		When enabled the display uses 10 rows of 6-dot braille cells, sacrificing
		dot rows 7 and 8.  When disabled the display uses 8-dot cells (default).

		Args:
			enable: ``True`` to activate 6-dot mode, ``False`` to restore 8-dot.
		"""
		self._iface.ForceSixDotBraille(enable)

	def setHybridPrintAndBrailleMode(self, enable: bool) -> None:
		"""Enable or disable hybrid print+braille mode (slot 37, v1.0.21).

		When enabled, the library renders both print and braille simultaneously
		on the focused-control multi-line area. Must be called after
		``simulateDisplay()`` and ``setRegisterEvents(True)`` during driver
		initialisation. (Slot shifted from 35→37 by the v1.22 insertion.)

		Args:
			enable: ``True`` to activate hybrid mode, ``False`` to deactivate.
		"""
		self._iface.SetHybridPrintAndBrailleMode(enable)

	def showBrailleOnScreen(self, enable: bool) -> None:
		"""Toggle the library's on-screen viewer window (slot 34).

		comtypes marshals the Python bool to VARIANT_BOOL automatically.

		Note: the library's viewer mirrors what's being sent to the device via
		the legacy Connect transport. In our SimulateDisplay caller-managed
		transport, the library is a pure rendering engine and the viewer
		window may open with no content.
		"""
		self._iface.ShowBrailleOnScreen(enable)

	def setBrailleTables(
		self,
		literaryTable: str,
		mathTable: str,
		computerTable: str,
	) -> None:
		"""Set the braille translation tables.

		v1.11 takes three tables (the v1.05 form took two; v1.07 added the
		computer Braille parameter).

		Args:
			literaryTable: Bare filename of the literary table (e.g., ``en-us-g2.ctb``).
			mathTable: Bare filename of the math table (e.g., ``en-ueb-math.ctb``).
			computerTable: Bare filename of the computer Braille table
				(e.g., ``en-us-comp8.ctb``). If callers have no specific computer
				table, passing the literary table here is a safe fallback.
		"""
		with liblouisTablePathContext():
			self._iface.SetBrailleTables(literaryTable, mathTable, computerTable)

	def addFocusedControl(self) -> None:
		"""Tell the library to obtain the focused control via UIA/IAccessible2
		and render it on the multi-line area (slot 31).

		Per the v1.17 docs: "This method will obtain the focused object from
		UIA or IAccessible2/IAccessible and either show it as structured
		Braille similar to JAWS, or will, in the case of editable text, wrap
		text across the lines of the display." With ``RegisterEvents(True)``
		also active, the library automatically calls this when focus
		changes — but it needs an initial call to bootstrap with the
		control that was already focused before the subscription started.
		"""
		self._iface.AddFocusedControl()

	def updateCursor(self) -> None:
		"""Update the library's tracked caret location within the focused
		control's content (slot 32).

		Per the docs: "This method will retrieve the cursor location from the
		application and attempt to dynamically update it in the already
		displayed text." Mostly redundant when ``RegisterEvents(True)`` is
		active (the library subscribes to caret events) but available for
		callers that drive focus tracking manually.
		"""
		self._iface.UpdateCursor()

	def setRegisterEvents(self, enable: bool) -> None:
		"""Toggle the library's UIA/MSAA event subscription (slot 33).

		When enabled, the library autonomously subscribes to accessibility
		events and renders braille via the ``TactileDisplayUpdated`` /
		``BrailleDisplayUpdated`` callbacks — described in v1.09's changelog
		as "an automatic Braille engine for any screen reader". Used to let
		the library drive the multi-line braille content for the focused
		control when ``brailleSource = "library"``.

		Pass a Python ``bool`` so comtypes maps it to VARIANT_BOOL's
		canonical values (``True`` → -1 / VARIANT_TRUE, ``False`` → 0 /
		VARIANT_FALSE). Some COM servers treat any non-zero as True, but
		passing the canonical pattern avoids any ambiguity.

		Args:
			enable: ``True`` to register, ``False`` to unregister.
		"""
		self._iface.RegisterEvents(bool(enable))

	# --- Input operation dispatch (v1.16, SimulateDisplay-mode caller helper) ---

	def executeOperation(self, operation: BrailleInputOperation) -> None:
		"""Submit a viewport / cursor operation to the library (slot 37).

		The v1.17 library uses ``ExecuteOperation`` to drive its internal
		viewport state when the caller owns the transport (``SimulateDisplay``
		path). ``GraphicPresentation``'s pan / zoom ``@script`` handlers
		submit operations through here.

		Only the operation code is exposed by this overload — pan / zoom
		operations ignore the VARIANT argument, so we pass a default
		``VARIANT()``. Future operations that need an argument (e.g.,
		``RouteCursor`` with a cell index, ``TypeKey`` with a BSTR) can add
		a sibling overload without disturbing this one.

		Args:
			operation: A ``BrailleInputOperation`` enum member.
		"""
		self._iface.ExecuteOperation(int(operation), VARIANT())
