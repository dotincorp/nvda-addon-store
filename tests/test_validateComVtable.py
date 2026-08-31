# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Unit tests for the pure layers of tools/validateComVtable.py.

Invariants
----------
- No DLL, no comtypes, no NVDA import required.
- Tests run with ``python -m unittest tests.test_validateComVtable`` on any
  machine with Python 3.11+ and the repo root on sys.path.
- Exercises: AST decoder, strict comparison, advisory comparison, allowlist
  suppression, scaffold rendering, typelib-absent classification.
- The impure layer (``extract_typelib``, ``read_dll_version``) is NOT tested
  here — it depends on a Windows 64-bit environment with comtypes installed.
"""

from __future__ import annotations

import unittest

from tools.validateComVtable import (
	KNOWN_DEVIATIONS,
	ParamRecord,
	ScaffoldBlock,
	VtableRecord,
	classify_strict_drift,
	compare_vtable_interface,
	format_scaffold_output,
	scaffold_method,
	parse_cominterface,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_MINIMAL_COMINTERFACE = """\
from comtypes import COMMETHOD, HRESULT
from ctypes import c_int, c_long, POINTER

class ITactileDisplayAPI:
    _methods_ = [
        # Slot 7
        COMMETHOD([], c_int, "Connect", (["in"], c_int, "preference")),
        # Slot 8
        COMMETHOD([], HRESULT, "Disconnect"),
        # Slot 9
        COMMETHOD([], HRESULT, "SetBrailleTables",
            (["in"], POINTER(c_long), "table")),
        # Slot 10
        COMMETHOD([], HRESULT, "Show"),
    ]

class ITactileDisplayCallbacks:
    _methods_ = [
        # Slot 7
        COMMETHOD([], HRESULT, "TactileDisplayUpdated",
            (["in"], POINTER(c_int), "data"),
            (["in"], c_long, "length")),
        # Slot 8
        COMMETHOD([], HRESULT, "GetTranslation",
            (["in"], POINTER(c_long), "cursorOffset")),
    ]
"""


def _makeRecord(
	listIndex: int,
	name: str,
	returnType: str = "HRESULT",
	params: tuple[ParamRecord, ...] = (),
	slotBase: int = 7,
) -> VtableRecord:
	return VtableRecord(
		listIndex=listIndex,
		slot=slotBase + listIndex,
		name=name,
		returnType=returnType,
		params=params,
	)


# ---------------------------------------------------------------------------
# TestAstDecoder
# ---------------------------------------------------------------------------


class TestAstDecoder(unittest.TestCase):
	"""``parse_cominterface`` extracts VtableRecords from source strings."""

	def test_parsesMethodNames(self) -> None:
		result = parse_cominterface(_MINIMAL_COMINTERFACE)
		self.assertIn("ITactileDisplayAPI", result)
		names = [r.name for r in result["ITactileDisplayAPI"]]
		self.assertEqual(names, ["Connect", "Disconnect", "SetBrailleTables", "Show"])

	def test_parsesCallbackClass(self) -> None:
		result = parse_cominterface(_MINIMAL_COMINTERFACE)
		self.assertIn("ITactileDisplayCallbacks", result)
		names = [r.name for r in result["ITactileDisplayCallbacks"]]
		self.assertEqual(names, ["TactileDisplayUpdated", "GetTranslation"])

	def test_cIntReturnType(self) -> None:
		result = parse_cominterface(_MINIMAL_COMINTERFACE)
		connect = result["ITactileDisplayAPI"][0]
		self.assertEqual(connect.name, "Connect")
		self.assertEqual(connect.returnType, "c_int")

	def test_pointerParamType(self) -> None:
		result = parse_cominterface(_MINIMAL_COMINTERFACE)
		setBraille = result["ITactileDisplayAPI"][2]
		self.assertEqual(len(setBraille.params), 1)
		self.assertEqual(setBraille.params[0].typeName, "POINTER(c_long)")

	def test_outDirectionParam(self) -> None:
		source = """\
from comtypes import COMMETHOD, HRESULT
from ctypes import c_int, POINTER

class ITactileDisplayAPI:
    _methods_ = [
        COMMETHOD([], HRESULT, "GetDimensions",
            (["out"], POINTER(c_int), "dotsX"),
            (["out"], POINTER(c_int), "dotsY")),
    ]
"""
		result = parse_cominterface(source)
		getDims = result["ITactileDisplayAPI"][0]
		self.assertEqual(getDims.params[0].direction, "out")
		self.assertEqual(getDims.params[1].direction, "out")

	def test_slotBaseIsTactileDisplayAPI(self) -> None:
		result = parse_cominterface(_MINIMAL_COMINTERFACE)
		self.assertEqual(result["ITactileDisplayAPI"][0].slot, 7)  # index 0 + base 7
		self.assertEqual(result["ITactileDisplayAPI"][3].slot, 10)  # index 3 + base 7

	def test_slotBaseIsCallbacks(self) -> None:
		result = parse_cominterface(_MINIMAL_COMINTERFACE)
		self.assertEqual(result["ITactileDisplayCallbacks"][0].slot, 3)  # index 0 + base 3

	def test_listIndexMatchesPosition(self) -> None:
		result = parse_cominterface(_MINIMAL_COMINTERFACE)
		for idx, rec in enumerate(result["ITactileDisplayAPI"]):
			self.assertEqual(rec.listIndex, idx)

	def test_emptyParams(self) -> None:
		result = parse_cominterface(_MINIMAL_COMINTERFACE)
		disconnect = result["ITactileDisplayAPI"][1]
		self.assertEqual(disconnect.params, ())


# ---------------------------------------------------------------------------
# TestStrictComparison
# ---------------------------------------------------------------------------


class TestStrictComparison(unittest.TestCase):
	"""``classify_strict_drift`` reports correct findings for divergent vtables."""

	def _api(self, names: list[str]) -> tuple[VtableRecord, ...]:
		return tuple(_makeRecord(i, n) for i, n in enumerate(names))

	def test_inSyncReturnsEmpty(self) -> None:
		names = ["Connect", "Disconnect", "Show"]
		declared = self._api(names)
		typelib = self._api(names)
		self.assertEqual(classify_strict_drift("ITactileDisplayAPI", declared, typelib), [])

	def test_appendedMethod(self) -> None:
		declared = self._api(["Connect", "Disconnect"])
		typelib = self._api(["Connect", "Disconnect", "NewMethod"])
		findings = classify_strict_drift("ITactileDisplayAPI", declared, typelib)
		self.assertEqual(len(findings), 1)
		self.assertEqual(findings[0].typelibName, "NewMethod")
		self.assertEqual(findings[0].classification, "new_appended")

	def test_midInsertShift(self) -> None:
		declared = self._api(["Connect", "Disconnect", "Show"])
		typelib = self._api(["Connect", "NewMiddle", "Disconnect", "Show"])
		findings = classify_strict_drift("ITactileDisplayAPI", declared, typelib)
		# At index 1 declared="Disconnect", typelib="NewMiddle" → mid-insert
		self.assertTrue(any(f.classification == "new_mid_insert" for f in findings))

	def test_removedMethod(self) -> None:
		declared = self._api(["Connect", "Disconnect", "Show"])
		typelib = self._api(["Connect", "Show"])
		findings = classify_strict_drift("ITactileDisplayAPI", declared, typelib)
		self.assertTrue(any(f.classification == "removed" for f in findings))

	def test_reorderedMethod(self) -> None:
		declared = self._api(["Connect", "Alpha", "Beta"])
		typelib = self._api(["Connect", "Beta", "Alpha"])
		findings = classify_strict_drift("ITactileDisplayAPI", declared, typelib)
		self.assertTrue(len(findings) > 0)

	def test_slotNumberInFinding(self) -> None:
		declared = self._api(["Connect"])
		typelib = self._api(["Connect", "New"])
		findings = classify_strict_drift("ITactileDisplayAPI", declared, typelib)
		self.assertEqual(findings[0].slot, 8)  # index 1 + base 7


# ---------------------------------------------------------------------------
# TestAllowlist
# ---------------------------------------------------------------------------


class TestAllowlist(unittest.TestCase):
	"""``compare_vtable_interface`` suppresses known deviations correctly."""

	def _makeConnectPair(self) -> tuple[tuple[VtableRecord, ...], tuple[VtableRecord, ...]]:
		"""Connect: declared returns c_int, typelib would report HRESULT."""
		declared = (_makeRecord(0, "Connect", returnType="c_int"),)
		typelib = (_makeRecord(0, "Connect", returnType="HRESULT"),)
		return declared, typelib

	def test_connectReturnTypeSuppressed(self) -> None:
		declared, typelib = self._makeConnectPair()
		report = compare_vtable_interface("ITactileDisplayAPI", declared, typelib, KNOWN_DEVIATIONS)
		# No strict findings (names match)
		self.assertEqual(report.strictFindings, ())
		# Advisory should NOT contain Connect return_type (suppressed)
		advisory_fields = [f.field for f in report.advisoryFindings if f.methodName == "Connect"]
		self.assertNotIn("return_type", advisory_fields)
		# Suppressed count should be > 0
		self.assertGreater(report.suppressedCount, 0)

	def test_nonAllowlistedDeviationIsReported(self) -> None:
		"""A deviation not in the allowlist DOES appear as advisory."""
		declared = (_makeRecord(0, "Show", returnType="c_int"),)
		typelib = (_makeRecord(0, "Show", returnType="HRESULT"),)
		report = compare_vtable_interface("ITactileDisplayAPI", declared, typelib, KNOWN_DEVIATIONS)
		advisory_fields = [f.field for f in report.advisoryFindings if f.methodName == "Show"]
		self.assertIn("return_type", advisory_fields)

	def test_typelibAbsentCallbackIsVerifyNotRemove(self) -> None:
		"""GetTranslation absent from typelib → advisory 'verify', not StrictFinding 'removed'."""
		param = ParamRecord(direction="in", typeName="POINTER(c_long)", paramName="cursorOffset")
		declared = (
			_makeRecord(0, "TactileDisplayUpdated", slotBase=3),
			_makeRecord(1, "BrailleDisplayUpdated", slotBase=3),
			VtableRecord(listIndex=2, slot=5, name="GetTranslation", returnType="HRESULT", params=(param,)),
		)
		# Typelib only exposes first 2 (v1.20 typelib under-reports)
		typelib = (
			_makeRecord(0, "TactileDisplayUpdated", slotBase=3),
			_makeRecord(1, "BrailleDisplayUpdated", slotBase=3),
		)
		report = compare_vtable_interface("ITactileDisplayCallbacks", declared, typelib, KNOWN_DEVIATIONS)
		# Should NOT be a strict "removed" finding
		removed_names = [f.declaredName for f in report.strictFindings if f.classification == "removed"]
		self.assertNotIn("GetTranslation", removed_names)
		# Should be suppressed (typelib_absent allowlist entry)
		self.assertGreater(report.suppressedCount, 0)

	def test_inSyncWhenNamesMatch(self) -> None:
		declared = (_makeRecord(0, "Connect"), _makeRecord(1, "Disconnect"))
		typelib = (_makeRecord(0, "Connect"), _makeRecord(1, "Disconnect"))
		report = compare_vtable_interface("ITactileDisplayAPI", declared, typelib, KNOWN_DEVIATIONS)
		self.assertTrue(report.inSync)
		self.assertEqual(report.strictFindings, ())


# ---------------------------------------------------------------------------
# TestScaffold
# ---------------------------------------------------------------------------


class TestScaffold(unittest.TestCase):
	"""``scaffold_method`` generates correct COMMETHOD declarations."""

	def _newMethod(
		self,
		name: str,
		returnType: str = "HRESULT",
		params: tuple[ParamRecord, ...] = (),
	) -> VtableRecord:
		return VtableRecord(listIndex=0, slot=7, name=name, returnType=returnType, params=params)

	def test_slotCommentPresent(self) -> None:
		record = self._newMethod("NewMethod")
		block = scaffold_method(record, slotBase=7)
		self.assertIn("# Slot 7", block.commethodText)

	def test_methodNameInCommethod(self) -> None:
		record = self._newMethod("SetHybridMode")
		block = scaffold_method(record, slotBase=7)
		self.assertIn('"SetHybridMode"', block.commethodText)

	def test_knownTypeNoReviewComment(self) -> None:
		param = ParamRecord(direction="in", typeName="c_int", paramName="flag")
		record = self._newMethod("Enable", params=(param,))
		block = scaffold_method(record, slotBase=7)
		self.assertFalse(block.hasUnknownTypes)
		self.assertNotIn("# REVIEW:", block.commethodText)

	def test_unknownTypeHasReviewComment(self) -> None:
		param = ParamRecord(direction="in", typeName="SomeObscureType", paramName="data")
		record = self._newMethod("WeirdMethod", params=(param,))
		block = scaffold_method(record, slotBase=7)
		self.assertTrue(block.hasUnknownTypes)
		self.assertIn("# REVIEW:", block.commethodText)

	def test_wrapperTextCamelCase(self) -> None:
		record = self._newMethod("SetHybridMode")
		block = scaffold_method(record, slotBase=7)
		self.assertIn("setHybridMode", block.wrapperText)

	def test_wrapperTextContainsMethodName(self) -> None:
		record = self._newMethod("SetHybridMode")
		block = scaffold_method(record, slotBase=7)
		self.assertIn("SetHybridMode", block.wrapperText)

	def test_formatScaffoldEmptyIsNothingMessage(self) -> None:
		self.assertEqual(format_scaffold_output([]), "no new methods — nothing to scaffold")

	def test_formatScaffoldHasBanner(self) -> None:
		record = self._newMethod("NewMethod")
		block = scaffold_method(record, slotBase=7)
		namedBlock = ScaffoldBlock(
			interfaceName="ITactileDisplayAPI",
			slot=block.slot,
			commethodText=block.commethodText,
			wrapperText=block.wrapperText,
			hasUnknownTypes=block.hasUnknownTypes,
		)
		output = format_scaffold_output([namedBlock])
		self.assertIn("SCAFFOLD", output)
		self.assertIn("REVIEW REQUIRED", output)


if __name__ == "__main__":
	unittest.main()
