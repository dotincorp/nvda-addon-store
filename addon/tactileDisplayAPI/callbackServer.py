# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Python-side COM server implementing ITactileDisplayCallbacks for SimulateDisplay.

When the addon uses TactileDisplayAPI's SimulateDisplay mode (v1.16+), the
library no longer owns the device transport — instead it calls back into the
addon when content needs to be rendered. The caller-side callback target is
implemented here.

``GetTranslation`` (v1.18) is implemented against NVDA's
``louisHelper.translate``. Hardware testing of v1.20 confirmed that
``AddFocusedControl`` AVs unless this third callback is both declared and
answers with a real translation. The implementation uses NVDA's
currently-configured braille table so the multi-line tactile area renders
the same braille as NVDA's regular 20-cell text display for the same input.

Threading-ownership
-------------------
- **Construction**: on the ``LibraryWorker`` STA thread. comtypes does not
  perform apartment registration at instance construction — the apartment the
  COM object belongs to is determined by the thread that creates it plus that
  thread's ``CoInitializeEx`` state. The worker calls
  ``CoInitializeEx(COINIT_APARTMENTTHREADED)`` at start, so an instance built
  there lives in that STA.
- **Method invocation**: the library calls back on the same STA (vendor docs
  imply "block the thread" semantics). The COM marshaller handles the case
  where the library calls from a different apartment.
- **Destruction**: on the ``LibraryWorker`` STA. The refcount hits zero after
  both the library's outgoing pointer and the ``BrailleDisplayDriver``'s
  strong reference are released.

Lifetime contract
-----------------
1. The driver creates the callback server on the worker thread.
2. Passes a comtypes pointer to ``ITactileDisplayAPI.SimulateDisplay``;
   the library calls AddRef internally.
3. Callbacks fire 0..N times.
4. At session teardown: caller invokes ``setShuttingDown()`` to drain any
   in-flight callback and short-circuit subsequent ones to a no-op.
5. The library's pointer is released (refcount -1).
6. The session drops its strong reference (refcount -1, hits zero,
   ``__del__`` runs on the worker thread).

Exception contract
------------------
COM methods MUST NOT propagate Python exceptions into the library — that
behaviour is undefined. Each method body wraps its work in
``try/except: log.exception(...); return S_OK``.
"""

from __future__ import annotations

import ctypes
import threading
from typing import Any, Callable, cast

from comtypes import COMObject  # pyright: ignore[reportUnknownVariableType]
from logHandler import log

from ..utils.logOnce import warnFailureOnce
from .comInterface import ITactileDisplayCallbacks


# S_OK is 0; comtypes uses HRESULT internally. Render callbacks always
# return S_OK so the library never sees a non-success result that would
# change its control flow.
_S_OK = 0


def _translateText(
	text: str,
	cursorOffset: int | None,
) -> tuple[str, list[int], int | None]:
	"""Translate ``text`` to Unicode-braille using NVDA's current table.

	Wraps :func:`addon.utils.braille.translateTextWithCursor` and
	converts the returned 8-bit cell ints to a Unicode-braille codepoint
	string (the format the library's multi-line tactile area consumes).

	Returns ``(brailleString, brailleToRawPos, brailleCursorPos)``:

	- ``brailleString`` is a sequence of Unicode-braille codepoints
	  (each character in U+2800-U+28FF). Empty when input is empty or
	  translation fails.
	- ``brailleToRawPos`` is the per-output-cell list of input character
	  indices (the array the library expects in ``originalOffsets`` so
	  it can apply ``[BrailleMarking]``-driven selection / typeform
	  markers). Empty list on failure.
	- ``brailleCursorPos`` is the braille-space cursor position
	  corresponding to ``cursorOffset``, or ``None`` when ``cursorOffset``
	  is ``None`` / out of range / translation failed.

	Never raises. Logs at WARNING with per-exception-type dedup on failure.
	Returns ``("", [], None)`` on any failure so the COM caller can skip
	writing through its OUT pointers.
	"""
	if not text:
		return ("", [], None)
	try:
		# Lazy import so this module loads cleanly during NVDA bootstrap
		# (utils.braille pulls in NVDA's braille / louisHelper, which need
		# the full NVDA env initialised — not always true at addon import time).
		from ..utils.braille import translateTextWithCursor  # noqa: PLC0415
	except Exception as exc:
		warnFailureOnce(
			"GetTranslation: import utils.braille.translateTextWithCursor",
			exc,
			"returning empty output",
		)
		return ("", [], None)
	try:
		# Clamp cursorOffset into the valid range; pass None through so
		# louisHelper distinguishes "no cursor" from "cursor at position 0".
		if cursorOffset is not None:
			cursorOffset = max(0, min(int(cursorOffset), len(text)))
		cells, brailleToRawPos, brailleCursorPos = translateTextWithCursor(text, cursorOffset)
		brailleString = "".join(chr(0x2800 + (cell & 0xFF)) for cell in cells)
		return (brailleString, brailleToRawPos, brailleCursorPos)
	except Exception as exc:
		warnFailureOnce("GetTranslation: translateTextWithCursor", exc, "returning empty output")
		return ("", [], None)


def _coerceCursorPointer(cursorOffset: object) -> int | None:
	"""Dereference comtypes' ``[in]int*`` parameter shape into an int or None.

	comtypes presents ``[in]int*`` arguments as ctypes pointer objects.
	A NULL pointer (which the library *does* pass for ``GetTranslation``
	on v1.20, per Joe's hardware test) is presented as a pointer
	object whose ``.contents`` access raises ``ValueError: NULL pointer
	access`` — NOT as Python ``None``. Without this defence, the
	``ValueError`` propagates back into comtypes, which converts it to
	a failing HRESULT, and the library AVs in its error handler.

	Returns the int the pointer references, or ``None`` for NULL /
	missing / unexpected shapes (all of which mean "no cursor" to the
	caller).
	"""
	if cursorOffset is None:
		return None
	# Attempt 1: ctypes pointer with ``.contents`` (the comtypes-typical case).
	try:
		contents = cursorOffset.contents  # type: ignore[attr-defined]
	except (ValueError, AttributeError):
		# ValueError = NULL pointer access; AttributeError = not a pointer at all.
		contents = None
	if contents is not None:
		valueAttr = getattr(contents, "value", contents)
		try:
			return int(valueAttr)
		except (TypeError, ValueError):
			return None
	# Attempt 2: comtypes occasionally flattens pointer→value for in-params.
	try:
		return int(cursorOffset)  # type: ignore[arg-type]
	except (TypeError, ValueError):
		return None


RenderCallable = Callable[[bytes], None]
"""Signature for the render-path callable injected at construction.

The callable receives the COPY of the callback's byte buffer (already
extracted via ctypes.string_at so the library can free its buffer when
the call returns). The callable must be non-blocking — long work would
block the library's calling thread (per vendor docs).
"""


class TactileDisplayCallbacks(COMObject):
	"""COM server for ``ITactileDisplayCallbacks``.

	Receives ``TactileDisplayUpdated`` and ``BrailleDisplayUpdated``
	invocations from TactileDisplayAPI when running in SimulateDisplay
	mode. Dispatches each byte buffer to the injected render callable.
	"""

	_com_interfaces_ = [ITactileDisplayCallbacks]

	# IID metadata for documentation and test alignment. Deliberately named
	# ``IID`` (not ``_iid_``) — comtypes' ``_compointer_base.from_param`` has
	# a "same-IID short-circuit" branch that reads ``value._iid_`` on the
	# argument value. If we expose ``_iid_`` on our COMObject instance, that
	# branch returns the Python object unchanged instead of looking up the
	# typed COM pointer in ``_com_pointers_``, and ctypes then raises
	# "Don't know how to convert parameter N" at the SimulateDisplay call
	# site. The correct IID-keyed pointer lookup lives in
	# ``_com_pointers_[ITactileDisplayCallbacks._iid_]`` automatically;
	# this attribute is for human / test inspection only.
	IID = ITactileDisplayCallbacks._iid_  # pyright: ignore[reportPrivateUsage]

	def __init__(
		self,
		renderTactile: RenderCallable,
		renderBraille: RenderCallable,
	) -> None:
		"""Construct the server with the render callables for each target.

		:param renderTactile: invoked on ``TactileDisplayUpdated``. Receives
			the callback bytes as a Python ``bytes``.
		:param renderBraille: invoked on ``BrailleDisplayUpdated``. Same shape.
		"""
		super().__init__()
		self._renderTactile = renderTactile
		self._renderBraille = renderBraille
		self._shuttingDown = False
		# Held while a callback body executes. Teardown acquires it to wait
		# for any in-flight call to drain before the caller releases the
		# Python-side strong reference.
		self._inFlightLock = threading.Lock()

	def setShuttingDown(self) -> None:
		"""Mark the server as no longer accepting work.

		After this call, both COM methods short-circuit to a no-op and
		return S_OK. Then the caller waits for any in-flight callback to
		complete (the lock dance) before releasing references.
		"""
		self._shuttingDown = True
		# Acquire then release the lock to wait for an in-flight callback
		# to drain. If no callback is running, this is essentially a no-op.
		with self._inFlightLock:
			pass

	def TactileDisplayUpdated(self, data: object, length: object) -> int:
		"""COM method: tactile-area content needs rendering.

		:param data: ``POINTER(c_ubyte)`` from comtypes — pointer to the
			library's buffer. Must not be retained past return.
		:param length: ``c_long`` count of bytes in ``data``.
		:returns: HRESULT (always S_OK; errors are logged and swallowed).
		"""
		return self._dispatch(data, length, self._renderTactile, "Tactile")

	def BrailleDisplayUpdated(self, data: object, length: object) -> int:
		"""COM method: braille-text content needs rendering."""
		return self._dispatch(data, length, self._renderBraille, "Braille")

	def GetTranslation(
		self,
		input: object,
		originalOffsets: object,
		cursorOffset: object,
	) -> str:
		"""COM method: caller-side Liblouis translation (v1.18).

		Per vendor clarification (Joe, 2026-05-26):

		- ``originalOffsets`` is an OUT array (one int per output braille
		  cell, value = the input character index that produced that
		  cell). The library pre-allocates the buffer; we fill it with
		  ``brailleToRawPos`` so the library can apply post-translation
		  selection / typeform markers from its ``[BrailleMarking]`` ini
		  config.
		- ``cursorOffset`` is INOUT despite the ``[in]`` IDL annotation:
		  the library passes the input-space cursor and expects us to
		  write the translated braille-space cursor back through the
		  same pointer.

		Both are declared ``["in"]`` in the COMMETHOD (see
		``comInterface.py``) so comtypes hands us the raw ctypes
		pointers rather than auto-marshalling single-int writes. We
		write through them manually.

		Returns just the output BSTR (single ``[out]`` Python return);
		never raises into the library.

		:param input: the text to translate (BSTR).
		:param originalOffsets: ``POINTER(c_long)`` to a caller-allocated
			int array of length ``len(output)``. We fill it with the
			``brailleToRawPos`` mapping. ``None`` / NULL → skip the write.
		:param cursorOffset: ``POINTER(c_long)`` — IN-side is the cursor
			position in input-character-index space; OUT-side gets the
			translated braille-space cursor written back. ``None`` /
			NULL → no cursor; we don't write back.
		:returns: Unicode-braille string for ``output``.
		"""
		if self._shuttingDown:
			return ""
		cursor = _coerceCursorPointer(cursorOffset)
		text = "" if input is None else str(input)
		brailleString, brailleToRawPos, brailleCursorPos = _translateText(text, cursor)
		# Clamp output (and the offsets fill) to the library's ``originalOffsets``
		# buffer size: per vendor it allocates ``4 * len(input) + 4096`` ints and
		# passes no length, so ``4 * len(input) + 4095`` is the largest write that
		# stays inside it. ``brailleString``, ``brailleToRawPos`` and the cell
		# count are the same length, so one slice keeps them consistent. The cap
		# sits far above any real translation; it only bounds a pathological
		# out >> in expansion.
		maxCells = 4 * len(text) + 4095
		if len(brailleToRawPos) > maxCells:
			brailleString = brailleString[:maxCells]
			brailleToRawPos = brailleToRawPos[:maxCells]
			if brailleCursorPos is not None and brailleCursorPos >= maxCells:
				brailleCursorPos = None
		# Fill the library's pre-allocated originalOffsets buffer with the
		# brailleToRawPos mapping. Skip if the library passed NULL (no
		# pointer to write to) or we have no values to write (translation
		# failed / empty input).
		#
		# ``originalOffsets`` is declared ``object`` in the COM signature
		# (comtypes hands raw ctypes pointers for ``["in"]int*`` params);
		# at runtime it is a ``POINTER(c_long)`` to the caller-allocated
		# array. Cast to ``Any`` so pyright permits the indexed write.
		if originalOffsets and brailleToRawPos:
			try:
				offsetsArr = cast(Any, originalOffsets)
				for i, value in enumerate(brailleToRawPos):
					offsetsArr[i] = value
			except (ValueError, IndexError, OverflowError):
				log.exception("GetTranslation: writing originalOffsets array failed")
		# Write the translated braille-space cursor back through the
		# cursorOffset pointer (INOUT semantics per Joe). Skip if the
		# library passed NULL (we have no pointer to write to) or
		# liblouis produced no cursor (input cursor was None / out of
		# range / translation failed).
		#
		# Same comtypes shape as above — cast to ``Any`` for the
		# ``.contents.value`` writeback; runtime type is ``POINTER(c_long)``.
		if cursor is not None and brailleCursorPos is not None:
			try:
				cast(Any, cursorOffset).contents.value = int(brailleCursorPos)
			except (ValueError, AttributeError):
				log.exception("GetTranslation: writing cursorOffset back failed")
		return brailleString

	def _dispatch(
		self,
		data: object,
		length: object,
		render: RenderCallable,
		target: str,
	) -> int:
		"""Common body for both COM methods.

		Extracts the byte buffer (copying it out of the library-owned
		memory), routes to ``render``, and swallows every exception.
		"""
		if self._shuttingDown:
			return _S_OK
		with self._inFlightLock:
			try:
				lengthInt = self._coerceLength(length)
				if lengthInt <= 0:
					log.debug("%sDisplayUpdated: empty payload (length=%s); dropping", target, lengthInt)
					return _S_OK
				if data is None:
					log.debugWarning("%sDisplayUpdated: null data pointer; dropping", target)
					return _S_OK
				# Copy the bytes out of library-owned memory. After return,
				# the library may reuse / free the buffer. `data` is typed
				# as `object` because comtypes dispatches via dynamic vtable
				# bindings; the runtime type is always `POINTER(c_ubyte)`
				# (see comInterface.ITactileDisplayCallbacks._methods_).
				payload = ctypes.string_at(data, lengthInt)  # pyright: ignore[reportArgumentType]
				render(payload)
			except Exception:
				# NVDA's Logger.exception takes exc_info as its second parameter and
				# passes an empty args tuple to _log, so lazy %-args are impossible
				# here -- an f-string is the only option. See docs/logging.md.
				log.exception(f"{target}DisplayUpdated: exception in render path; swallowed")  # noqa: G004
		return _S_OK

	@staticmethod
	def _coerceLength(length: object) -> int:
		"""Pull an int out of comtypes' ``c_long`` parameter.

		comtypes typically passes Python ints directly, but defensive
		coercion handles the case where it passes a ctypes value.
		"""
		# ctypes types have a `.value` attribute; bare ints don't.
		valueAttr = getattr(length, "value", None)
		if valueAttr is not None:
			return int(valueAttr)
		return int(length)  # type: ignore[arg-type]
