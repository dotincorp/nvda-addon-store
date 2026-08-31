# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Vendor path utilities for platform-specific dependencies.

This module provides utilities to manage vendored dependencies that are
platform-specific (e.g., native Python extensions compiled for specific
Python versions and architectures).
"""

import struct
import sys
from pathlib import Path
from typing import Final, TypedDict, cast

_vendorPathInitialized: bool = False


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


def getVendorSubdir() -> str:
	"""Return the vendor subdirectory name for the current Python environment.

	The subdirectory name is based on the Python version and architecture,
	e.g., "cp313_win_amd64" for Python 3.13 on 64-bit Windows.
	"""
	pythonVersion = f"cp{sys.version_info.major}{sys.version_info.minor}"
	bits = struct.calcsize("P") * 8
	arch = "win32" if bits == 32 else "win_amd64"
	return f"{pythonVersion}_{arch}"


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

	import addonHandler

	addon: addonHandler.Addon = cast(addonHandler.Addon, addonHandler.getCodeAddon())
	vendorSubdir = getVendorSubdir()

	if vendorSubdir not in SUPPORTED_PLATFORMS:
		from logHandler import log

		log.error(f"Unsupported platform: {vendorSubdir}. Supported: {', '.join(SUPPORTED_PLATFORMS)}")
		raise RuntimeError(f"DotPad add-on does not support platform {vendorSubdir}")

	vendorPath = Path(addon.path) / "_vendor" / vendorSubdir
	if not vendorPath.exists():
		raise RuntimeError(f"Vendor directory not found: {vendorPath}")

	sys.path.insert(0, str(vendorPath))
	_vendorPathInitialized = True
