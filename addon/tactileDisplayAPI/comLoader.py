# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Registration-free COM loader for TactileDisplayAPI (v1.11).

Loads TactileDisplayAPI.dll directly and creates a COM object via
``DllGetClassObject``, bypassing the Windows registry entirely.
No ``regsvr32``, no admin rights, no HKLM/HKCU writes — the addon ships
the DLL bundled and end-user installs without elevated privileges.

The vtable layout is no longer hand-declared here; it lives in
``comInterface.ITactileDisplayAPI`` as a comtypes interface class.
``createTactileDisplayApi`` calls the class factory's ``CreateInstance``
with each candidate IID until one succeeds, then casts the resulting raw
pointer into the comtypes-typed pointer. comtypes handles refcounting,
BSTR marshalling, and HRESULT translation from there.

The IID-candidate iteration is preserved verbatim — different library
versions expose different runtime IIDs for the same dual interface, and
the candidate list is the only thing standing between us and a hard fail
when the vendor rotates the IID.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

from logHandler import log

if TYPE_CHECKING:
	from comtypes.automation import IDispatch

from .comInterface import ITactileDisplayAPI


# --- COM GUIDs ---


class GUID(ctypes.Structure):
	_fields_ = [
		("Data1", ctypes.c_ulong),
		("Data2", ctypes.c_ushort),
		("Data3", ctypes.c_ushort),
		("Data4", ctypes.c_ubyte * 8),
	]


def _makeGuid(s: str) -> GUID:
	"""Create a GUID from a string like '{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}'."""
	s = s.strip("{}")
	parts = s.split("-")
	data4Hex = parts[3] + parts[4]
	data4 = (ctypes.c_ubyte * 8)(*(int(data4Hex[i : i + 2], 16) for i in range(0, 16, 2)))
	return GUID(
		Data1=int(parts[0], 16),
		Data2=int(parts[1], 16),
		Data3=int(parts[2], 16),
		Data4=data4,
	)


# COM identifiers
# CLSID is reused from v1.05 in v1.11; ProgID is "tactileDisplayAPI.1".
# TODO: switch to CLSIDFromProgID-style resolution if upstream rotates the CLSID.
PROGID_TACTILE_DISPLAY = "tactileDisplayAPI.1"
CLSID_TACTILE_DISPLAY_API = _makeGuid("{42543274-ec5e-4427-b473-e4e85f9909bc}")
IID_IClassFactory = _makeGuid("{00000001-0000-0000-C000-000000000046}")
IID_IDispatch = _makeGuid("{00020400-0000-0000-C000-000000000046}")
# Dual-interface IID candidates. The vendor preserved the CLSID across the
# v1.05→v1.11 rename; they likely preserved the dual-interface IID too. The
# v1.11 IID extracted by string-scanning the DLL turned out to be
# E_NOINTERFACE on hardware — kept here in case a future build rotates the IID.
#
# Append-only contract: future rotations add entries to the END of
# IID_CANDIDATES so log-based diagnostics remain interpretable.
IID_IJDPGRAPHICS_LEGACY = _makeGuid("{48FB9EFA-4F20-4086-8A15-5CE3CF0CC2E3}")
IID_ITactileDisplayAPI = _makeGuid("{b96433d8-efe9-4c8a-a1f9-0ec4178d3af3}")
IID_CANDIDATES: tuple[GUID, ...] = (
	IID_IJDPGRAPHICS_LEGACY,  # primary — vendor preserves binary contracts
	IID_ITactileDisplayAPI,  # secondary — E_NOINTERFACE on current hardware
	IID_IDispatch,  # last resort — would need different vtable handling
)

S_OK = 0


# --- IClassFactory vtable infrastructure ---
#
# Hand-rolled because we obtain the factory via DllGetClassObject (registration-
# free path), not CoCreateInstance. comtypes can't easily wrap an IClassFactory
# acquired this way; the few lines below cover what we need.


class _ObjBase(ctypes.Structure):
	"""Base COM object with vtable pointer (used for IClassFactory casts)."""

	pass


_ObjBase._fields_ = [("lpVtbl", ctypes.c_void_p)]

# IClassFactory vtable function signatures
_CF_QueryInterface = ctypes.WINFUNCTYPE(
	ctypes.HRESULT,
	ctypes.POINTER(_ObjBase),
	ctypes.POINTER(GUID),
	ctypes.POINTER(ctypes.c_void_p),
)
_CF_AddRef = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.POINTER(_ObjBase))
_CF_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.POINTER(_ObjBase))
_CF_CreateInstance = ctypes.WINFUNCTYPE(
	ctypes.HRESULT,
	ctypes.POINTER(_ObjBase),
	ctypes.c_void_p,
	ctypes.POINTER(GUID),
	ctypes.POINTER(ctypes.c_void_p),
)


class IClassFactoryVtbl(ctypes.Structure):
	_fields_ = [
		("QueryInterface", _CF_QueryInterface),
		("AddRef", _CF_AddRef),
		("Release", _CF_Release),
		("CreateInstance", _CF_CreateInstance),
	]


class IClassFactoryObj(ctypes.Structure):
	_fields_ = [("lpVtbl", ctypes.POINTER(IClassFactoryVtbl))]


# --- DLL loading ---


def _getLibraryDir() -> Path:
	"""Return the directory containing TactileDisplayAPI DLLs."""
	return Path(os.path.dirname(__file__))


@contextlib.contextmanager
def _dllSearchPathContext() -> Generator[None]:
	"""Temporarily add the TactileDisplayAPI directory to the DLL search path.

	This ensures dependency DLLs (DotPadSDK, jsoncpp, Mecab, TTBEngine,
	libmathcat_c) are found when loading TactileDisplayAPI.dll. liblouis is
	not bundled here — the library loads NVDA's liblouis from the absolute
	``LiblouisPath`` written into its per-locale ini.
	"""
	lib_dir = _getLibraryDir()
	cookie = os.add_dll_directory(str(lib_dir))
	try:
		yield
	finally:
		cookie.close()


@contextlib.contextmanager
def liblouisTablePathContext() -> Generator[None]:
	"""Temporarily set CWD to the TactileDisplayAPI directory around library calls.

	Historically the bundled liblouis resolved braille tables via a relative
	``tables\\{filename}`` path from the CWD. The library now loads liblouis
	and tables from NVDA's absolute ``LiblouisPath`` / ``TablesPath``, so the
	CWD no longer affects table resolution. This context manager is retained
	as a harmless safeguard around COM methods that may still do relative-path
	resolution internally (DrawTextLabel, ShowMultilineText, ShowStatusText,
	GraphMathEquation, SetBrailleTables); it restores the original CWD on exit.
	"""
	lib_dir = str(_getLibraryDir())
	old_cwd = os.getcwd()
	os.chdir(lib_dir)
	try:
		yield
	finally:
		os.chdir(old_cwd)


# Module-level singleton DLL handle. Once loaded, the DLL stays in memory
# for the addon's process lifetime — same lifetime model as the previous
# wrapper-held reference, just made explicit. The dependency DLLs
# (DotPadSDK, jsoncpp, Mecab, TTBEngine, libmathcat_c) are resolved at load
# time via _dllSearchPathContext; subsequent calls don't need that context.
_cachedDll: ctypes.WinDLL | None = None


def getBundledDllVersion() -> str:
	"""Read the FileVersion resource from the bundled TactileDisplayAPI.dll.

	Returns a string of the form ``"v{major}.{minor}.{patch}"`` (e.g. ``"v1.0.21"``).
	Falls back to ``"unknown"`` if the version resource cannot be read.
	"""
	import struct

	path = str(_getLibraryDir() / "TactileDisplayAPI.dll")
	try:
		size: int = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
		if not size:
			return "unknown"
		buf = ctypes.create_string_buffer(size)
		ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf)
		pInfo = ctypes.c_void_p()
		uLen = ctypes.c_uint()
		if not ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(pInfo), ctypes.byref(uLen)):
			return "unknown"
		# VS_FIXEDFILEINFO: dwFileVersionMS at offset 8, dwFileVersionLS at offset 12.
		addr = pInfo.value
		if addr is None:
			return "unknown"
		raw = (ctypes.c_char * uLen.value).from_address(addr).raw
		ms, ls = struct.unpack_from("<II", raw, 8)
		major, minor, patch = ms >> 16, ms & 0xFFFF, ls >> 16
		return f"v{major}.{minor}.{patch}"
	except Exception:
		return "unknown"


def _loadDll() -> ctypes.WinDLL:
	"""Load TactileDisplayAPI.dll (or return the cached handle)."""
	global _cachedDll
	if _cachedDll is not None:
		return _cachedDll
	dll_path = _getLibraryDir() / "TactileDisplayAPI.dll"
	if not dll_path.exists():
		raise FileNotFoundError(f"TactileDisplayAPI.dll not found at {dll_path}")
	with _dllSearchPathContext():
		_cachedDll = ctypes.WinDLL(str(dll_path))
	log.debug(f"Loaded TactileDisplayAPI.dll from {dll_path}")
	return _cachedDll


# --- COM object creation ---


def _getClassFactory(dll: ctypes.WinDLL) -> "ctypes._Pointer[IClassFactoryObj]":  # pyright: ignore[reportPrivateUsage]
	"""Call DllGetClassObject to get the IClassFactory for TactileDisplayAPI.

	The ``_Pointer`` annotation is the actual class returned by
	``ctypes.POINTER``; its underscore prefix is a Python convention rather
	than a real privacy boundary, but pyright flags it. This use is
	idiomatic for ctypes annotations.
	"""
	factory_ptr = ctypes.c_void_p()
	hr: int = dll.DllGetClassObject(
		ctypes.byref(CLSID_TACTILE_DISPLAY_API),
		ctypes.byref(IID_IClassFactory),
		ctypes.byref(factory_ptr),
	)
	if hr != S_OK:
		raise OSError(f"DllGetClassObject failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}")
	return ctypes.cast(factory_ptr, ctypes.POINTER(IClassFactoryObj))


def _guidStr(guid: GUID) -> str:
	"""Format a GUID struct as the canonical {xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx} string."""
	d4 = bytes(guid.Data4)
	return (
		f"{{{guid.Data1:08x}-{guid.Data2:04x}-{guid.Data3:04x}-"
		f"{d4[0]:02x}{d4[1]:02x}-"
		f"{d4[2]:02x}{d4[3]:02x}{d4[4]:02x}{d4[5]:02x}{d4[6]:02x}{d4[7]:02x}}}"
	)


def createTactileDisplayApi() -> "ctypes._Pointer[ITactileDisplayAPI]":  # pyright: ignore[reportPrivateUsage]
	"""Create a comtypes-typed pointer to the library's dual interface.

	Loads the DLL (cached via module-level singleton), gets the
	``IClassFactory`` via ``DllGetClassObject``, iterates ``IID_CANDIDATES``
	via ``IClassFactory::CreateInstance`` until one succeeds, and casts the
	resulting raw pointer into ``POINTER(ITactileDisplayAPI)``.

	Returns:
		A comtypes-typed pointer. The caller can call any method declared
		in ``ITactileDisplayAPI._methods_`` directly. Refcount is managed
		by comtypes; when the wrapper is garbage-collected, ``Release()``
		is called automatically.

	Raises:
		FileNotFoundError: ``TactileDisplayAPI.dll`` not found in the addon directory.
		OSError: Every candidate IID failed ``CreateInstance``. The exception
			message names every candidate tried and the HRESULT each returned.
	"""
	dll = _loadDll()
	factory = _getClassFactory(dll)
	obj_ptr = ctypes.c_void_p()
	resolvedIid: GUID | None = None
	attempts: list[tuple[GUID, int]] = []
	try:
		vtbl = factory.contents.lpVtbl.contents
		for candidate in IID_CANDIDATES:
			hr = vtbl.CreateInstance(
				ctypes.cast(factory, ctypes.POINTER(_ObjBase)),
				None,
				ctypes.byref(candidate),
				ctypes.byref(obj_ptr),
			)
			if hr == S_OK:
				resolvedIid = candidate
				log.debug(f"Tactile-display interface resolved via IID = {_guidStr(candidate)}")
				break
			attempts.append((candidate, hr))
		if resolvedIid is None:
			tried = ", ".join(f"{_guidStr(iid)}=0x{hr & 0xFFFFFFFF:08X}" for iid, hr in attempts)
			raise OSError(f"Tactile-display interface unavailable. Tried: {tried}")
	finally:
		# Release the class factory (independent refcount from the COM object).
		fvtbl = factory.contents.lpVtbl.contents
		fvtbl.Release(ctypes.cast(factory, ctypes.POINTER(_ObjBase)))

	raw_ptr = obj_ptr.value
	assert raw_ptr is not None
	# Wrap the raw pointer as the comtypes-typed pointer. The raw pointer
	# has refcount 1 (CreateInstance gives caller-owned reference);
	# comtypes' Release-on-GC decrements it on Python wrapper destruction.
	# Do NOT wrap the same raw pointer twice — that would double-Release.
	return ctypes.cast(raw_ptr, ctypes.POINTER(ITactileDisplayAPI))


def createSystemTactileDisplayApi() -> "IDispatch":
	"""Return an ``IDispatch`` pointer via CoCreateInstance (system-registered path).

	Uses ``comtypes.CoCreateInstance`` with the known CLSID and ``IDispatch``
	as the requested interface. No DLL load, no search-path context — Windows
	resolves the DLL via the registry. COM is already initialised (STA) on the
	LibraryWorker thread before this is called.

	Returns ``IDispatch`` (not the typed ``ITactileDisplayAPI`` pointer) so
	that callers use ``DispatchProxy`` for position-independent dispatch.
	This makes the system path immune to future mid-vtable insertions by the
	vendor, because method calls are resolved by name via
	``IDispatch.GetIDsOfNames`` rather than by vtable slot number.

	Raises:
		OSError: System COM server not registered. The exception message
			contains "System tactile-display interface unavailable".
	"""
	import comtypes
	from comtypes.automation import IDispatch as _IDispatch

	clsid = comtypes.GUID("{42543274-ec5e-4427-b473-e4e85f9909bc}")

	try:
		idisp = comtypes.CoCreateInstance(
			clsid,
			interface=_IDispatch,
			clsctx=comtypes.CLSCTX_INPROC_SERVER,
		)
		log.debug("System tactile-display interface obtained as IDispatch")
		return idisp  # type: ignore[return-value]
	except OSError:
		pass

	raise OSError(
		"System tactile-display interface unavailable "
		"(CLSID {42543274-ec5e-4427-b473-e4e85f9909bc}; "
		"is TactileDisplayAPI installed system-wide?)",
	)
