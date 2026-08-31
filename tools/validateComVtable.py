# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Validate the hand-declared COM vtable in comInterface.py against the bundled DLL.

This tool compares ``addon/tactileDisplayAPI/comInterface.py``'s ``_methods_``
declarations against the vtable extracted from the bundled
``TactileDisplayAPI.dll`` via ``comtypes.client.GetModule``.

Two-layer architecture
----------------------
Pure layer (AST + comparison): no comtypes, no NVDA, runs anywhere.
  - ``parse_cominterface()`` — AST-decode ``_methods_`` lists.
  - ``classify_strict_drift()`` — name/count comparison.
  - ``compare_vtable_interface()`` — full per-interface report.
  - ``scaffold_method()`` / ``format_scaffold_output()`` — stub generation.

Impure layer (Windows, 64-bit Python, comtypes installed):
  - ``extract_typelib()`` — ``comtypes.client.GetModule`` against DLL.
  - ``read_dll_version()`` — PE FileVersion resource read.

Exit codes
----------
0  vtable in sync (or ``--scaffold`` with nothing to scaffold).
1  count/name-order drift detected (only under ``--check``; ``--strict``
   also exits 1 on unallowlisted signature differences).
2  environment or parse error (missing DLL, no comtypes, 32-bit Python,
   absent typelib, unparseable comInterface.py).

Usage
-----
python tools/validateComVtable.py                 # human-readable report
python tools/validateComVtable.py --check         # CI mode
python tools/validateComVtable.py --scaffold      # emit stubs for new methods
python tools/validateComVtable.py --dll PATH      # override DLL location
"""

from __future__ import annotations

import argparse
import ast
import ctypes
import logging
import re
import shutil
import struct
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

log = logging.getLogger("validateComVtable")

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_SYNC: Final[int] = 0
EXIT_DRIFT: Final[int] = 1
EXIT_ERROR: Final[int] = 2

# ---------------------------------------------------------------------------
# Slot base offsets (IUnknown+IDispatch=7 for ITactileDisplayAPI;
# IUnknown only=3 for ITactileDisplayCallbacks)
# ---------------------------------------------------------------------------

_SLOT_BASE: Final[dict[str, int]] = {
	"ITactileDisplayAPI": 7,
	"ITactileDisplayCallbacks": 3,
}
_DEFAULT_SLOT_BASE: Final[int] = 7


def _slotBase(interfaceName: str) -> int:
	return _SLOT_BASE.get(interfaceName, _DEFAULT_SLOT_BASE)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParamRecord:
	"""One parameter in a COM method signature."""

	direction: str  # "in", "out", or "in,out"
	typeName: str  # e.g. "c_int", "POINTER(c_long)", "BSTR"
	paramName: str


@dataclass(frozen=True, slots=True)
class VtableRecord:
	"""One COM method — produced by both AST-parse and typelib-extract layers."""

	listIndex: int  # zero-based position in _methods_
	slot: int  # vtable slot (listIndex + slotBase)
	name: str
	returnType: str  # e.g. "HRESULT", "c_int"
	params: tuple[ParamRecord, ...]


@dataclass(frozen=True, slots=True)
class KnownDeviation:
	"""One baked-in allowlist entry for a deliberate hand-deviation."""

	interfaceName: str
	methodName: str
	description: str
	kind: Literal["return_type", "param_type", "typelib_absent"]


@dataclass(frozen=True, slots=True)
class StrictFinding:
	"""A count or name-order divergence — fails ``--check``."""

	interfaceName: str
	listIndex: int
	slot: int
	declaredName: str | None  # None if absent from comInterface.py
	typelibName: str | None  # None if absent from typelib
	classification: Literal["new_appended", "new_mid_insert", "removed", "reordered", "count_mismatch"]


@dataclass(frozen=True, slots=True)
class AdvisoryFinding:
	"""A signature deviation not suppressed by the allowlist."""

	interfaceName: str
	methodName: str
	field: str  # e.g. "return_type", "param[2].type"
	declaredValue: str
	typelibValue: str


@dataclass(frozen=True, slots=True)
class InterfaceReport:
	"""Comparison result for one interface."""

	interfaceName: str
	declaredCount: int
	typelibCount: int
	strictFindings: tuple[StrictFinding, ...]
	advisoryFindings: tuple[AdvisoryFinding, ...]
	suppressedCount: int
	inSync: bool  # True iff strictFindings is empty


@dataclass(frozen=True, slots=True)
class ComparisonReport:
	"""Full report for both interfaces."""

	dllVersion: str  # PE FileVersion e.g. "v1.0.21" or "unknown"
	docstringVersion: str  # from comInterface.py module docstring
	interfaces: tuple[InterfaceReport, ...]
	overallInSync: bool


@dataclass(frozen=True, slots=True)
class ScaffoldBlock:
	"""Output of ``--scaffold`` for one new method."""

	interfaceName: str
	slot: int
	commethodText: str  # pasteable COMMETHOD declaration
	wrapperText: str  # pasteable wrapper.py facade skeleton
	hasUnknownTypes: bool


# ---------------------------------------------------------------------------
# Known-deviation allowlist
# ---------------------------------------------------------------------------

KNOWN_DEVIATIONS: dict[tuple[str, str], KnownDeviation] = {
	("ITactileDisplayAPI", "Connect"): KnownDeviation(
		interfaceName="ITactileDisplayAPI",
		methodName="Connect",
		description=(
			"Connect returns c_int, not HRESULT. The library uses the return value as a "
			"connection-attempt status code (0=success, non-zero=soft failure). "
			"comtypes HRESULT auto-raise would discard that value."
		),
		kind="return_type",
	),
	("ITactileDisplayCallbacks", "GetTranslation"): KnownDeviation(
		interfaceName="ITactileDisplayCallbacks",
		methodName="GetTranslation",
		description=(
			"GetTranslation: originalOffsets and cursorOffset are declared as POINTER(c_long) "
			"though the typelib reports value types; cursorOffset direction is [in] though it "
			"is INOUT per the vendor IDL. On x64 a pointer is 8 bytes vs 4 for a value — "
			"declaring as value type corrupts the stack frame. "
			"The v1.20 typelib also omits this method entirely (under-reports); "
			"the binary requires a 3-method vtable (hardware-confirmed)."
		),
		kind="typelib_absent",
	),
}

# ---------------------------------------------------------------------------
# Pure layer — AST parser
# ---------------------------------------------------------------------------


def _astNodeToTypeName(node: ast.expr) -> str:
	"""Convert an AST type node to its canonical string representation."""
	if isinstance(node, ast.Name):
		return node.id
	if isinstance(node, ast.Attribute):
		return f"{_astNodeToTypeName(node.value)}.{node.attr}"
	if isinstance(node, ast.Subscript):
		# e.g. POINTER(c_long), POINTER(BSTR)
		valueStr = _astNodeToTypeName(node.value)
		sliceNode = node.slice
		sliceStr = _astNodeToTypeName(sliceNode)
		return f"{valueStr}({sliceStr})"
	if isinstance(node, ast.Call):
		funcStr = _astNodeToTypeName(node.func)
		argsStr = ", ".join(_astNodeToTypeName(a) for a in node.args)
		return f"{funcStr}({argsStr})"
	if isinstance(node, ast.Constant):
		return repr(node.value)
	return ast.unparse(node)


def _parseParam(node: ast.expr) -> ParamRecord:
	"""Parse one (direction_list, type, name) tuple from a COMMETHOD argspec."""
	if not isinstance(node, ast.Tuple) or len(node.elts) < 2:
		return ParamRecord(direction="in", typeName=ast.unparse(node), paramName="?")
	directionNode = node.elts[0]
	typeNode = node.elts[1]
	nameNode = node.elts[2] if len(node.elts) > 2 else None

	# Direction: first element is a list of strings e.g. ["in"] or ["out"]
	direction = "in"
	if isinstance(directionNode, ast.List):
		dirs = [
			elt.value
			for elt in directionNode.elts
			if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
		]
		direction = ",".join(dirs) if dirs else "in"

	typeName = _astNodeToTypeName(typeNode)
	paramName = (
		nameNode.value if isinstance(nameNode, ast.Constant) and isinstance(nameNode.value, str) else "?"
	)
	return ParamRecord(direction=direction, typeName=typeName, paramName=paramName)


def _parseMethodsList(
	listNode: ast.List,
	interfaceName: str,
) -> tuple[VtableRecord, ...]:
	"""Parse a ``_methods_ = [...]`` list AST node into ``VtableRecord`` tuples."""
	slotBase = _slotBase(interfaceName)
	records: list[VtableRecord] = []
	for idx, elt in enumerate(listNode.elts):
		if not isinstance(elt, ast.Call):
			continue
		# COMMETHOD(flags, return_type, name, *params)
		args = elt.args
		if len(args) < 3:
			continue
		returnTypeNode = args[1]
		nameNode = args[2]
		if not isinstance(nameNode, ast.Constant) or not isinstance(nameNode.value, str):
			continue
		methodName = str(nameNode.value)
		returnType = _astNodeToTypeName(returnTypeNode)
		params = tuple(_parseParam(a) for a in args[3:])
		records.append(
			VtableRecord(
				listIndex=idx,
				slot=slotBase + idx,
				name=methodName,
				returnType=returnType,
				params=params,
			),
		)
	return tuple(records)


def parse_cominterface(source: str) -> dict[str, tuple[VtableRecord, ...]]:
	"""AST-parse comInterface.py source and return vtable records per class.

	Returns a dict mapping class name → ordered tuple of VtableRecord.
	Raises ``ValueError`` if no recognized interface classes are found.
	"""
	tree = ast.parse(source)
	result: dict[str, tuple[VtableRecord, ...]] = {}
	for node in ast.walk(tree):
		if not isinstance(node, ast.ClassDef):
			continue
		className = node.name
		if className not in ("ITactileDisplayAPI", "ITactileDisplayCallbacks"):
			continue
		for item in node.body:
			if not isinstance(item, ast.Assign):
				continue
			for target in item.targets:
				if isinstance(target, ast.Name) and target.id == "_methods_":
					if isinstance(item.value, ast.List):
						result[className] = _parseMethodsList(item.value, className)
	return result


def _extractDocstringVersion(source: str) -> str:
	"""Extract a version string from the module docstring of comInterface.py."""
	match = re.search(r"v(\d+\.\d+\.?\d*)", source[:2000])
	return f"v{match.group(1)}" if match else "unknown"


# ---------------------------------------------------------------------------
# Pure layer — comparison
# ---------------------------------------------------------------------------


def classify_strict_drift(
	interfaceName: str,
	declared: tuple[VtableRecord, ...],
	typelib: tuple[VtableRecord, ...],
) -> list[StrictFinding]:
	"""Compare ordered name lists; return StrictFindings for any divergence."""
	findings: list[StrictFinding] = []
	slotBase = _slotBase(interfaceName)
	declaredNames = [r.name for r in declared]
	typelibNames = [r.name for r in typelib]

	if len(declaredNames) == len(typelibNames) and declaredNames == typelibNames:
		return findings

	# Walk by typelib position, find first divergence
	maxLen = max(len(declaredNames), len(typelibNames))
	for i in range(maxLen):
		declName = declaredNames[i] if i < len(declaredNames) else None
		tlName = typelibNames[i] if i < len(typelibNames) else None
		if declName == tlName:
			continue

		# Classify this divergence
		if tlName is not None and tlName not in declaredNames:
			# Typelib has a name not in declared at all → new method
			if i >= len(declaredNames):
				classification: Literal[
					"new_appended",
					"new_mid_insert",
					"removed",
					"reordered",
					"count_mismatch",
				] = "new_appended"
			else:
				classification = "new_mid_insert"
		elif declName is not None and declName not in typelibNames:
			# Declared has a name not in typelib → removed
			classification = "removed"
		elif tlName is None and declName is not None:
			# Typelib shorter → extra declared methods
			classification = "count_mismatch"
		elif declName is None and tlName is not None:
			# Declared shorter → extra typelib methods
			classification = "new_appended"
		else:
			# Both present but different → reordered
			classification = "reordered"

		findings.append(
			StrictFinding(
				interfaceName=interfaceName,
				listIndex=i,
				slot=slotBase + i,
				declaredName=declName,
				typelibName=tlName,
				classification=classification,
			),
		)

	return findings


def compare_vtable_interface(
	interfaceName: str,
	declared: tuple[VtableRecord, ...],
	typelib: tuple[VtableRecord, ...],
	allowlist: dict[tuple[str, str], KnownDeviation],
) -> InterfaceReport:
	"""Full per-interface comparison: strict on name/count, advisory on signatures."""
	rawStrictFindings = classify_strict_drift(interfaceName, declared, typelib)
	# Promote typelib-absent allowlisted methods from strict "removed" to suppressed advisory.
	promotedSuppress = 0
	filteredStrict: list[StrictFinding] = []
	for sf in rawStrictFindings:
		if sf.classification == "removed" and sf.declaredName is not None:
			key = (interfaceName, sf.declaredName)
			if key in allowlist and allowlist[key].kind == "typelib_absent":
				promotedSuppress += 1
				continue
		filteredStrict.append(sf)
	strictFindings = tuple(filteredStrict)

	# Advisory: compare signatures for name-matched methods
	advisoryFindings: list[AdvisoryFinding] = []
	suppressedCount = 0
	declaredByName = {r.name: r for r in declared}
	typelibByName = {r.name: r for r in typelib}

	# Check declared methods for which typelib has a match
	for name, declRecord in declaredByName.items():
		if name not in typelibByName:
			# Method absent from typelib — check allowlist
			key = (interfaceName, name)
			if key in allowlist and allowlist[key].kind == "typelib_absent":
				suppressedCount += 1
			else:
				# Advisory: method declared but absent from typelib
				advisoryFindings.append(
					AdvisoryFinding(
						interfaceName=interfaceName,
						methodName=name,
						field="typelib_absent",
						declaredValue="declared",
						typelibValue="absent",
					),
				)
			continue

		tlRecord = typelibByName[name]
		key = (interfaceName, name)
		isAllowlisted = key in allowlist

		# Return type
		if declRecord.returnType != tlRecord.returnType:
			if isAllowlisted and allowlist[key].kind == "return_type":
				suppressedCount += 1
			else:
				advisoryFindings.append(
					AdvisoryFinding(
						interfaceName=interfaceName,
						methodName=name,
						field="return_type",
						declaredValue=declRecord.returnType,
						typelibValue=tlRecord.returnType,
					),
				)

		# Parameters
		for paramIdx, (declParam, tlParam) in enumerate(
			zip(declRecord.params, tlRecord.params, strict=False),
		):
			if declParam.typeName != tlParam.typeName:
				if isAllowlisted and allowlist[key].kind == "param_type":
					suppressedCount += 1
				else:
					advisoryFindings.append(
						AdvisoryFinding(
							interfaceName=interfaceName,
							methodName=name,
							field=f"param[{paramIdx}].type",
							declaredValue=declParam.typeName,
							typelibValue=tlParam.typeName,
						),
					)
			if declParam.direction != tlParam.direction:
				if isAllowlisted and allowlist[key].kind == "param_type":
					suppressedCount += 1
				else:
					advisoryFindings.append(
						AdvisoryFinding(
							interfaceName=interfaceName,
							methodName=name,
							field=f"param[{paramIdx}].direction",
							declaredValue=declParam.direction,
							typelibValue=tlParam.direction,
						),
					)

	return InterfaceReport(
		interfaceName=interfaceName,
		declaredCount=len(declared),
		typelibCount=len(typelib),
		strictFindings=strictFindings,
		advisoryFindings=tuple(advisoryFindings),
		suppressedCount=suppressedCount + promotedSuppress,
		inSync=len(strictFindings) == 0,
	)


# ---------------------------------------------------------------------------
# Pure layer — report formatting
# ---------------------------------------------------------------------------

_CLASSIFICATION_LABELS: dict[str, str] = {
	"new_appended": "new (appended)",
	"new_mid_insert": "new (mid-insert — downstream slots shifted ⚠)",
	"removed": "removed",
	"reordered": "reordered (downstream shift from insertion above)",
	"count_mismatch": "count mismatch",
}


def format_report(report: ComparisonReport, verbose: bool = False) -> str:
	"""Render a ComparisonReport as a human-readable string."""
	lines: list[str] = []
	lines.append(f"TactileDisplayAPI.dll  version: {report.dllVersion}")
	lines.append(f"comInterface.py        version: {report.docstringVersion}  (from module docstring)")
	lines.append("")

	for iface in report.interfaces:
		slotBase = _slotBase(iface.interfaceName)
		lastSlot = slotBase + iface.declaredCount - 1 if iface.declaredCount > 0 else slotBase
		sync = "IN SYNC" if iface.inSync else "DRIFT DETECTED"
		lines.append(
			f"{iface.interfaceName:<32} — {iface.declaredCount} methods "
			f"(slots {slotBase}-{lastSlot}) — {sync}",
		)

		if iface.strictFindings:
			lines.append("")
			for f in iface.strictFindings:
				label = _CLASSIFICATION_LABELS.get(f.classification, f.classification)
				declStr = f'declared="{f.declaredName}"' if f.declaredName else "absent from comInterface.py"
				tlStr = f'typelib="{f.typelibName}"' if f.typelibName else "absent from typelib"
				lines.append(f"  [slot {f.slot}] {label}")
				lines.append(f"           {declStr}  /  {tlStr}")

		if iface.advisoryFindings:
			lines.append("")
			for af in iface.advisoryFindings:
				if af.field == "typelib_absent":
					lines.append(
						f"  Advisory [{af.methodName}]: declared in wrapper, absent from typelib"
						" — verify vs vendor IDL/hardware",
					)
				else:
					lines.append(
						f"  Advisory [{af.methodName}] {af.field}: "
						f'declared="{af.declaredValue}"  typelib="{af.typelibValue}"',
					)

		if iface.suppressedCount > 0 and not verbose:
			lines.append(
				f"\n  Advisory: {iface.suppressedCount} signature deviation(s) "
				"suppressed by known-deviation allowlist.  (use --verbose to show details)",
			)
		elif iface.suppressedCount > 0 and verbose:
			lines.append(f"\n  Suppressed deviations ({iface.suppressedCount}):")
			ifaceKey = iface.interfaceName
			for (ki, km), dev in KNOWN_DEVIATIONS.items():
				if ki == ifaceKey:
					lines.append(f"    [{km}]: {dev.description}")

		lines.append("")

	return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pure layer — scaffold
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
	"BSTR": "BSTR",
	"c_int": "c_int",
	"c_long": "c_long",
	"c_double": "c_double",
	"c_ubyte": "c_ubyte",
	"c_float": "c_float",
	"c_uint": "c_uint",
	"c_ulong": "c_ulong",
	"HRESULT": "HRESULT",
	"VARIANT_BOOL": "VARIANT_BOOL",
	"VARIANT": "VARIANT",
	"c_void_p": "c_void_p",
}

_SCAFFOLD_BANNER = textwrap.dedent("""\
	# ============================================================
	# SCAFFOLD — REVIEW REQUIRED before using
	# Generated by tools/validateComVtable.py
	# Types are best-guess from typelib. Verify against vendor IDL.
	# Stub-vs-implement decision requires hardware testing.
	# ============================================================
""")


def _mapType(typeName: str) -> tuple[str, bool]:
	"""Map a typelib type string to canonical form; return (mapped, is_unknown)."""
	# Strip POINTER(...) wrapper for lookup, then re-wrap
	if typeName.startswith("POINTER(") and typeName.endswith(")"):
		inner = typeName[8:-1]
		mappedInner, unknown = _mapType(inner)
		return f"POINTER({mappedInner})", unknown
	if typeName in _TYPE_MAP:
		return _TYPE_MAP[typeName], False
	return typeName, True


def _toCamelCase(name: str) -> str:
	"""Convert PascalCase method name to camelCase for wrapper facade."""
	if not name:
		return name
	return name[0].lower() + name[1:]


def scaffold_method(record: VtableRecord, slotBase: int) -> ScaffoldBlock:
	"""Generate a ScaffoldBlock for one new method from the typelib."""
	slot = slotBase + record.listIndex
	hasUnknown = False

	# Return type
	mappedReturn, retUnknown = _mapType(record.returnType)
	if retUnknown:
		hasUnknown = True

	# Build COMMETHOD args
	commethodArgs: list[str] = ["[]", f"{mappedReturn},", f'"{record.name}",']
	if retUnknown:
		commethodArgs[1] = f"{mappedReturn},  # REVIEW: verify return type"

	paramLines: list[str] = []
	for param in record.params:
		mappedType, pUnknown = _mapType(param.typeName)
		if pUnknown:
			hasUnknown = True
		dirStr = f'["{param.direction}"]'
		typeAnnot = "  # REVIEW: verify type" if pUnknown else ""
		paramLines.append(f'\t\t([{dirStr}], {mappedType}, "{param.paramName}"),{typeAnnot}')

	# COMMETHOD block
	commethodLines = [f"\t# Slot {slot} — {record.name} (vX.Y.Z new method; REVIEW: verify name/sig)"]
	if paramLines:
		commethodLines.append("\tCOMMETHOD(")
		commethodLines.append("\t\t[],")
		commethodLines.append(f"\t\t{mappedReturn},")
		commethodLines.append(f'\t\t"{record.name}",')
		commethodLines.extend(paramLines)
		commethodLines.append("\t),")
	else:
		commethodLines.append(f'\tCOMMETHOD([], {mappedReturn}, "{record.name}"),')

	# wrapper.py facade skeleton
	camelName = _toCamelCase(record.name)
	wrapperParamSigs = ", ".join(f"{p.paramName}: object" for p in record.params)
	wrapperParams = ", ".join(p.paramName for p in record.params)
	wrapperLines = [
		f"# wrapper.py facade skeleton for {record.name}:",
		f"# def {camelName}(self{', ' + wrapperParamSigs if wrapperParamSigs else ''}) -> None:",
		f"#     self._iface.{record.name}({wrapperParams})",
	]

	return ScaffoldBlock(
		interfaceName="",  # set by caller
		slot=slot,
		commethodText="\n".join(commethodLines),
		wrapperText="\n".join(wrapperLines),
		hasUnknownTypes=hasUnknown,
	)


def format_scaffold_output(blocks: list[ScaffoldBlock]) -> str:
	"""Format a list of ScaffoldBlocks as a ready-to-paste string."""
	if not blocks:
		return "no new methods — nothing to scaffold"

	parts = [_SCAFFOLD_BANNER]
	currentIface: str | None = None
	for block in blocks:
		if block.interfaceName != currentIface:
			currentIface = block.interfaceName
			parts.append(f"\n# --- {currentIface} ---\n")
		parts.append(block.commethodText)
		parts.append("")
		parts.append(block.wrapperText)
		parts.append("")

	return "\n".join(parts)


# ---------------------------------------------------------------------------
# Impure layer — typelib extraction and DLL version
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
	"""Raised when typelib extraction fails; carries the exit code."""

	def __init__(self, message: str, exitCode: int = EXIT_ERROR) -> None:
		super().__init__(message)
		self.exitCode = exitCode


def read_dll_version(dllPath: Path) -> str:
	"""Read the PE FileVersion resource from the DLL.

	Returns ``"vMAJOR.MINOR.PATCH"`` or ``"unknown"`` on failure.
	Reimplements ``comLoader.getBundledDllVersion`` without importing comLoader.
	"""
	try:
		pathStr = str(dllPath)
		size: int = ctypes.windll.version.GetFileVersionInfoSizeW(pathStr, None)  # type: ignore[attr-defined]
		if not size:
			return "unknown"
		buf = ctypes.create_string_buffer(size)
		ctypes.windll.version.GetFileVersionInfoW(pathStr, 0, size, buf)  # type: ignore[attr-defined]
		pInfo = ctypes.c_void_p()
		uLen = ctypes.c_uint()
		if not ctypes.windll.version.VerQueryValueW(  # type: ignore[attr-defined]
			buf,
			"\\",
			ctypes.byref(pInfo),
			ctypes.byref(uLen),
		):
			return "unknown"
		addr = pInfo.value
		if addr is None:
			return "unknown"
		raw = (ctypes.c_char * uLen.value).from_address(addr).raw
		ms, ls = struct.unpack_from("<II", raw, 8)
		major, minor, patch = ms >> 16, ms & 0xFFFF, ls >> 16
		return f"v{major}.{minor}.{patch}"
	except Exception:
		return "unknown"


def _normaliseTypelibParam(param: object) -> ParamRecord:
	"""Convert one comtypes _methods_ param descriptor to a ParamRecord."""
	# comtypes param descriptors are (flags, type, name) tuples internally;
	# after GetModule they surface as objects with .flags, .type, .name attrs.
	# We use duck-typing since the internal representation is semi-private.
	try:
		flags = getattr(param, "flags", 0)
		direction = "out" if (flags & 2) else "in"
		typeName = getattr(param, "type", type(None)).__name__ if hasattr(param, "type") else "?"
		paramName = getattr(param, "name", "?") or "?"
		return ParamRecord(direction=direction, typeName=typeName, paramName=paramName)
	except Exception:
		return ParamRecord(direction="in", typeName="?", paramName="?")


def extract_typelib(dllPath: Path) -> dict[str, tuple[VtableRecord, ...]]:
	"""Extract vtable records from the DLL's embedded typelib via comtypes.

	Raises ``ExtractionError`` for any environment failure.
	"""
	# 64-bit check
	if sys.maxsize <= 2**32:
		raise ExtractionError(
			f"ERROR: 64-bit Python required for COM typelib extraction.\n"
			f"Current: sys.maxsize={sys.maxsize} (32-bit).",
			EXIT_ERROR,
		)

	if not dllPath.exists():
		raise ExtractionError(
			f"ERROR: DLL not found at {dllPath}\nCheck --dll or ensure the file is present.",
			EXIT_ERROR,
		)

	try:
		import comtypes.client  # pyright: ignore[reportMissingModuleSource]
	except ImportError as exc:
		raise ExtractionError(
			f"ERROR: comtypes is not installed.\nInstall it: pip install comtypes\nDetail: {exc}",
			EXIT_ERROR,
		) from exc

	# Use a temporary gen_dir so GetModule always regenerates from the live
	# DLL, bypassing the persistent comtypes gen cache.  Without this,
	# replacing the DLL with a new version that has the same typelib GUID
	# (as vendors do when adding methods) causes GetModule to return the
	# stale cached module and silently report an out-of-date vtable as
	# "IN SYNC".
	_tempGenDir = tempfile.mkdtemp(prefix="validateComVtable_")
	try:
		_origGenDir = comtypes.client.gen_dir  # pyright: ignore[reportUnknownVariableType]
		comtypes.client.gen_dir = _tempGenDir
		sys.path.insert(0, _tempGenDir)
		try:
			tl = comtypes.client.GetModule(str(dllPath))
		except Exception as exc:
			raise ExtractionError(
				f"ERROR: typelib extraction failed for {dllPath}.\n"
				f"Ensure the DLL has an embedded typelib (all v1.11+ do).\nDetail: {exc}",
				EXIT_ERROR,
			) from exc
		finally:
			comtypes.client.gen_dir = _origGenDir
			try:
				sys.path.remove(_tempGenDir)
			except ValueError:
				pass
	finally:
		shutil.rmtree(_tempGenDir, ignore_errors=True)

	# The typelib may expose ITactileDisplayAPI under "ITactileDisplayImpl"
	_TYPELIB_ALIASES: dict[str, tuple[str, ...]] = {
		"ITactileDisplayAPI": ("ITactileDisplayAPI", "ITactileDisplayImpl"),
	}

	result: dict[str, tuple[VtableRecord, ...]] = {}
	for className in ("ITactileDisplayAPI", "ITactileDisplayCallbacks"):
		iface = None
		for alias in _TYPELIB_ALIASES.get(className, (className,)):
			iface = getattr(tl, alias, None)
			if iface is not None:
				break
		if iface is None:
			continue
		methods = getattr(iface, "_methods_", [])
		slotBase = _slotBase(className)
		records: list[VtableRecord] = []
		for idx, m in enumerate(methods):
			name = getattr(m, "name", f"_slot{idx}")
			# Return type
			retTypeAttr = getattr(m, "restype", None)
			returnType = (
				retTypeAttr.__name__
				if retTypeAttr is not None and hasattr(retTypeAttr, "__name__")
				else "HRESULT"
			)
			# Params
			paramDescriptors = getattr(m, "argspec", ()) or ()
			params = tuple(_normaliseTypelibParam(p) for p in paramDescriptors)
			records.append(
				VtableRecord(
					listIndex=idx,
					slot=slotBase + idx,
					name=name,
					returnType=returnType,
					params=params,
				),
			)
		result[className] = tuple(records)
	return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _defaultComInterfacePath() -> Path:
	"""Resolve comInterface.py relative to the repo root (cwd)."""
	return Path("addon/tactileDisplayAPI/comInterface.py")


def _defaultDllPath() -> Path:
	return Path("addon/tactileDisplayAPI/TactileDisplayAPI.dll")


def main() -> int:
	"""Entry point; returns an exit code."""
	parser = argparse.ArgumentParser(
		description="Validate comInterface.py vtable against bundled TactileDisplayAPI.dll.",
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	parser.add_argument(
		"--check",
		action="store_true",
		help="CI mode: exit 1 on count/name-order drift, 0 when in sync.",
	)
	parser.add_argument(
		"--strict",
		action="store_true",
		help="Also exit 1 on unallowlisted advisory signature differences (use with --check).",
	)
	parser.add_argument(
		"--scaffold",
		action="store_true",
		help="Emit COMMETHOD + wrapper stubs for new methods to stdout.",
	)
	parser.add_argument(
		"--scaffold-out",
		metavar="FILE",
		help="Redirect scaffold output to FILE instead of stdout.",
	)
	parser.add_argument(
		"--dll",
		metavar="PATH",
		help=f"Override DLL location (default: {_defaultDllPath()}).",
	)
	parser.add_argument(
		"--verbose",
		action="store_true",
		help="Show allowlisted deviations with rationale in report.",
	)
	args = parser.parse_args()

	dllPath = Path(args.dll) if args.dll else _defaultDllPath()
	comInterfacePath = _defaultComInterfacePath()

	# Parse comInterface.py (pure, no comtypes)
	try:
		source = comInterfacePath.read_text(encoding="utf-8")
	except OSError as exc:
		print(f"ERROR: Could not read {comInterfacePath}: {exc}", file=sys.stderr)
		return EXIT_ERROR

	try:
		declaredAll = parse_cominterface(source)
	except SyntaxError as exc:
		print(f"ERROR: Failed to parse {comInterfacePath}: {exc}", file=sys.stderr)
		return EXIT_ERROR
	except ValueError as exc:
		print(f"ERROR: {exc}", file=sys.stderr)
		return EXIT_ERROR

	docstringVersion = _extractDocstringVersion(source)

	# Extract typelib from DLL (impure)
	try:
		typelibAll = extract_typelib(dllPath)
	except ExtractionError as exc:
		print(str(exc), file=sys.stderr)
		return exc.exitCode

	dllVersion = read_dll_version(dllPath)

	# Compare interfaces
	interfaceReports: list[InterfaceReport] = []
	for className in ("ITactileDisplayAPI", "ITactileDisplayCallbacks"):
		declared = declaredAll.get(className, ())
		typelib = typelibAll.get(className, ())
		report = compare_vtable_interface(className, declared, typelib, KNOWN_DEVIATIONS)
		interfaceReports.append(report)

	overallInSync = all(r.inSync for r in interfaceReports)
	compReport = ComparisonReport(
		dllVersion=dllVersion,
		docstringVersion=docstringVersion,
		interfaces=tuple(interfaceReports),
		overallInSync=overallInSync,
	)

	# Scaffold mode
	if args.scaffold or args.scaffold_out:
		scaffoldBlocks: list[ScaffoldBlock] = []
		for className in ("ITactileDisplayAPI", "ITactileDisplayCallbacks"):
			declared = declaredAll.get(className, ())
			typelib = typelibAll.get(className, ())
			declaredNames = {r.name for r in declared}
			slotBase = _slotBase(className)
			for tlRecord in typelib:
				if tlRecord.name not in declaredNames:
					block = scaffold_method(tlRecord, slotBase - tlRecord.listIndex)
					# Re-create with correct interface name
					block = ScaffoldBlock(
						interfaceName=className,
						slot=tlRecord.slot,
						commethodText=block.commethodText,
						wrapperText=block.wrapperText,
						hasUnknownTypes=block.hasUnknownTypes,
					)
					scaffoldBlocks.append(block)

		scaffoldText = format_scaffold_output(scaffoldBlocks)
		if args.scaffold_out:
			Path(args.scaffold_out).write_text(scaffoldText, encoding="utf-8")
			print(f"Scaffold written to {args.scaffold_out}")
		else:
			print(scaffoldText)
		# Still print the sync report to stderr so the maintainer has both
		print(format_report(compReport, verbose=args.verbose), file=sys.stderr)
		return EXIT_SYNC

	# Default: print report
	print(format_report(compReport, verbose=args.verbose))

	# Exit code logic
	if args.check or args.strict:
		if not overallInSync:
			return EXIT_DRIFT
		if args.strict:
			for r in interfaceReports:
				if r.advisoryFindings:
					return EXIT_DRIFT
		return EXIT_SYNC

	return EXIT_SYNC


if __name__ == "__main__":
	sys.exit(main())
