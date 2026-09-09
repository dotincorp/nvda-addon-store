# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Vendor path utilities for platform-specific dependencies.

This module provides utilities to manage vendored dependencies that are
platform-specific (e.g., native Python extensions compiled for specific
Python versions and architectures).
"""

import importlib
import struct
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final, TypedDict, cast

import addonHandler
from logHandler import log

_vendorPathInitialized: bool = False
_winrtCollectionsGrafted: bool = False


class VendorTarget(TypedDict):
	"""Configuration for a vendor target platform."""

	python: str
	arch: str
	subdir: str


#: Every supported NVDA (2026.1+) runs 64-bit Python 3.13, so there is a single target.
VENDOR_TARGETS: Final[tuple[VendorTarget, ...]] = (
	{"python": "3.13", "arch": "win_amd64", "subdir": "cp313_win_amd64"},
)

SUPPORTED_PLATFORMS: Final[tuple[str, ...]] = tuple(t["subdir"] for t in VENDOR_TARGETS)

#: The winrt release the vendored projections were built against. They reach the runtime
#: through a C API capsule, so pairing them with another one crashes rather than raises.
VENDORED_WINRT_VERSION: Final = "3.2.1"


def getVendorSubdir() -> str:
	"""Return the vendor subdirectory name for the current Python environment.

	The subdirectory name is based on the Python version and architecture,
	e.g., "cp313_win_amd64" for Python 3.13 on 64-bit Windows.
	"""
	pythonVersion = f"cp{sys.version_info.major}{sys.version_info.minor}"
	bits = struct.calcsize("P") * 8
	arch = "win32" if bits == 32 else "win_amd64"
	return f"{pythonVersion}_{arch}"


def getVendorPath() -> Path:
	"""Return the platform-specific vendor directory.

	Raises:
		RuntimeError: If the current platform is not supported or the vendor
			directory does not exist.
	"""
	addon: addonHandler.Addon = cast(addonHandler.Addon, addonHandler.getCodeAddon())
	vendorSubdir = getVendorSubdir()

	if vendorSubdir not in SUPPORTED_PLATFORMS:
		log.error("Unsupported platform: %s. Supported: %s", vendorSubdir, ", ".join(SUPPORTED_PLATFORMS))
		raise RuntimeError(f"DotPad add-on does not support platform {vendorSubdir}")

	vendorPath = Path(addon.path) / "_vendor" / vendorSubdir
	if not vendorPath.exists():
		raise RuntimeError(f"Vendor directory not found: {vendorPath}")

	return vendorPath


def ensureVendorPath() -> None:
	"""Add the platform-specific vendor directory to sys.path.

	This function detects the current Python version and architecture,
	then adds the appropriate vendor subdirectory to sys.path. This allows
	vendored packages with native extensions to be imported normally.

	The function is idempotent - calling it multiple times has no additional effect.

	Raises:
		RuntimeError: If the current platform is not supported or the vendor
			directory does not exist.
	"""
	global _vendorPathInitialized
	if _vendorPathInitialized:
		return

	sys.path.insert(0, str(getVendorPath()))
	_vendorPathInitialized = True


def appendPackagePath(moduleName: str, path: Path) -> None:
	"""Append *path* to an already imported package's search path.

	Args:
		moduleName: Dotted name of a package that is already in ``sys.modules``.
		path: Directory to append to its ``__path__``.

	Raises:
		RuntimeError: If the module is not an imported package with a mutable
			``__path__``.
	"""
	module = sys.modules.get(moduleName)
	packagePath = getattr(module, "__path__", None)
	if not isinstance(packagePath, list):
		raise RuntimeError(f"{moduleName} is not an imported package with a mutable __path__")

	entry = str(path)
	if entry not in packagePath:
		packagePath.append(entry)


def ensureWinrtCollections() -> None:
	"""Supply ``winrt.windows.foundation.collections`` when NVDA's build omits it.

	NVDA 2026.3 beta 1 bundles bleak and the winrt projections but not this one -- only
	the compiled projections import it, at C level, where py2exe's module finder cannot
	see it -- so bleak raises ``ModuleNotFoundError`` as soon as a device is discovered.

	Note it is grafted onto the imported packages' ``__path__`` rather than added to
	``sys.path``: the vendored ``winrt`` is a namespace package and NVDA's frozen one is a
	regular package, which wins from any position. Appending leaves what NVDA ships first.

	A no-op on builds that ship the module or run a different winrt runtime.
	"""
	global _winrtCollectionsGrafted
	if _winrtCollectionsGrafted:
		return

	try:
		importlib.import_module("winrt.windows.foundation.collections")
		return
	except ImportError:
		pass

	if "winrt.windows.foundation" not in sys.modules:
		log.debug("No frozen winrt projections to complete")
		return

	runtimeVersion = _getWinrtRuntimeVersion()
	if runtimeVersion != VENDORED_WINRT_VERSION:
		log.error(
			"Cannot complete NVDA's winrt projections: it runs winrt-runtime %s, "
			"the vendored ones need %s. Bluetooth is unlikely to work.",
			runtimeVersion,
			VENDORED_WINRT_VERSION,
		)
		return

	try:
		winrtPath = getVendorPath() / "winrt"
		appendPackagePath("winrt", winrtPath)
		appendPackagePath("winrt.windows.foundation", winrtPath / "windows" / "foundation")
		importlib.invalidate_caches()
		importlib.import_module("winrt.windows.foundation.collections")
	except (RuntimeError, ImportError):
		log.exception("Could not complete NVDA's winrt projections; Bluetooth is unlikely to work")
		return

	_winrtCollectionsGrafted = True
	log.info("NVDA does not ship winrt.windows.foundation.collections; using the vendored copy")


def _getWinrtRuntimeVersion() -> str | None:
	"""Return NVDA's winrt-runtime version, or ``None`` if it cannot be read."""
	try:
		return version("winrt-runtime")
	except PackageNotFoundError:
		return None
