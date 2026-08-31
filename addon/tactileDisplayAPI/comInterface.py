# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""comtypes interface declaration for ITactileDisplayAPI (v1.34).

This file is the single source of truth for the library's vtable layout.
The interface was renamed ``ITactileDisplayImpl`` in the v1.22 typelib but
the IID is unchanged; our hand-declared class keeps the original name for
continuity.

The runtime class ``ITactileDisplayAPI`` is a comtypes IDispatch subclass.
It inherits IUnknown (slots 0-2) and IDispatch (slots 3-6) from comtypes,
so the ``_methods_`` list starts at vtable slot 7 (the first library-
specific method, ``Connect``).

v1.23 → v1.34 vtable change
-----------------------------
None. ``validateComVtable.py --check`` reports both interfaces IN SYNC
against the v1.0.34 typelib: ``ITactileDisplayAPI`` still has 33 methods
(slots 7-39) and ``ITactileDisplayCallbacks`` still has 3. The eleven
intervening vendor releases were behaviour and rendering fixes only.

v1.21 → v1.22/v1.23 vtable change
-----------------------------------
Two new methods inserted mid-vtable at slots 12-13:
``SetBrailleLinePadding(padding: c_long)`` and
``ForceSixDotBraille(flag: VARIANT_BOOL)``. Every slot from 12 onwards
shifts +2; ``SetHybridPrintAndBrailleMode`` moves from slot 35 to slot 37.
Total: 33 methods.

v1.20 → v1.21 vtable change
------------------------------
``ITactileDisplayAPI`` gains one new method inserted mid-vtable at slot 35:
``SetHybridPrintAndBrailleMode(flag: VARIANT_BOOL)``. The insertion shifts
the previously-slot-35 ``EnableContractedBrailleInput`` to slot 36, and
the previously-slot-36 ``ExecuteOperation`` to slot 37. Total: 31 methods.

``ITactileDisplayCallbacks`` is unchanged in v1.0.21 — 3 methods, slots
7-9. ``callbackServer.py`` requires no changes.

v1.17 → v1.20 vtable
----------------------
``ITactileDisplayAPI`` itself is binary-identical between v1.17 and
v1.20 — the 30-method layout from v1.17 stands.

``ITactileDisplayCallbacks`` has 3 methods as of v1.18:
``TactileDisplayUpdated`` (v1.16), ``BrailleDisplayUpdated`` (v1.16),
and ``GetTranslation`` (v1.18). The published typelib of v1.20
exposes only the first two, but the library's actual binary expects
a 3-method vtable on the COMObject — ``AddFocusedControl`` AVs unless
the third method is both declared and implemented with a working
translation (hardware-confirmed on v1.20). ``callbackServer.py``
implements it against NVDA's ``louisHelper.translate`` so the library
gets the user's currently-configured braille table.

The trailing ``cursorOffset`` parameter is ``[in]int*`` (a pointer to
int) per the vendor IDL, not ``[in]int`` by value. On x64 the calling
convention difference is 8 vs 4 bytes; declaring this as ``c_long``
shifts register reads and corrupts the stack frame. Use
``POINTER(c_long)``.

v1.16 → v1.17 vtable change (kept for context)
----------------------------------------------
v1.17 inserted ``DisplayLiteraryBraille`` at vtable slot 11, between
``SetBrailleTables`` (slot 10) and what was ``SetDrawingMode`` in v1.16
(slot 11, now slot 12). Every v1.16 slot from 11 onwards shifts +1,
ending at ``ExecuteOperation`` slot 36 (was slot 35). The slot is
declared for vtable correctness; ``wrapper.py`` does not expose it
and the addon does not call it.

``DisplayLiteraryBraille(flag: c_int)`` controls whether non-math text
uses literary Braille (``flag=1``) or computer Braille (``flag=0``).
The library toggles literary Braille on automatically when contracted-
Braille input is enabled, and toggles input off when literary display
is turned off (the two are inextricably linked vendor-side). v1.18
also exposes the default as the ``[Liblouis]DisplayLiteraryBraille``
ini key (=1).

v1.15 → v1.16 vtable change (kept for context)
----------------------------------------------
v1.16 inserted ``SimulateDisplay`` at vtable slot 8. We declare it for
vtable correctness; ``wrapper.py`` exposes it.

Threading-ownership: an instance of this interface is owned by the
``LibraryWorker``. All method calls happen on that worker thread inside
its STA COM apartment. Refcounting is automatic via comtypes'
``_compointer_base.__del__``.

Why hand-declared rather than typelib-generated: the IID-candidate
iteration requires the typed pointer to be IID-agnostic at the wrapping
layer. A typelib-generated stub would lock to one IID; the hand-declared
class uses ``_iid_`` purely as metadata.

Method-signature mistakes here surface as comtypes-level errors at class
construction or first call — NOT as the stack-corrupting access violations
that manual ``WINFUNCTYPE`` prototypes produced in the previous wrapper.
"""

from __future__ import annotations

from ctypes import POINTER, c_double, c_int, c_long, c_ubyte
from ctypes.wintypes import VARIANT_BOOL
from enum import IntEnum

# IDispatch lives in comtypes.automation (not top-level comtypes); the
# automation submodule is imported eagerly so this is safe at any time.
# COMMETHOD's argspec is variadic and partially typed; pyright flags the
# call signature even though the runtime contract is solid. One ignore at
# the import site covers all COMMETHOD calls below.
from comtypes import BSTR, COMMETHOD, GUID, HRESULT, IUnknown  # pyright: ignore[reportUnknownVariableType]
from comtypes.automation import VARIANT, IDispatch


class BrailleInputOperation(IntEnum):
	"""Operation codes for ``ITactileDisplayAPI.ExecuteOperation`` (slot 39).

	Values mirror the ``_BrailleInputOperation`` IntFlag exposed by the v1.23
	typelib. The library uses these to drive the ``SimulateDisplay``-mode
	viewport — pan, zoom, route, and (for tactile keyboards) keyboard
	emulation. The pan/zoom subset is wired to ``GraphicPresentation``
	``@script`` handlers; the remaining members are declared for completeness.

	Note: v1.23 inserted ``INVERT_LAST_TACTILE_IMAGE = 20`` between
	``SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE`` and ``ROUTE_CURSOR``, shifting
	all subsequent codes up by one relative to v1.17.
	"""

	NONE = 0
	PAN_LEFT = 1
	PAN_RIGHT = 2
	PAN_VIEWPORT_LEFT = 3
	PAN_VIEWPORT_LEFT_SMALL = 4
	PAN_VIEWPORT_RIGHT = 5
	PAN_VIEWPORT_RIGHT_SMALL = 6
	PAN_VIEWPORT_UP = 7
	PAN_VIEWPORT_UP_SMALL = 8
	PAN_VIEWPORT_DOWN = 9
	PAN_VIEWPORT_DOWN_SMALL = 10
	PAN_VIEWPORT_HOME = 11
	PAN_VIEWPORT_END = 12
	PAN_VIEWPORT_TOP = 13
	PAN_VIEWPORT_BOTTOM = 14
	PAN_VIEWPORT_CENTER = 15
	ZOOM_VIEWPORT_OUT = 16
	ZOOM_VIEWPORT_IN = 17
	SHOW_OBJECT_AT_CURSOR_AS_BRAILLE = 18
	SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE = 19
	INVERT_LAST_TACTILE_IMAGE = 20
	ROUTE_CURSOR = 21
	TYPE_KEY = 22
	UP_ARROW = 23
	DOWN_ARROW = 24
	LEFT_ARROW = 25
	RIGHT_ARROW = 26
	PRIOR_WORD = 27
	NEXT_WORD = 28
	HOME = 29
	END = 30
	TOP_OF_DOCUMENT = 31
	BOTTOM_OF_DOCUMENT = 32
	ENTER_KEY = 33
	ESCAPE_KEY = 34
	BACKSPACE_KEY = 35


# Set to the legacy IID for documentation. The runtime QueryInterface uses
# an explicit IID from comLoader.IID_CANDIDATES, not this attribute. Keeping
# the metadata aligned with the first candidate prevents surprise should
# anyone read the class definition.
_IID_LEGACY = GUID("{48FB9EFA-4F20-4086-8A15-5CE3CF0CC2E3}")

# IID for ITactileDisplayCallbacks. Unchanged across v1.16/v1.17/v1.18/v1.20
# even though v1.18 appended ``GetTranslation`` to the vtable — the vendor
# kept the IID stable. The v1.20 typelib still only declares the first two
# methods, but the binary requires a 3-method vtable (hardware-confirmed:
# AddFocusedControl AVs without it). This interface is implemented by callers,
# not by the library;
# it appears here because SimulateDisplay's 6th argument is a
# ``POINTER(ITactileDisplayCallbacks)`` and ``callbackServer.py`` exposes a
# COMObject server bound to this IID.
_IID_CALLBACKS = GUID("{26E7E209-71A0-4C74-93B3-C209786D872A}")


class ITactileDisplayCallbacks(IUnknown):
	"""Callback interface implemented by SimulateDisplay's caller.

	v1.16 introduced this interface so a caller can drive transport itself
	(``SimulateDisplay`` mode) and receive byte buffers from the library
	when content needs to be rendered. The addon's render path is wired
	through ``callbackServer.TactileDisplayCallbacks``.

	v1.18 appended ``GetTranslation`` at slot 9, letting the caller manage
	Liblouis translation. The v1.20 typelib still only exposes 2 methods,
	but the library binary expects a 3-method vtable — ``AddFocusedControl``
	AVs unless the third method is both declared AND returns a real
	translation (hardware-confirmed). ``GetTranslation`` is implemented via
	NVDA's ``louisHelper``; the COMMETHOD declared here matches the vendor
	IDL exactly (including ``POINTER(c_long)`` for the trailing
	``cursorOffset`` — a pointer per the IDL, not a value).
	"""

	_iid_ = _IID_CALLBACKS
	_methods_ = [
		# Slot 7 — TactileDisplayUpdated(data, length) (v1.16)
		COMMETHOD(
			[],
			HRESULT,
			"TactileDisplayUpdated",
			(["in"], POINTER(c_ubyte), "data"),
			(["in"], c_long, "length"),
		),
		# Slot 8 — BrailleDisplayUpdated(data, length) (v1.16)
		COMMETHOD(
			[],
			HRESULT,
			"BrailleDisplayUpdated",
			(["in"], POINTER(c_ubyte), "data"),
			(["in"], c_long, "length"),
		),
		# Slot 9 — GetTranslation(input, cursorOffset) -> (output, originalOffsets)
		# (v1.18). IDL: ``HRESULT GetTranslation([in]BSTR input,
		# [out]BSTR* output, [out]int* originalOffsets, [in]int* cursorOffset)``.
		#
		# Per vendor clarification (Joe, 2026-05-26):
		# - ``originalOffsets`` is an ARRAY filled by liblouis with the
		#   ``brailleToRawPos`` mapping (one int per output braille cell,
		#   value = input character index that produced that cell). The
		#   caller (library) pre-allocates the buffer; the callee fills
		#   it. Length matches ``len(output)``. The library uses this
		#   array post-translation to apply ``[BrailleMarking]``-driven
		#   selection / typeform markers (dots 7+8 on selected text,
		#   underlines, etc.) — the same trick NVDA does at
		#   ``source/braille.py:637`` with its local ``brailleToRawPos``.
		# - ``cursorOffset`` is INOUT despite the ``[in]`` IDL annotation:
		#   the library passes the input-space cursor in, and the callee
		#   writes back the translated braille-space cursor through the
		#   same pointer.
		#
		# Both pointers are declared as ``["in"]`` here so comtypes
		# passes them through to the Python method without auto-writing
		# a single return value (which is what ``["out"]`` would do for
		# the single-int case, incompatible with our multi-int array
		# write and our INOUT pointer-write semantics). The COM calling
		# convention is identical either way — caller passes a pointer
		# in the parameter slot, callee may write through it. The
		# Python implementation manually writes to both pointers via
		# pointer indexing (``ptr[i] = val``) and ``.contents.value``.
		#
		# The trailing ``cursorOffset`` parameter is a POINTER (not a
		# value); on x64 the calling convention passes an 8-byte pointer,
		# and declaring it as ``c_long`` (4-byte value) corrupts the
		# stack frame.
		COMMETHOD(
			[],
			HRESULT,
			"GetTranslation",
			(["in"], BSTR, "input"),
			(["out"], POINTER(BSTR), "output"),
			(["in"], POINTER(c_long), "originalOffsets"),
			(["in"], POINTER(c_long), "cursorOffset"),
		),
	]


class ITactileDisplayAPI(IDispatch):
	"""Hand-declared dual interface for TactileDisplayAPI v1.21.

	Slot ordering MUST match the library's documented vtable layout
	(re-verified for each bundled-library bump). Inserting or removing a
	method in the middle is a binary-incompat change; new methods are
	APPENDED.

	Slot map:
		0-2:  IUnknown    (inherited from comtypes.IUnknown via IDispatch)
		3-6:  IDispatch   (inherited from comtypes.IDispatch)
		7-37: library methods, declared below (31 methods; slots 7-34
		      unchanged from v1.17/v1.20; slot 35 new in v1.0.21;
		      slots 36-37 shifted from v1.0.20 slots 35-36)

	Connect (slot 7) returns ``c_int`` — NOT HRESULT. The typelib reports
	HRESULT, but empirical testing showed the library uses the return value
	as a connection-attempt status code (0 = success, non-zero = soft
	failure with library-specific meaning). comtypes' default HRESULT
	auto-raise would discard that value, so we keep the hand-deviation here.

	SimulateDisplay (slot 8, v1.16) uses a caller-managed transport path.
	``wrapper.py`` exposes ``simulateDisplay``.

	DisplayLiteraryBraille (slot 11, v1.17) is declared but the addon does
	not call it. The wrapper.py facade does not expose it. v1.18 also
	surfaces the same control via the ``[Liblouis]DisplayLiteraryBraille``
	ini key.

	Show (slot 28) returns HRESULT — but the library returns S_FALSE
	(0x00000001, positive) when no device is connected. comtypes only
	auto-raises on negative HRESULTs, so S_FALSE is harmless.

	ExecuteOperation (slot 37) takes a VARIANT as its second argument.
	Per the typelib docstring: BSTR for ``TypeKey``, VT_I4 (c_long) for
	``RouteCursor``, otherwise VT_EMPTY / VT_NULL. Used with SimulateDisplay.

	All other methods return HRESULT — comtypes auto-raises ``COMError``
	on failure, replacing the previous wrapper's manual ``checkHr`` calls.
	"""

	_iid_ = _IID_LEGACY  # metadata; QI uses comLoader.IID_CANDIDATES at runtime
	_methods_ = [
		# Slot 7 — Connect (returns library status int, NOT HRESULT)
		COMMETHOD(
			[],
			c_int,
			"Connect",
			(["in"], c_int, "preference"),
		),
		# Slot 8 — SimulateDisplay (v1.16; declared for vtable correctness,
		# NOT called by addon code — wrapper.py exposes it via simulateDisplay)
		COMMETHOD(
			[],
			HRESULT,
			"SimulateDisplay",
			(["in"], BSTR, "displayName"),
			(["in"], c_long, "tactileDotsX"),
			(["in"], c_long, "tactileDotsY"),
			(["in"], c_long, "totalBrailleCellCount"),
			(["in"], c_long, "lineCount"),
			(["in"], POINTER(ITactileDisplayCallbacks), "callbacks"),
		),
		# Slot 9 — Disconnect
		COMMETHOD([], HRESULT, "Disconnect"),
		# Slot 10 — SetBrailleTables (3 BSTRs since v1.07)
		COMMETHOD(
			[],
			HRESULT,
			"SetBrailleTables",
			(["in"], BSTR, "literaryTable"),
			(["in"], BSTR, "mathTable"),
			(["in"], BSTR, "computerTable"),
		),
		# Slot 11 — DisplayLiteraryBraille (v1.17; non-math text uses literary
		# Braille when flag=1, computer Braille when flag=0. Declared for
		# vtable correctness; not called by addon code.)
		COMMETHOD(
			[],
			HRESULT,
			"DisplayLiteraryBraille",
			(["in"], c_int, "flag"),
		),
		# Slot 12 — SetBrailleLinePadding(padding: c_long) (v1.22; controls line
		# spacing on the tactile display: 0=auto, see vendor docs for enum values)
		COMMETHOD(
			[],
			HRESULT,
			"SetBrailleLinePadding",
			(["in"], c_long, "padding"),
		),
		# Slot 13 — ForceSixDotBraille(flag: VARIANT_BOOL) (v1.22; when True the
		# display uses 10 rows of 6-dot braille, sacrificing dot rows 7/8)
		COMMETHOD(
			[],
			HRESULT,
			"ForceSixDotBraille",
			(["in"], VARIANT_BOOL, "flag"),
		),
		# Slot 14 — SetDrawingMode (0 = buffered, 1 = immediate; shifted from
		# slot 12 by the v1.22 insertion of SetBrailleLinePadding/ForceSixDotBraille)
		COMMETHOD(
			[],
			HRESULT,
			"SetDrawingMode",
			(["in"], c_int, "immediate"),
		),
		# Slot 15 — GetDimensions (out, out)
		COMMETHOD(
			[],
			HRESULT,
			"GetDimensions",
			(["out"], POINTER(c_int), "dotsX"),
			(["out"], POINTER(c_int), "dotsY"),
		),
		# Slot 16 — Clear
		COMMETHOD([], HRESULT, "Clear"),
		# Slot 17 — DrawLine
		COMMETHOD(
			[],
			HRESULT,
			"DrawLine",
			(["in"], c_int, "x1"),
			(["in"], c_int, "y1"),
			(["in"], c_int, "x2"),
			(["in"], c_int, "y2"),
		),
		# Slot 18 — DrawBox
		COMMETHOD(
			[],
			HRESULT,
			"DrawBox",
			(["in"], c_int, "x"),
			(["in"], c_int, "y"),
			(["in"], c_int, "width"),
			(["in"], c_int, "height"),
		),
		# Slot 19 — DrawCircle
		COMMETHOD(
			[],
			HRESULT,
			"DrawCircle",
			(["in"], c_int, "xCenter"),
			(["in"], c_int, "yCenter"),
			(["in"], c_int, "radius"),
		),
		# Slot 20 — DrawPoly
		COMMETHOD(
			[],
			HRESULT,
			"DrawPoly",
			(["in"], c_int, "xCenter"),
			(["in"], c_int, "yCenter"),
			(["in"], c_int, "radius"),
			(["in"], c_int, "numSides"),
			(["in"], c_double, "startAngle"),
		),
		# Slot 21 — Fill
		COMMETHOD(
			[],
			HRESULT,
			"Fill",
			(["in"], c_int, "x"),
			(["in"], c_int, "y"),
			(["in"], c_int, "fillKind"),
		),
		# Slot 22 — InvertRect
		COMMETHOD(
			[],
			HRESULT,
			"InvertRect",
			(["in"], c_int, "x"),
			(["in"], c_int, "y"),
			(["in"], c_int, "width"),
			(["in"], c_int, "height"),
		),
		# Slot 23 — DrawBrailleLabel
		COMMETHOD(
			[],
			HRESULT,
			"DrawBrailleLabel",
			(["in"], c_int, "x"),
			(["in"], c_int, "y"),
			(["in"], BSTR, "brailleUnicode"),
		),
		# Slot 24 — DrawTextLabel (caller wraps in liblouisTablePathContext)
		COMMETHOD(
			[],
			HRESULT,
			"DrawTextLabel",
			(["in"], c_int, "x"),
			(["in"], c_int, "y"),
			(["in"], BSTR, "text"),
		),
		# Slot 25 — GraphMathEquation (caller wraps in liblouisTablePathContext)
		COMMETHOD(
			[],
			HRESULT,
			"GraphMathEquation",
			(["in"], BSTR, "expression"),
			(["in"], c_int, "xMin"),
			(["in"], c_int, "xMax"),
			(["in"], c_int, "dotsPerTick"),
			(["in"], c_int, "showLabel"),
		),
		# Slot 26 — DrawImage
		COMMETHOD(
			[],
			HRESULT,
			"DrawImage",
			(["in"], BSTR, "filename"),
			(["in"], BSTR, "aiParams"),
			(["in"], c_int, "magnification"),
		),
		# Slot 27 — DrawScreenRegion
		COMMETHOD(
			[],
			HRESULT,
			"DrawScreenRegion",
			(["in"], c_int, "x"),
			(["in"], c_int, "y"),
			(["in"], c_int, "width"),
			(["in"], c_int, "height"),
			(["in"], c_int, "magnification"),
		),
		# Slot 28 — DrawASCIIBrailleImage
		COMMETHOD(
			[],
			HRESULT,
			"DrawASCIIBrailleImage",
			(["in"], BSTR, "filename"),
		),
		# Slot 29 — UndoLastDraw
		COMMETHOD([], HRESULT, "UndoLastDraw"),
		# Slot 30 — Show (HRESULT — S_FALSE positive, doesn't auto-raise)
		COMMETHOD([], HRESULT, "Show"),
		# Slot 31 — ShowMultilineText (caller wraps in liblouisTablePathContext)
		COMMETHOD(
			[],
			HRESULT,
			"ShowMultilineText",
			(["in"], BSTR, "text"),
		),
		# Slot 32 — ShowStatusText (caller wraps in liblouisTablePathContext)
		COMMETHOD(
			[],
			HRESULT,
			"ShowStatusText",
			(["in"], BSTR, "text"),
		),
		# Slot 33 — AddFocusedControl (v1.12+, declared in v1.16; not called)
		COMMETHOD([], HRESULT, "AddFocusedControl"),
		# Slot 34 — UpdateCursor (v1.12+, declared in v1.16; not called)
		COMMETHOD([], HRESULT, "UpdateCursor"),
		# Slot 35 — RegisterEvents(VARIANT_BOOL) (v1.12+, declared in v1.16; not called)
		COMMETHOD(
			[],
			HRESULT,
			"RegisterEvents",
			(["in"], VARIANT_BOOL, "enable"),
		),
		# Slot 36 — ShowBrailleOnScreen(VARIANT_BOOL) (v1.12+, declared in v1.16; not called)
		COMMETHOD(
			[],
			HRESULT,
			"ShowBrailleOnScreen",
			(["in"], VARIANT_BOOL, "enable"),
		),
		# Slot 37 — SetHybridPrintAndBrailleMode(VARIANT_BOOL) (v1.0.21; shifted from
		# slot 35 by the v1.22 insertion of SetBrailleLinePadding/ForceSixDotBraille)
		COMMETHOD(
			[],
			HRESULT,
			"SetHybridPrintAndBrailleMode",
			(["in"], VARIANT_BOOL, "flag"),
		),
		# Slot 38 — EnableContractedBrailleInput(VARIANT_BOOL) (v1.12+; shifted from
		# slot 36 by the v1.0.21 insertion, then slot 38 by the v1.22 insertion; not called)
		COMMETHOD(
			[],
			HRESULT,
			"EnableContractedBrailleInput",
			(["in"], VARIANT_BOOL, "enable"),
		),
		# Slot 39 — ExecuteOperation(operation, argument: VARIANT) (v1.16; shifted from
		# slot 36→37 at v1.0.21, then to slot 39 at v1.22)
		COMMETHOD(
			[],
			HRESULT,
			"ExecuteOperation",
			(["in"], c_long, "operation"),
			(["in"], VARIANT, "argument"),
		),
	]
