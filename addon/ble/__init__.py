# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2026 Dot Incorporated

"""Bluetooth Low Energy communication module.

This module provides BLE connectivity for DotPad braille displays and decides which
BLE implementation the rest of the package uses.

NVDA 2026.3 gained ``hwIo.ble`` (PR #19838), which is this package upstreamed, plus a
bundled ``bleak``. From that version the addon defers to core; on 2026.1 and 2026.2 it
uses the local ``scanner``/``hwIo`` modules against the vendored bleak.

**The probe order matters.** ``ensureVendorPath()`` does ``sys.path.insert(0, ...)``,
which would shadow core's bleak for the entire NVDA process. So core is probed first and
the vendor path is only added when core has no BLE support -- which is why this decision
lives here, in the package root, rather than at the call sites.

``hwIo.ble`` is resolved through ``importlib`` because it does not exist on the NVDA
versions this addon is type-checked against; a plain import would be unresolvable.
Callers should use the ``createScanner`` / ``createBle`` factories, which cast core's
objects to the local classes -- the APIs are identical.
"""

import importlib
from typing import Any

from logHandler import log


def _setUpBle() -> tuple[Any | None, bool]:
	"""Return ``(coreBleModule, bleAvailable)`` for this NVDA version."""
	try:
		core = importlib.import_module("hwIo.ble")
	except ImportError:
		core = None
	if core is not None:
		log.debug("BLE: using NVDA's built-in hwIo.ble")
		return core, True

	try:
		from ..utils.vendor import ensureVendorPath

		ensureVendorPath()
	except RuntimeError as e:
		log.error("BLE not available: %s", e)
		return None, False
	log.debug("BLE: NVDA has no hwIo.ble; using the vendored bleak")
	return None, True


#: NVDA's ``hwIo.ble`` module when available (NVDA 2026.3+), otherwise ``None``, and
#: ``BLE_AVAILABLE`` is ``False`` when no BLE implementation is usable at all -- the
#: vendored bleak is missing for this platform, so the local modules refuse to import.
coreBle, BLE_AVAILABLE = _setUpBle()
