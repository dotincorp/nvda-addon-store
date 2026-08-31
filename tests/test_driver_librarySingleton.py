# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the per-driver-instance library singleton (feature 015).

After feature 015, ``BrailleDisplayDriver`` constructs the
``LibraryWorker`` + ``TactileDisplayAPI`` + ``TactileDisplayCallbacks``
at ``__init__`` time and tears them down at ``terminate()``. Each
graphic session borrows the worker — no per-session library construction.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestDriverLibrarySingleton(unittest.TestCase):
	"""``BrailleDisplayDriver`` owns the TactileDisplayAPI library lifecycle."""

	def test_initConstructsLibraryWhenGraphicDisplayPresent(self) -> None:
		"""When a graphic display is attached, init starts the worker and
		calls ``SimulateDisplay(...)``."""
		# We test the singleton-setup logic in isolation by directly calling
		# the helper that __init__ invokes. The full driver __init__ does
		# extensive device-detection work that is not relevant to this
		# contract; we just need to verify that GIVEN a driver with a
		# graphic display, the singleton fields are populated.
		from addon.brailleDisplayDrivers.dotPad.driver import (
			BrailleDisplayDriver,
		)

		# Instantiate a bare driver instance bypassing __init__ (it does
		# device I/O). We can still exercise the singleton-setup method.
		driver = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
		driver._libraryWorker = None
		driver._tda = None
		driver._callbackServer = None
		driver._libraryReady = False
		# Fake the dimensions a graphicDisplay would expose.
		driver.graphicDisplay = MagicMock(
			physicalNumCols=30,
			physicalNumRows=10,
			cellWidth=2,
			cellHeight=4,
		)
		driver.textDisplay = MagicMock(
			physicalNumRows=1,
			physicalNumCols=20,
		)
		driver._deviceName = "DotPad320A"

		# Patch the names where driver.py looks them up — driver.py imports
		# LibraryWorker / TactileDisplayAPI / TactileDisplayCallbacks at
		# module-load time, so the lookup goes through
		# ``addon.brailleDisplayDrivers.dotPad.driver``'s own namespace,
		# not the source modules. We also need to patch the simulated
		# display module so ``computeSimulateDisplayArgs`` returns a
		# fixed tuple (it would otherwise import NVDA's braille module).
		driverModule = "addon.brailleDisplayDrivers.dotPad.driver"
		with (
			patch(f"{driverModule}.LibraryWorker") as workerCls,
			patch(f"{driverModule}.TactileDisplayAPI") as tdaCls,
			patch(f"{driverModule}.TactileDisplayCallbacks") as cbCls,
			patch(f"{driverModule}._simulatedDisplay") as simMod,
			patch(f"{driverModule}.iniPatcher") as iniPatcherMod,
		):
			workerInstance = workerCls.return_value
			# Make the worker's submit().result() return whatever the
			# closure returns.
			workerInstance.submit.side_effect = lambda fn, *a, **k: MagicMock(
				result=lambda timeout=None: fn(),
			)
			tdaInstance = tdaCls.return_value
			cbInstance = cbCls.return_value
			simMod.computeSimulateDisplayArgs.return_value = ("DotPad320A", 60, 40, 20, 1)
			iniPatcherMod.patchTactileDisplayAPIIni.return_value = {}

			driver._setupLibrarySingleton()

		self.assertIs(driver._libraryWorker, workerInstance)
		self.assertIs(driver._tda, tdaInstance)
		self.assertIs(driver._callbackServer, cbInstance)
		self.assertTrue(driver._libraryReady)
		workerInstance.start.assert_called_once()
		tdaInstance.simulateDisplay.assert_called_once()
		# Graphics-only: even though a textDisplay (20 cells, 1 line) exists, the
		# text-area cell/line counts passed to SimulateDisplay must be forced to 0
		# so the library never stands up its braille-text pipeline. We drive the
		# physical text strip via NVDA's own braille pipeline, not the library.
		simArgs = tdaInstance.simulateDisplay.call_args.args
		self.assertEqual(simArgs[3], 0, "totalBrailleCellCount must be 0 (graphics-only)")
		self.assertEqual(simArgs[4], 0, "lineCount must be 0 (graphics-only)")

	def test_initSkipsLibraryWhenNoGraphicDisplay(self) -> None:
		"""When no graphic display is attached, the singleton stays None."""
		from addon.brailleDisplayDrivers.dotPad.driver import (
			BrailleDisplayDriver,
		)

		driver = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
		driver._libraryWorker = None
		driver._tda = None
		driver._callbackServer = None
		driver._libraryReady = False
		driver.graphicDisplay = None
		driver.textDisplay = None
		driver._deviceName = "TextOnlyDevice"

		driver._setupLibrarySingleton()

		self.assertIsNone(driver._libraryWorker)
		self.assertIsNone(driver._tda)
		self.assertIsNone(driver._callbackServer)
		self.assertFalse(driver._libraryReady)

	def test_terminateDrainsAndReleasesLibrary(self) -> None:
		"""Teardown calls setShuttingDown then worker.stop and clears refs."""
		from addon.brailleDisplayDrivers.dotPad.driver import (
			BrailleDisplayDriver,
		)

		driver = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
		driver._libraryWorker = MagicMock(name="worker")
		driver._tda = MagicMock(name="tda")
		driver._callbackServer = MagicMock(name="callbacks")
		driver._libraryReady = True

		driver._teardownLibrarySingleton()

		driver._callbackServer is None or self.fail("callbacks should be cleared")
		self.assertIsNone(driver._libraryWorker)
		self.assertIsNone(driver._tda)
		self.assertIsNone(driver._callbackServer)
		self.assertFalse(driver._libraryReady)

	def test_terminateIdempotent(self) -> None:
		"""Second teardown is a safe no-op."""
		from addon.brailleDisplayDrivers.dotPad.driver import (
			BrailleDisplayDriver,
		)

		driver = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
		driver._libraryWorker = None
		driver._tda = None
		driver._callbackServer = None
		driver._libraryReady = False

		# Must not raise.
		driver._teardownLibrarySingleton()


class TestDriverLibraryUiaEventsToggle(unittest.TestCase):
	"""RegisterEvents is toggled by enable/disable methods, NOT at driver init."""

	_driverModule = "addon.brailleDisplayDrivers.dotPad.driver"

	def _readyDriver(self):
		from addon.brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver

		driver = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
		driver._libraryWorker = MagicMock(name="worker")
		driver._tda = MagicMock(name="tda")
		driver._libraryReady = True
		return driver

	def test_enable_submits_register_events(self) -> None:
		from addon.brailleDisplayDrivers.dotPad import driver as driverMod

		driver = self._readyDriver()
		driver.enableLibraryUiaEvents()
		driver._libraryWorker.submit.assert_called_once_with(
			driverMod._setRegisterEventsOnWorker,
			driver._tda,
			driver._libraryWorker,
		)

	def test_disable_submits_unregister_events(self) -> None:
		from addon.brailleDisplayDrivers.dotPad import driver as driverMod

		driver = self._readyDriver()
		driver.disableLibraryUiaEvents()
		driver._libraryWorker.submit.assert_called_once_with(
			driverMod._disableRegisterEventsOnWorker,
			driver._tda,
			driver._libraryWorker,
		)

	def test_toggle_noop_when_library_not_ready(self) -> None:
		driver = self._readyDriver()
		driver._libraryReady = False
		driver.enableLibraryUiaEvents()
		driver.disableLibraryUiaEvents()
		driver._libraryWorker.submit.assert_not_called()

	def test_setup_does_not_enable_events_at_init(self) -> None:
		"""``_setupLibrarySingleton`` must NOT submit RegisterEvents — events are
		enabled only by the braille presentation after its bootstrap."""
		from addon.brailleDisplayDrivers.dotPad import driver as driverMod
		from addon.brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver

		driver = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
		driver._libraryWorker = None
		driver._tda = None
		driver._callbackServer = None
		driver._libraryReady = False
		driver.graphicDisplay = MagicMock(physicalNumCols=30, physicalNumRows=10, cellWidth=2, cellHeight=4)
		driver.textDisplay = MagicMock(physicalNumRows=1, physicalNumCols=20)
		driver._deviceName = "DotPad320A"

		dm = self._driverModule
		with (
			patch(f"{dm}.LibraryWorker") as workerCls,
			patch(f"{dm}.TactileDisplayAPI"),
			patch(f"{dm}.TactileDisplayCallbacks"),
			patch(f"{dm}._simulatedDisplay"),
			patch(f"{dm}.iniPatcher") as iniMod,
		):
			workerInstance = workerCls.return_value
			workerInstance.submit.side_effect = lambda fn, *a, **k: MagicMock(
				result=lambda timeout=None: fn(),
			)
			iniMod.patchTactileDisplayAPIIni.return_value = {}
			driver._setupLibrarySingleton()

		submittedFns = [c.args[0] for c in workerInstance.submit.call_args_list if c.args]
		self.assertNotIn(driverMod._setRegisterEventsOnWorker, submittedFns)


class TestIniPatcherOrdering(unittest.TestCase):
	"""Feature 025: ``iniPatcher.patchTactileDisplayAPIIni`` runs before ``worker.start()``."""

	def test_iniPatcherCalledBeforeWorkerStart(self) -> None:
		from addon.brailleDisplayDrivers.dotPad.driver import (
			BrailleDisplayDriver,
		)

		driver = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
		driver._libraryWorker = None
		driver._tda = None
		driver._callbackServer = None
		driver._libraryReady = False
		driver.graphicDisplay = MagicMock(
			physicalNumCols=30,
			physicalNumRows=10,
			cellWidth=2,
			cellHeight=4,
		)
		driver.textDisplay = MagicMock(physicalNumRows=1, physicalNumCols=20)
		driver._deviceName = "DotPad320A"

		driverModule = "addon.brailleDisplayDrivers.dotPad.driver"
		# Use a single parent mock to record call order across both targets.
		# ``patch`` returns the mock you can inspect via ``method_calls``.
		callOrder = MagicMock()
		with (
			patch(f"{driverModule}.LibraryWorker", new=callOrder.LibraryWorker),
			patch(f"{driverModule}.TactileDisplayAPI") as tdaCls,
			patch(f"{driverModule}.TactileDisplayCallbacks"),
			patch(f"{driverModule}._simulatedDisplay"),
			patch(f"{driverModule}.iniPatcher", new=callOrder.iniPatcher),
		):
			workerInstance = callOrder.LibraryWorker.return_value
			workerInstance.submit.side_effect = lambda fn, *a, **k: MagicMock(
				result=lambda timeout=None: fn(),
			)
			tdaCls.return_value = MagicMock()
			callOrder.iniPatcher.patchTactileDisplayAPIIni.return_value = {}

			driver._setupLibrarySingleton()

		# Find the indices of the relevant calls inside the parent mock's call log.
		callNames = [c[0] for c in callOrder.mock_calls]
		patchCallIdx = next(
			i for i, name in enumerate(callNames) if name == "iniPatcher.patchTactileDisplayAPIIni"
		)
		workerStartIdx = next(i for i, name in enumerate(callNames) if name == "LibraryWorker().start")
		self.assertLess(
			patchCallIdx,
			workerStartIdx,
			f"patchTactileDisplayAPIIni must run before LibraryWorker.start (got order: {callNames})",
		)
		callOrder.iniPatcher.patchTactileDisplayAPIIni.assert_called_once_with()


if __name__ == "__main__":
	unittest.main()
