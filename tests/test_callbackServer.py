# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Smoke tests for the SimulateDisplay callback server (feature 014).

Asserts the Python class implementing ``ITactileDisplayCallbacks``
(declared in feature 013's comInterface.py) has the right IID, can
be constructed without raising, and never propagates exceptions back
into the COM layer.

These are pure-Python unit tests; no COM library load happens. The
class under test is a `comtypes.COMObject` subclass — comtypes
validates the vtable / IID linkage at construction time, which is
what `test_classConstructs` exercises.
"""

from __future__ import annotations

import unittest
from ctypes import c_long, c_ubyte


class TestTactileDisplayCallbacksContract(unittest.TestCase):
	"""``TactileDisplayCallbacks`` satisfies the callback-server contract."""

	def test_iidMatchesInterface(self) -> None:
		"""Server class IID matches the interface declared in comInterface.

		Note: the attribute is ``IID`` (not ``_iid_``) — exposing ``_iid_``
		on the COMObject server breaks comtypes' typed-pointer conversion
		via ``_compointer_base.from_param``. See ``callbackServer.py``'s
		class-level comment.
		"""
		from addon.tactileDisplayAPI.callbackServer import TactileDisplayCallbacks
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayCallbacks

		self.assertEqual(TactileDisplayCallbacks.IID, ITactileDisplayCallbacks._iid_)

	def test_classConstructs(self) -> None:
		"""Instantiating the server with a no-op render path raises nothing.

		comtypes builds the COM vtable at instance construction; a bad
		_com_interfaces_ entry would raise here.
		"""
		from addon.tactileDisplayAPI.callbackServer import TactileDisplayCallbacks

		instance = TactileDisplayCallbacks(
			renderTactile=lambda data: None,
			renderBraille=lambda data: None,
		)
		self.assertIsNotNone(instance)

	def test_methodsAreNonThrowing(self) -> None:
		"""Render-path callable that raises does not propagate into COM.

		The callback contract requires the method body to catch every
		exception and return S_OK. We
		simulate the COM call by invoking the Python method directly
		with a small in-memory byte buffer; if the exception propagates,
		this test catches it.
		"""
		from addon.tactileDisplayAPI.callbackServer import TactileDisplayCallbacks

		def boom(_data: bytes) -> None:
			raise RuntimeError("synthetic render-path failure")

		instance = TactileDisplayCallbacks(renderTactile=boom, renderBraille=boom)

		# Build a small ctypes ubyte buffer the way comtypes would deliver it.
		size = 4
		bufferType = c_ubyte * size
		buffer = bufferType(0x01, 0x02, 0x03, 0x04)
		data = bufferType.from_buffer(buffer)

		# Direct method call — bypasses the COM marshaller but exercises the
		# Python body's exception-handling, which is what the contract locks.
		result = instance.TactileDisplayUpdated(data, c_long(size))
		self.assertEqual(result, 0)  # S_OK = 0

		result = instance.BrailleDisplayUpdated(data, c_long(size))
		self.assertEqual(result, 0)

	def test_shutdownStopsAcceptingCallbacks(self) -> None:
		"""After setShuttingDown(), callbacks short-circuit to S_OK no-op.

		Prevents use-after-free during teardown (the library may still
		hold a pointer when the GraphicDisplaySession is dropping its
		reference). See callback-server.md §Teardown order.
		"""
		from addon.tactileDisplayAPI.callbackServer import TactileDisplayCallbacks

		calls: list[bytes] = []
		instance = TactileDisplayCallbacks(
			renderTactile=calls.append,
			renderBraille=calls.append,
		)
		size = 1
		bufferType = c_ubyte * size
		data = bufferType.from_buffer(bufferType(0xFF))

		# Live: render path is called.
		instance.TactileDisplayUpdated(data, c_long(size))
		self.assertEqual(len(calls), 1)

		# After shutdown: callbacks no-op.
		instance.setShuttingDown()
		instance.TactileDisplayUpdated(data, c_long(size))
		instance.BrailleDisplayUpdated(data, c_long(size))
		self.assertEqual(len(calls), 1, "post-shutdown callbacks must not call the render path")

	def test_getTranslationIsDeclared(self) -> None:
		"""``GetTranslation`` is declared on this server (feature 024).

		v1.20's binary expects a 3-method vtable on the callback
		COMObject; the library AVs in ``AddFocusedControl``'s
		focus-fetch/translate pipeline unless the third method is
		present and returns a real braille translation. Feature 024
		implements it via NVDA's ``louisHelper``.
		"""
		from addon.tactileDisplayAPI.callbackServer import TactileDisplayCallbacks

		self.assertTrue(
			hasattr(TactileDisplayCallbacks, "GetTranslation"),
			"GetTranslation must be declared (feature 024).",
		)


class TestGetTranslationHelper(unittest.TestCase):
	"""Feature 024 — ``_translateText`` helper.

	The helper is module-level (not a method) so the translation logic
	can be tested without instantiating the COMObject or mocking comtypes
	pointer marshalling. The COM method itself (`GetTranslation`) is a
	thin wrapper around this helper.

	Tests inject a fake ``addon.utils.braille`` module into ``sys.modules``
	BEFORE the helper's lazy import runs, rather than importing the real
	``addon.utils.braille`` (which pulls in NVDA's braille/config chain
	and fails in the test bootstrap where ``globalVars.appDir`` isn't
	always set in time).
	"""

	@staticmethod
	def _withFakeUtilsBraille(translateTextWithCursor):
		"""Return a context manager that swaps ``addon.utils.braille`` in
		``sys.modules`` for a fake module carrying the given
		``translateTextWithCursor`` callable.
		"""
		import sys
		import types
		from contextlib import contextmanager

		@contextmanager
		def cm():
			moduleName = "addon.utils.braille"
			fake = types.ModuleType(moduleName)
			fake.translateTextWithCursor = translateTextWithCursor
			original = sys.modules.get(moduleName)
			sys.modules[moduleName] = fake
			try:
				yield fake
			finally:
				if original is None:
					del sys.modules[moduleName]
				else:
					sys.modules[moduleName] = original

		return cm()

	def test_emptyInputReturnsEmptyOutput(self) -> None:
		"""Empty / None input short-circuits to ``("", [], None)`` without
		invoking the underlying translator (a translation call on empty
		input is a waste, AND would force NVDA bootstrap state we don't
		need at this layer).
		"""
		from addon.tactileDisplayAPI import callbackServer

		# No fake injected — empty input must short-circuit before any
		# import happens.
		self.assertEqual(callbackServer._translateText("", None), ("", [], None))
		self.assertEqual(callbackServer._translateText("", 0), ("", [], None))

	def test_translatesViaUtilsBraille(self) -> None:
		"""``_translateText`` delegates to ``utils.braille.translateTextWithCursor``,
		converts the returned cell ints to Unicode-braille codepoints,
		and passes through brailleToRawPos + brailleCursorPos verbatim.

		Per Joe's spec (2026-05-26), brailleToRawPos is the array the
		library wants in ``originalOffsets`` for selection/typeform
		marking; ``brailleCursorPos`` is written back through the
		caller's ``cursorOffset`` pointer when present.

		Injects a fake utility module so the assertion is independent of
		which liblouis table NVDA happens to have loaded — and independent
		of the test-bootstrap quirk that prevents the real utility from
		importing here.
		"""
		from addon.tactileDisplayAPI import callbackServer

		# Cells 0x01, 0x03, 0x09 → U+2801, U+2803, U+2809.
		def fake(text, cursorOffset=None, brailleTable=None):
			return ([0x01, 0x03, 0x09], [0, 1, 2], None)

		with self._withFakeUtilsBraille(fake):
			output, offsets, cursor = callbackServer._translateText("hi!", None)

		self.assertEqual(output, "⠁⠃⠉")
		self.assertEqual(offsets, [0, 1, 2])
		# brailleCursorPos None passes through; the COM method handles
		# "no cursor" by NOT writing back through the cursorOffset
		# pointer rather than picking a sentinel int.
		self.assertIsNone(cursor)

	def test_cursorPositionIsForwarded(self) -> None:
		"""When ``cursorOffset`` is non-None, the helper passes it through
		to ``utils.braille.translateTextWithCursor`` (clamped to range) and
		returns the braille-space cursor as the third tuple element.
		"""
		from addon.tactileDisplayAPI import callbackServer

		passed: dict[str, object] = {}

		def fake(text, cursorOffset=None, brailleTable=None):
			passed["text"] = text
			passed["cursorOffset"] = cursorOffset
			# Echo cursor back in braille-space; for a simple test the
			# input cursor maps 1:1.
			return ([0x07, 0x0F], [0, 1], cursorOffset)

		with self._withFakeUtilsBraille(fake):
			_output, _offsets, cursor = callbackServer._translateText("ab", 1)

		self.assertEqual(passed["text"], "ab")
		self.assertEqual(passed["cursorOffset"], 1)
		self.assertEqual(cursor, 1)

	def test_cursorClampedToInputLength(self) -> None:
		"""A cursor past the end of the input is clamped to ``len(text)``
		before being forwarded to the utility.
		"""
		from addon.tactileDisplayAPI import callbackServer

		passed: dict[str, object] = {}

		def fake(text, cursorOffset=None, brailleTable=None):
			passed["cursorOffset"] = cursorOffset
			return ([0x01], [0], cursorOffset)

		with self._withFakeUtilsBraille(fake):
			callbackServer._translateText("ab", 999)

		self.assertEqual(passed["cursorOffset"], 2)  # clamped to len("ab")

	def test_swallowsTranslationFault(self) -> None:
		"""If ``utils.braille.translateTextWithCursor`` raises, the helper
		returns ``("", [], None)`` rather than letting it reach the library.
		"""
		from addon.tactileDisplayAPI import callbackServer

		def boom(*_args, **_kwargs):
			raise RuntimeError("synthetic liblouis failure")

		with self._withFakeUtilsBraille(boom):
			result = callbackServer._translateText("hello", None)

		self.assertEqual(result, ("", [], None))


class TestGetTranslationComMethod(unittest.TestCase):
	"""The ``GetTranslation`` COM method delegates to ``_translateText``."""

	def _newInstance(self):
		from addon.tactileDisplayAPI.callbackServer import TactileDisplayCallbacks

		return TactileDisplayCallbacks(
			renderTactile=lambda data: None,
			renderBraille=lambda data: None,
		)

	@staticmethod
	def _newCursorPointer(value: int) -> object:
		import ctypes

		# ctypes.pointer(c_long(value)) → POINTER(c_long) we can deref later
		# in the test to confirm the COM method wrote back through it.
		return ctypes.pointer(ctypes.c_long(value))

	@staticmethod
	def _newOffsetsArray(size: int) -> object:
		import ctypes

		# (c_long * size)() → array; pointer-indexing-compatible.
		return (ctypes.c_long * size)()

	def test_methodDelegatesToHelper_fillsBothPointers(self) -> None:
		"""COM method invokes ``_translateText`` with input + cursor,
		then writes the braille-to-raw array into ``originalOffsets``
		and the braille cursor position back through ``cursorOffset``.
		Returns just the output BSTR.
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI import callbackServer

		instance = self._newInstance()
		offsetsBuf = self._newOffsetsArray(3)
		cursorPtr = self._newCursorPointer(2)  # input cursor at position 2

		with patch.object(
			callbackServer,
			"_translateText",
			return_value=("⠁⠃⠉", [0, 1, 2], 1),
		) as helper:
			output = instance.GetTranslation("hello", offsetsBuf, cursorPtr)

		self.assertEqual(output, "⠁⠃⠉")
		# Helper was called with the unwrapped int from cursorPtr (not the pointer itself).
		helper.assert_called_once_with("hello", 2)
		# originalOffsets array got brailleToRawPos written into it.
		self.assertEqual([offsetsBuf[i] for i in range(3)], [0, 1, 2])
		# cursorOffset pointer got the translated cursor (1) written back.
		self.assertEqual(cursorPtr.contents.value, 1)

	def test_outputClampedToVendorBufferSize(self) -> None:
		"""Output + originalOffsets are clamped to ``4 * len(input) + 4095`` (the
		library's buffer size), so the fill can't overrun it.

		Here the 1-char input gives a 4099-cell cap; the translation yields 4100
		cells, so the last cell (and its offset) is dropped and the cursor that
		landed on the clamped-out cell is discarded.
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI import callbackServer

		instance = self._newInstance()
		inputText = "a"  # len 1 → cap = 4 * 1 + 4095 = 4099
		cap = 4 * len(inputText) + 4095
		overLong = cap + 1  # 4100 cells: one past the vendor buffer
		# Library allocation for this input: 4 * len + 4096 ints.
		offsetsBuf = self._newOffsetsArray(4 * len(inputText) + 4096)
		cursorPtr = self._newCursorPointer(cap)  # cursor on the clamped-out cell

		with patch.object(
			callbackServer,
			"_translateText",
			return_value=("⠿" * overLong, list(range(overLong)), cap),
		):
			output = instance.GetTranslation(inputText, offsetsBuf, cursorPtr)

		# Returned braille truncated to the cap.
		self.assertEqual(len(output), cap)
		# Exactly ``cap`` offsets written, in order — no overrunning write.
		self.assertEqual([offsetsBuf[i] for i in range(cap)], list(range(cap)))
		# The slot one past the cap was never written.
		self.assertEqual(offsetsBuf[cap], 0)
		# Cursor landed on the clamped-out cell (>= cap) → dropped, not written.
		self.assertEqual(cursorPtr.contents.value, cap)

	def test_expandedUnmappedCharsNotTruncated(self) -> None:
		"""A multi-cell expansion of an unmapped character is NOT truncated: an
		8-cell expansion of a 1-char input is well under the 4099-cell cap, so it
		passes through intact.
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI import callbackServer

		instance = self._newInstance()
		inputText = "￼"  # one embedded-object placeholder, len 1
		expanded = 8  # liblouis \xNNNN fallback ≈ 8 cells
		offsetsBuf = self._newOffsetsArray(4 * len(inputText) + 4096)
		cursorPtr = self._newCursorPointer(0)

		with patch.object(
			callbackServer,
			"_translateText",
			return_value=("⠿" * expanded, list(range(expanded)), None),
		):
			output = instance.GetTranslation(inputText, offsetsBuf, cursorPtr)

		# Not truncated: all 8 expansion cells survive.
		self.assertEqual(len(output), expanded)
		self.assertEqual([offsetsBuf[i] for i in range(expanded)], list(range(expanded)))

	def test_nullOriginalOffsetsSkipsArrayWrite(self) -> None:
		"""When the library passes NULL for ``originalOffsets``, the COM
		method skips the array write without raising — the brailleToRawPos
		data is just dropped.
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI import callbackServer

		instance = self._newInstance()
		cursorPtr = self._newCursorPointer(0)

		with patch.object(
			callbackServer,
			"_translateText",
			return_value=("⠁", [0], 0),
		):
			# Should NOT raise even though originalOffsets is None.
			output = instance.GetTranslation("h", None, cursorPtr)

		self.assertEqual(output, "⠁")
		self.assertEqual(cursorPtr.contents.value, 0)

	def test_nullCursorPointerIsNoneToHelper(self) -> None:
		"""When the library passes Python None for ``cursorOffset``, the
		method passes ``None`` to ``_translateText`` and skips writing
		back. The brailleToRawPos write still happens.
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI import callbackServer

		instance = self._newInstance()
		offsetsBuf = self._newOffsetsArray(1)

		with patch.object(
			callbackServer,
			"_translateText",
			return_value=("⠁", [0], None),
		) as helper:
			instance.GetTranslation("anything", offsetsBuf, None)
		helper.assert_called_once_with("anything", None)
		self.assertEqual(offsetsBuf[0], 0)

	def test_nullCtypesPointerIsNoneToHelper(self) -> None:
		"""When the library passes a NULL ctypes pointer (not Python None)
		for ``cursorOffset``, ``_coerceCursorPointer`` defends against
		``ValueError: NULL pointer access`` and the method passes ``None``
		to the helper, then skips writing back.
		"""
		import ctypes
		from unittest.mock import patch

		from addon.tactileDisplayAPI import callbackServer

		instance = self._newInstance()
		offsetsBuf = self._newOffsetsArray(1)
		nullPtr = ctypes.POINTER(ctypes.c_long)()  # NULL

		with patch.object(
			callbackServer,
			"_translateText",
			return_value=("⠁", [0], None),
		) as helper:
			instance.GetTranslation("anything", offsetsBuf, nullPtr)
		helper.assert_called_once_with("anything", None)

	def test_validCtypesPointerIsDereferenced(self) -> None:
		"""Non-NULL ``POINTER(c_long)`` for ``cursorOffset`` is dereferenced
		on read and gets the translated cursor written back on return.
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI import callbackServer

		instance = self._newInstance()
		offsetsBuf = self._newOffsetsArray(1)
		cursorPtr = self._newCursorPointer(5)  # IN: input cursor at position 5

		with patch.object(
			callbackServer,
			"_translateText",
			return_value=("⠁", [0], 3),  # liblouis translates 5 → 3 in braille
		) as helper:
			instance.GetTranslation("hi", offsetsBuf, cursorPtr)
		helper.assert_called_once_with("hi", 5)
		# OUT: cursorPtr now holds the translated cursor.
		self.assertEqual(cursorPtr.contents.value, 3)

	def test_shutdownShortCircuits(self) -> None:
		"""After ``setShuttingDown()``, GetTranslation returns an empty
		string without invoking the helper and without writing through
		the OUT pointers.
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI import callbackServer

		instance = self._newInstance()
		offsetsBuf = self._newOffsetsArray(3)
		cursorPtr = self._newCursorPointer(99)  # sentinel: should stay 99
		instance.setShuttingDown()

		with patch.object(callbackServer, "_translateText") as helper:
			output = instance.GetTranslation("hello", offsetsBuf, cursorPtr)

		self.assertEqual(output, "")
		helper.assert_not_called()
		# Pointers untouched by the short-circuit path.
		self.assertEqual(cursorPtr.contents.value, 99)
		self.assertEqual([offsetsBuf[i] for i in range(3)], [0, 0, 0])


if __name__ == "__main__":
	unittest.main()
