# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Render path for TactileDisplayAPI's SimulateDisplay mode.

When the library calls ``ITactileDisplayCallbacks.TactileDisplayUpdated``,
this module's ``renderTactileBytes`` is invoked with the raw payload bytes.
The bytes are in standard braille cell notation — one byte per cell, with
the Unicode braille pattern bit mapping (confirmed by hardware probe).

The render path turns those bytes into DotPad device writes by:

1. Constructing a ``DpTactileGraphicsBuffer`` sized to the graphic display.
2. Calling ``tactile.braille.drawBrailleCells`` per row with
   ``hCellPadding=0`` (graphic display, no cell spacing). The function
   decomposes each braille byte via ``_brailleDotCoords`` and calls
   ``setDot`` per set bit; ``setDot``'s bit math writes ``_cellBuffer``
   in DotPad graphic-mode pin encoding.
3. Calling ``graphicDisplay.display(buf)`` — the existing entry point
   that delta-compares each row against the prior frame and queues only
   changed rows via ``Packet.makePacket``.

The whole pipeline runs on the ``LibraryWorker`` STA thread — callbacks
fire there and ``Display.display`` queue submission is thread-safe, so no
bouncing to NVDA's main thread is needed.

For ``BrailleDisplayUpdated`` (braille-text content), this module logs and
drops those callbacks since the addon does not use the library's
``ShowMultilineText`` / ``ShowStatusText`` methods in SimulateDisplay mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import addonHandler
from logHandler import log
from tactile.braille import drawBrailleCells

try:
	from ..utils.testing import IS_UNDER_UNITTEST
except ImportError:
	IS_UNDER_UNITTEST = False  # type: ignore

if TYPE_CHECKING or IS_UNDER_UNITTEST:
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from ..presentations.base import Presentation
else:
	_addon = addonHandler.getCodeAddon()
	DpTactileGraphicsBuffer = _addon.loadModule(
		"brailleDisplayDrivers.dotPad.tactileBuffer",
	).DpTactileGraphicsBuffer


def _getLibraryBytesConsumerClasses() -> tuple[type, ...]:
	"""Lazily resolve the presentation classes whose presence opens the gate.

	Resolved at call time (not module load) to avoid the load-order cycle
	with ``addon.presentations.braille`` — that module is what loads the
	driver, which loads us. Caching is safe because the classes never
	change at runtime.
	"""
	global _libraryBytesConsumerClasses
	cached = _libraryBytesConsumerClasses
	if cached is not None:
		return cached
	if TYPE_CHECKING or IS_UNDER_UNITTEST:
		from ..presentations.braille import LibraryBraillePresentation
		from ..presentations.graphic import GraphicPresentation
	else:  # pragma: no cover - exercised at NVDA runtime, not under unittest
		_localAddon = addonHandler.getCodeAddon()
		GraphicPresentation = _localAddon.loadModule("presentations.graphic").GraphicPresentation
		LibraryBraillePresentation = _localAddon.loadModule(
			"presentations.braille",
		).LibraryBraillePresentation
	resolved = (GraphicPresentation, LibraryBraillePresentation)
	_libraryBytesConsumerClasses = resolved
	return resolved


_libraryBytesConsumerClasses: tuple[type, ...] | None = None


def _getBrailleHandler() -> Any:
	"""Return NVDA's ``braille.handler`` — wrapped so tests can monkey-patch it.

	NVDA's ``braille`` module isn't importable under pytest (no NVDA
	runtime), so test code patches this helper to return a mock.
	"""
	import braille  # imported lazily so unit tests can patch this function

	return braille.handler


def _getActivePresentation() -> Presentation | None:
	"""Return the renderer's active presentation, or ``None``.

	Walks ``braille.handler.display._renderer.presentationManager.activePresentation``,
	returning ``None`` on any missing link. Wrapped in a helper so unit
	tests can patch it directly and so the gate has a single defensive
	traversal point.
	"""
	try:
		handler = _getBrailleHandler()
		if handler is None:
			return None
		display = handler.display
		if display is None:
			return None
		renderer = getattr(display, "_renderer", None)
		if renderer is None:
			return None
		manager = getattr(renderer, "presentationManager", None)
		if manager is None:
			return None
		return getattr(manager, "activePresentation", None)
	except Exception:
		# Defensive — the gate MUST NOT raise out of the COM callback.
		log.debug("renderTactileBytes: failed to read active presentation", exc_info=True)
		return None


def renderTactileBytes(payload: bytes) -> None:
	"""Render a tactile-display payload from the library callback to hardware.

	A presentation-aware gate controls which bytes reach
	``graphicDisplay.display(buf)``. Library bytes only pass through when
	the active presentation is ``GraphicPresentation`` (tactile-graphic
	content) or ``LibraryBraillePresentation`` (library-driven multi-line
	braille). Any other active presentation (``BraillePresentation``,
	table, chart, screen capture, or ``None``) causes the bytes to be
	discarded with a debug log entry.

	:param payload: Bytes in standard braille cell notation, row-major
		over the graphic display. Length should equal
		``physicalNumRows * physicalNumCols``; mismatched lengths are
		clamped / zero-padded with a warning.
	"""
	# Gate: only library-bytes-consuming presentations may write to the
	# multi-line area. Other presentations own the area via NVDA-driven
	# rendering; their content would be clobbered if we passed bytes
	# through.
	try:
		activePresentation = _getActivePresentation()
		allowedClasses = _getLibraryBytesConsumerClasses()
		if not isinstance(activePresentation, allowedClasses):
			activeName = type(activePresentation).__name__ if activePresentation else "None"
			log.debug(
				f"renderTactileBytes: discarding {len(payload)} bytes; active "
				f"presentation {activeName} is not a library-bytes consumer",
			)
			return
	except Exception:
		# Defensive — must not raise out of the COM callback.
		log.exception("renderTactileBytes: gate isinstance check raised; discarding")
		return

	graphicDisplay = _getGraphicDisplay()
	if graphicDisplay is None:
		# No graphic display attached — nothing to render. The session
		# should never have entered SimulateDisplay mode in this case,
		# but we defensively no-op here.
		return

	physicalNumCols = int(graphicDisplay.physicalNumCols)
	physicalNumRows = int(graphicDisplay.physicalNumRows)
	cellHeight = int(graphicDisplay.cellHeight)
	expectedLen = physicalNumRows * physicalNumCols

	if len(payload) != expectedLen:
		log.warning(
			f"renderTactileBytes: payload length {len(payload)} != expected "
			f"{expectedLen} ({physicalNumRows}r × {physicalNumCols}c); "
			"rendering what fits, padding tail with zeros",
		)

	buf = DpTactileGraphicsBuffer(
		hCellCount=physicalNumCols,
		vCellCount=physicalNumRows,
	)
	# Iterate row-by-row. For rows beyond the payload, do nothing — the
	# buffer starts zero-initialised and those cells stay zero.
	for rowIndex in range(physicalNumRows):
		start = rowIndex * physicalNumCols
		end = start + physicalNumCols
		if start >= len(payload):
			break
		rowCells = list(payload[start:end])
		drawBrailleCells(
			buf,
			0,
			rowIndex * cellHeight,
			rowCells,
			hCellPadding=0,
		)
	graphicDisplay.display(buf)


def renderBrailleBytes(payload: bytes) -> None:
	"""Log and discard a braille-text payload from the library callback.

	The braille callback fires when the library renders content via
	``ShowMultilineText``, ``ShowStatusText``, or its multiline-text
	pipeline. The addon does not call those methods in SimulateDisplay mode,
	so this callback should not fire under normal operation. If it does
	(e.g. via ``AddFocusedControl`` or library-internal triggers), we log
	at debug and discard the bytes.
	"""
	log.debug(f"renderBrailleBytes: ignoring {len(payload)} bytes (log-and-drop)")


def getNVDABrailleTableIfAvailable() -> str | None:
	"""Return the filename of NVDA's currently-active braille output table
	IF that file exists in NVDA's liblouis tables directory; otherwise
	``None``.

	The library accepts a literary translation table via ``SetBrailleTables``.
	Without that call it uses whatever's set in the ``TactileDisplayAPI.ini``
	(currently ``en-us-g2.ctb``). If the user has configured NVDA for a
	different table — and that table exists in NVDA's ``louis/tables``
	directory — this passes it to the library so the multi-line braille
	matches NVDA's configured output table.

	The library loads its tables from NVDA's ``TablesPath``
	(``brailleTables.TABLES_DIR``), so the existence check targets that
	directory. Users with custom tables installed outside ``louis/tables``
	won't match — for those we return ``None`` and the library keeps its
	default. Logged so the user understands the mismatch.
	"""
	try:
		import os

		import braille
		import brailleTables

		handler = braille.handler  # type: ignore[attr-defined]
		if handler is None:
			return None
		tableObj = getattr(handler, "table", None)
		if tableObj is None:
			return None
		tableName = getattr(tableObj, "fileName", None)
		if not tableName:
			return None
		# NVDA's liblouis tables directory — the same directory the patched
		# INI points the library's ``TablesPath`` at.
		tablesDir = brailleTables.TABLES_DIR
		if not os.path.exists(os.path.join(tablesDir, tableName)):
			log.info(
				f"dotPad: NVDA's braille table {tableName!r} is not present in "
				"NVDA's louis/tables directory; the library will keep its default "
				"table. To match NVDA's braille shape on the multi-line area, "
				"select a table whose file ships with NVDA's liblouis.",
			)
			return None
		return str(tableName)
	except Exception:
		log.debug(
			"getNVDABrailleTableIfAvailable: failed to read NVDA's braille table",
			exc_info=True,
		)
		return None


def computeSimulateDisplayArgs() -> tuple[str, int, int, int, int]:
	"""Compute the arguments to ``ITactileDisplayAPI.SimulateDisplay``.

	Reads the currently-attached ``BrailleDisplayDriver`` to derive
	dimensions. The library expects **dot counts** (not cell counts) for
	the tactile area and **raw cell counts** (no spacing adjustment) for
	the braille text area.

	:returns: ``(displayName, tactileDotsX, tactileDotsY, totalBrailleCellCount, lineCount)``
	:raises RuntimeError: if no graphic display is attached.
	"""
	display = _getDriverDisplay()
	graphicDisplay = display.graphicDisplay
	if graphicDisplay is None:
		raise RuntimeError("SimulateDisplay path requires a graphic display; none attached")

	tactileDotsX = int(graphicDisplay.physicalNumCols) * int(graphicDisplay.cellWidth)
	tactileDotsY = int(graphicDisplay.physicalNumRows) * int(graphicDisplay.cellHeight)

	textDisplay = display.textDisplay
	if textDisplay is None:
		totalBrailleCellCount = 0
		lineCount = 0
	else:
		totalBrailleCellCount = int(textDisplay.physicalNumRows) * int(textDisplay.physicalNumCols)
		lineCount = int(textDisplay.physicalNumRows)

	displayName = str(getattr(display, "_deviceName", "") or "DotPad")
	return displayName, tactileDotsX, tactileDotsY, totalBrailleCellCount, lineCount


def _getGraphicDisplay() -> Any:
	"""Return the active graphic-display surface, or None if unavailable."""
	handler = _getBrailleHandler()
	if handler is None:
		return None
	display = handler.display
	if display is None:
		return None
	return getattr(display, "graphicDisplay", None)


def _getDriverDisplay() -> Any:
	"""Return the active ``BrailleDisplayDriver`` instance.

	:raises RuntimeError: if no braille display driver is attached.
	"""
	handler = _getBrailleHandler()
	if handler is None or handler.display is None:
		raise RuntimeError("no braille display driver attached")
	return handler.display
