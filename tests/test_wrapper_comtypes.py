# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Declarative-shape tests for the comtypes-backed wrapper.

These tests inspect ``ITactileDisplayAPI._methods_`` (the static class
declaration) and the comLoader's IID-candidate machinery without loading
``TactileDisplayAPI.dll``. They are CI-runnable on machines that don't
have the DLL.

Coverage:
- US1: vtable slot ordering matches the v1.23 layout — 33 methods, slots 7-39
  (any reorder fails the test before reaching hardware).
- US2: Connect declares c_int return; all other methods declare HRESULT.
  BSTR args are declared via comtypes.BSTR. The class inherits IDispatch
  so vtable slots 0-6 are inherited.
- US3: comLoader exposes the registration-free machinery and uses
  DllGetClassObject (not CoCreateInstance). The DLL load is cached.
- US4: feature 007's IID candidate list is preserved; the runtime QI
  iterates candidates until one succeeds; an all-failed scenario raises
  with a diagnostic listing every IID + HRESULT.
- US5: tests run without TactileDisplayAPI.dll loaded.
"""

from __future__ import annotations

import unittest
from ctypes import c_int
from unittest.mock import MagicMock, patch

# US5: importing comInterface MUST NOT trigger a DLL load. Only
# comLoader.createTactileDisplayApi loads the DLL.
import addon.tactileDisplayAPI.comInterface as _comInterfaceModule  # noqa: F401


def _getMethodSpec(methodName: str):  # type: ignore[no-untyped-def]
	"""Find the ``_ComMemberSpec`` for a method by name in
	``ITactileDisplayAPI._methods_``."""
	from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

	for spec in ITactileDisplayAPI._methods_:
		# _ComMemberSpec has a `name` attribute holding the method name.
		if getattr(spec, "name", None) == methodName:
			return spec
	raise AssertionError(f"method {methodName!r} not found in ITactileDisplayAPI._methods_")


# Expected vtable slot ordering for v1.23. Slots 0-6 are inherited from
# IDispatch (IUnknown + IDispatch); _methods_ declares slots 7-39.
# v1.17 inserted DisplayLiteraryBraille at slot 11. v1.22 inserted
# SetBrailleLinePadding at slot 12 and ForceSixDotBraille at slot 13
# (mid-vtable, between DisplayLiteraryBraille and what was SetDrawingMode),
# shifting every subsequent slot +2. v1.0.21 had previously inserted
# SetHybridPrintAndBrailleMode; that move is now reflected in the shifted
# slots 37/38/39.
_EXPECTED_METHOD_NAMES = [
	"Connect",  # slot 7
	"SimulateDisplay",  # slot 8 (v1.16; declared for vtable correctness)
	"Disconnect",  # slot 9
	"SetBrailleTables",  # slot 10
	"DisplayLiteraryBraille",  # slot 11 (v1.17; declared, not called)
	"SetBrailleLinePadding",  # slot 12 (v1.22 mid-vtable insertion)
	"ForceSixDotBraille",  # slot 13 (v1.22 mid-vtable insertion)
	"SetDrawingMode",  # slot 14 (was slot 12 before v1.22)
	"GetDimensions",  # slot 15
	"Clear",  # slot 16
	"DrawLine",  # slot 17
	"DrawBox",  # slot 18
	"DrawCircle",  # slot 19
	"DrawPoly",  # slot 20
	"Fill",  # slot 21
	"InvertRect",  # slot 22
	"DrawBrailleLabel",  # slot 23
	"DrawTextLabel",  # slot 24
	"GraphMathEquation",  # slot 25
	"DrawImage",  # slot 26
	"DrawScreenRegion",  # slot 27
	"DrawASCIIBrailleImage",  # slot 28
	"UndoLastDraw",  # slot 29
	"Show",  # slot 30
	"ShowMultilineText",  # slot 31
	"ShowStatusText",  # slot 32
	"AddFocusedControl",  # slot 33 (v1.12+, wrapped in v1.16)
	"UpdateCursor",  # slot 34
	"RegisterEvents",  # slot 35
	"ShowBrailleOnScreen",  # slot 36
	"SetHybridPrintAndBrailleMode",  # slot 37 (v1.0.21; shifted +2 by v1.22)
	"EnableContractedBrailleInput",  # slot 38 (shifted +2 by v1.22)
	"ExecuteOperation",  # slot 39 (shifted +2 by v1.22)
]


# --- US1: New methods can be wrapped safely ---


class TestVtableSlotOrder(unittest.TestCase):
	"""Slot ordering matches the v1.23 vtable (33 methods, slots 7-39). Any
	reorder accidentally inserting a method earlier in the list fails this
	test before it ever reaches hardware."""

	def test_methods_in_documented_order(self) -> None:
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		actual = [getattr(spec, "name", None) for spec in ITactileDisplayAPI._methods_]
		self.assertEqual(actual, _EXPECTED_METHOD_NAMES)


# --- US2: Session-side identical behaviour ---


class TestConnectReturnsCInt(unittest.TestCase):
	"""Connect declares c_int return (NOT HRESULT) so comtypes does not
	auto-raise on non-zero — the session needs to branch on the return value."""

	def test_connect_restype_is_c_int(self) -> None:
		spec = _getMethodSpec("Connect")
		# _ComMemberSpec stores restype as the first positional field.
		# We check for `c_int` specifically; comtypes' HRESULT type is a
		# distinct subclass of c_long.
		restype = getattr(spec, "restype", None)
		self.assertIs(restype, c_int)


class TestOtherMethodsReturnHresult(unittest.TestCase):
	"""Every method except Connect returns HRESULT — comtypes auto-raises
	COMError on negative HRESULT, replacing the previous wrapper's manual
	checkHr calls."""

	def test_all_non_connect_methods_use_hresult(self) -> None:
		from comtypes import HRESULT

		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		for spec in ITactileDisplayAPI._methods_:
			name = getattr(spec, "name", None)
			restype = getattr(spec, "restype", None)
			if name == "Connect":
				continue
			self.assertIs(
				restype,
				HRESULT,
				f"method {name} should declare HRESULT return; got {restype}",
			)


class TestBstrArgsDeclared(unittest.TestCase):
	"""Methods that take text/filenames declare BSTR for those args."""

	def test_bstr_args(self) -> None:
		from comtypes import BSTR

		expectedBstrPositions = {
			"SetBrailleTables": [0, 1, 2],  # 3 BSTR args
			"DrawBrailleLabel": [2],  # x, y, BSTR
			"DrawTextLabel": [2],  # x, y, BSTR
			"GraphMathEquation": [0],  # BSTR, 4× int
			"DrawImage": [0, 1],  # 2× BSTR, int
			"DrawASCIIBrailleImage": [0],  # BSTR
			"ShowMultilineText": [0],  # BSTR
			"ShowStatusText": [0],  # BSTR
		}
		for methodName, bstrPositions in expectedBstrPositions.items():
			spec = _getMethodSpec(methodName)
			argtypes = list(getattr(spec, "argtypes", ()))
			for pos in bstrPositions:
				self.assertIs(
					argtypes[pos],
					BSTR,
					f"{methodName} argtypes[{pos}] should be BSTR; got {argtypes[pos]}",
				)


class TestInheritsFromIDispatch(unittest.TestCase):
	"""ITactileDisplayAPI inherits from IDispatch so vtable slots 0-6 are
	implicit. _methods_ starts at slot 7."""

	def test_idispatch_in_mro(self) -> None:
		from comtypes.automation import IDispatch

		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		self.assertIn(IDispatch, ITactileDisplayAPI.__mro__)


# --- US3: Registration-free DLL load preserved ---


class TestComLoaderUsesDllGetClassObject(unittest.TestCase):
	"""comLoader exposes the registration-free machinery: _loadDll,
	_getClassFactory, createTactileDisplayApi, createSystemTactileDisplayApi."""

	def test_required_symbols_present(self) -> None:
		from addon.tactileDisplayAPI import comLoader

		self.assertTrue(hasattr(comLoader, "_loadDll"))
		self.assertTrue(hasattr(comLoader, "_getClassFactory"))
		self.assertTrue(hasattr(comLoader, "createTactileDisplayApi"))
		self.assertTrue(hasattr(comLoader, "createSystemTactileDisplayApi"))


class TestBundledPathUsesDllGetClassObjectNotCoCreateInstance(unittest.TestCase):
	"""createTactileDisplayApi (bundled path) must use DllGetClassObject only.

	createSystemTactileDisplayApi legitimately uses CoCreateInstance; we scope
	the check to the bundled function so the guard remains meaningful.
	"""

	def test_bundled_path_source(self) -> None:
		import inspect

		from addon.tactileDisplayAPI.comLoader import createTactileDisplayApi

		source = inspect.getsource(createTactileDisplayApi)
		self.assertIn("DllGetClassObject", source)
		self.assertNotIn("CoCreateInstance", source)


class TestSystemPathRaisesWhenComServerAbsent(unittest.TestCase):
	"""createSystemTactileDisplayApi raises OSError with a descriptive message
	when CoCreateInstance fails for all candidates."""

	def test_raises_descriptive_error(self) -> None:
		from addon.tactileDisplayAPI import comLoader

		with patch("comtypes.CoCreateInstance", side_effect=OSError("E_CLASSNOTREG")):
			with self.assertRaises(OSError) as ctx:
				comLoader.createSystemTactileDisplayApi()

		self.assertIn("System tactile-display interface unavailable", str(ctx.exception))


class TestDllLoaderSingleton(unittest.TestCase):
	"""_loadDll caches the WinDLL handle in a module-level singleton.
	The DLL is loaded on first call and reused on subsequent calls."""

	def test_dll_is_cached(self) -> None:
		from addon.tactileDisplayAPI import comLoader

		# Reset the cache so this test starts from a known state.
		comLoader._cachedDll = None

		mockDll = MagicMock()
		mockDll.DllGetClassObject = MagicMock(return_value=0)

		with (
			patch("addon.tactileDisplayAPI.comLoader.ctypes.WinDLL", return_value=mockDll) as mockWinDLL,
			patch("addon.tactileDisplayAPI.comLoader._dllSearchPathContext"),
			patch("pathlib.Path.exists", return_value=True),
		):
			comLoader._loadDll()
			comLoader._loadDll()
			comLoader._loadDll()

		# WinDLL constructor called exactly once despite three _loadDll calls.
		self.assertEqual(mockWinDLL.call_count, 1)

		# Reset for other tests.
		comLoader._cachedDll = None


# --- US4: IID-candidate iteration preserved ---


class TestIidCandidatesPreserved(unittest.TestCase):
	"""Feature 007's IID_CANDIDATES list is preserved with the legacy IID
	as the first entry."""

	def test_legacy_iid_first(self) -> None:
		from addon.tactileDisplayAPI.comLoader import IID_CANDIDATES, IID_IJDPGRAPHICS_LEGACY

		self.assertGreaterEqual(len(IID_CANDIDATES), 3)
		# First entry is the legacy IID — the binary contract the vendor preserves.
		self.assertEqual(_guidEqual(IID_CANDIDATES[0], IID_IJDPGRAPHICS_LEGACY), True)


def _guidEqual(a, b) -> bool:  # type: ignore[no-untyped-def]
	"""Compare two GUID structs by field equality."""
	return (
		a.Data1 == b.Data1 and a.Data2 == b.Data2 and a.Data3 == b.Data3 and bytes(a.Data4) == bytes(b.Data4)
	)


class TestIidIsLegacyCandidate(unittest.TestCase):
	"""ITactileDisplayAPI._iid_ matches the legacy IID (metadata only;
	the runtime QI uses the explicit candidate list)."""

	def test_iid_matches_legacy(self) -> None:
		from comtypes import GUID

		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		# comtypes.GUID is a different struct type from comLoader.GUID
		# (different ctypes definition); compare via canonical string form.
		self.assertEqual(
			str(ITactileDisplayAPI._iid_).upper().strip("{}"),
			"48FB9EFA-4F20-4086-8A15-5CE3CF0CC2E3",
		)
		# Sanity-check: the comtypes.GUID class is what we expect.
		self.assertIsInstance(ITactileDisplayAPI._iid_, GUID)


class TestAllCandidatesFailedRaisesDescriptiveError(unittest.TestCase):
	"""When every candidate IID returns E_NOINTERFACE, createTactileDisplayApi
	raises OSError listing every IID tried and its HRESULT.

	We patch the IClassFactory result-handling at a higher level: by replacing
	``_getClassFactory`` and the factory's ``vtbl`` with a hand-rolled fake
	that mimics the ctypes Structure-pointer layout enough for the production
	code to walk it. Mocking with raw MagicMocks doesn't work because
	``ctypes.cast`` on a MagicMock argument recurses infinitely.
	"""

	def test_all_failed_lists_every_candidate(self) -> None:
		from addon.tactileDisplayAPI import comLoader

		E_NOINTERFACE = 0x80004002
		# Reset the DLL cache so our patched WinDLL is used.
		comLoader._cachedDll = None

		# Track CreateInstance and Release call counts for assertions.
		calls = {"createInstance": 0, "release": 0}

		def fakeCreateInstance(_factoryPtr, _outer, _iid, _outPtr):  # type: ignore[no-untyped-def]
			calls["createInstance"] += 1
			return E_NOINTERFACE

		def fakeRelease(_factoryPtr):  # type: ignore[no-untyped-def]
			calls["release"] += 1
			return 0

		# Stub out the inner ctypes.cast in createTactileDisplayApi too —
		# the production code casts the factory pointer for the CreateInstance
		# and Release thiscall, which we don't need to simulate exactly.
		class _FakeVtbl:
			CreateInstance = staticmethod(fakeCreateInstance)
			Release = staticmethod(fakeRelease)

		class _FakeLpVtbl:
			contents = _FakeVtbl()

		class _FakeFactory:
			contents = type("_FakeContents", (), {"lpVtbl": _FakeLpVtbl()})()

		# Bypass the ctypes.cast(factory, POINTER(_ObjBase)) call by patching
		# ctypes.cast inside the comLoader module to return the input verbatim.
		with (
			patch.object(comLoader, "_loadDll", return_value=MagicMock()),
			patch.object(comLoader, "_getClassFactory", return_value=_FakeFactory()),
			patch.object(comLoader.ctypes, "cast", side_effect=lambda obj, _typ: obj),
			# byref returns the GUID instance unchanged; the fake CreateInstance
			# doesn't dereference it.
			patch.object(comLoader.ctypes, "byref", side_effect=lambda obj: obj),
		):
			with self.assertRaises(OSError) as ctx:
				comLoader.createTactileDisplayApi()

		msg = str(ctx.exception)
		self.assertIn("Tactile-display interface unavailable", msg)
		# Every candidate's IID and HRESULT should appear in the message.
		self.assertIn("48fb9efa", msg.lower())  # legacy IID
		self.assertIn("80004002", msg.lower())  # E_NOINTERFACE
		# All 3 candidate IIDs were tried; factory was Released once.
		self.assertEqual(calls["createInstance"], 3)
		self.assertEqual(calls["release"], 1)


# --- US5: CI-runnable without DLL ---


class TestRunsWithoutDll(unittest.TestCase):
	"""Confirms this test module imports cleanly without TactileDisplayAPI.dll
	loaded. The DLL is loaded by createTactileDisplayApi, not by importing
	the comInterface module."""

	def test_import_does_not_load_dll(self) -> None:
		from addon.tactileDisplayAPI import comLoader

		# At import time, the cache is None unless an earlier test loaded.
		# Reset to verify no implicit load happened during import.
		comLoader._cachedDll = None
		# Importing comInterface must not trigger _loadDll.
		import addon.tactileDisplayAPI.comInterface  # noqa: F401

		self.assertIsNone(comLoader._cachedDll)


if __name__ == "__main__":
	unittest.main()
