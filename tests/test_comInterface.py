# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Smoke tests for the comtypes ITactileDisplayAPI declaration.

Asserts the wrapped vtable list is well-formed and matches the v1.23
typelib layout. Catches the "slot misaligned with library vtable"
failure mode at unit-test time before it surfaces as a stack-corrupting
access violation on first call.

Membership and ordering tests only — does NOT load the COM library
or call any method. The tests run on any machine that has the addon
source tree, including CI workers without a DotPad attached.

Scope context:
- v1.16 inserted ``SimulateDisplay`` at slot 8.
- v1.17 inserted ``DisplayLiteraryBraille`` at vtable slot 11 (between
  ``SetBrailleTables`` and what was ``SetDrawingMode`` in v1.16). Every
  wrapped method downstream of slot 10 shifts +1 vtable position versus v1.16.
- v1.0.21 inserted ``SetHybridPrintAndBrailleMode`` at slot 35 (mid-vtable),
  shifting ``EnableContractedBrailleInput`` to slot 36 and ``ExecuteOperation``
  to slot 37.
- v1.22 inserted ``SetBrailleLinePadding`` at slot 12 and ``ForceSixDotBraille``
  at slot 13 (mid-vtable, between ``DisplayLiteraryBraille`` and what was
  ``SetDrawingMode``), shifting every subsequent slot +2. Total: 33 methods
  (slots 7-39). ``SetHybridPrintAndBrailleMode`` moves from slot 35 → 37.
"""

from __future__ import annotations

import unittest


# The expected vtable order is the source of truth for what the addon
# wraps. List position N corresponds to vtable slot 7+N. The first
# entry maps to slot 7 (the first library-specific method after the
# inherited IUnknown 0-2 and IDispatch 3-6 slots).
_EXPECTED_METHOD_ORDER = (
	"Connect",
	"SimulateDisplay",
	"Disconnect",
	"SetBrailleTables",
	"DisplayLiteraryBraille",
	"SetBrailleLinePadding",
	"ForceSixDotBraille",
	"SetDrawingMode",
	"GetDimensions",
	"Clear",
	"DrawLine",
	"DrawBox",
	"DrawCircle",
	"DrawPoly",
	"Fill",
	"InvertRect",
	"DrawBrailleLabel",
	"DrawTextLabel",
	"GraphMathEquation",
	"DrawImage",
	"DrawScreenRegion",
	"DrawASCIIBrailleImage",
	"UndoLastDraw",
	"Show",
	"ShowMultilineText",
	"ShowStatusText",
	"AddFocusedControl",
	"UpdateCursor",
	"RegisterEvents",
	"ShowBrailleOnScreen",
	"SetHybridPrintAndBrailleMode",
	"EnableContractedBrailleInput",
	"ExecuteOperation",
)


class TestITactileDisplayAPIVtable(unittest.TestCase):
	"""``ITactileDisplayAPI._methods_`` matches v1.23's vtable layout (33 methods, slots 7-39)."""

	def test_classConstructs(self) -> None:
		"""Importing the interface class succeeds with no construction error.

		comtypes validates every ``COMMETHOD`` signature at class-body
		execution time. A malformed ``argspec`` or unknown ctypes type
		raises here, before any runtime call.
		"""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		self.assertIsNotNone(ITactileDisplayAPI._methods_)
		self.assertGreater(len(ITactileDisplayAPI._methods_), 0)

	def test_methodCount(self) -> None:
		"""v1.23's vtable has 33 library-specific methods (slots 7-39)."""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		self.assertEqual(len(ITactileDisplayAPI._methods_), len(_EXPECTED_METHOD_ORDER))

	def test_methodOrderMatchesV123Typelib(self) -> None:
		"""Each COMMETHOD sits at the slot v1.23's typelib reports.

		List position N in ``_methods_`` corresponds to vtable slot 7+N.
		A swap with the library's actual order is the failure mode that
		feature 011's comtypes migration was designed to escape from;
		this assertion locks the order at unit-test time.
		"""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		actual = tuple(m.name for m in ITactileDisplayAPI._methods_)
		self.assertEqual(actual, _EXPECTED_METHOD_ORDER)

	def test_simulateDisplayAtSlot8(self) -> None:
		"""``SimulateDisplay`` is at vtable slot 8 (list index 1).

		Historical (v1.16) binary-incompatible change: ``SimulateDisplay``
		was inserted between ``Connect`` (slot 7) and ``Disconnect``
		(slot 9). v1.17 kept this slot stable. If this assertion ever
		fails, every method downstream is in the wrong slot.
		"""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		# Index 1 = vtable slot 8.
		self.assertEqual(ITactileDisplayAPI._methods_[1].name, "SimulateDisplay")

	def test_displayLiteraryBrailleAtSlot11(self) -> None:
		"""``DisplayLiteraryBraille`` is at vtable slot 11 (list index 4).

		v1.17 binary-incompatible change: inserted between
		``SetBrailleTables`` (slot 10) and what was ``SetDrawingMode``
		in v1.16 (slot 11, now slot 14 after the v1.22 insertion). Every
		method downstream of slot 10 shifts +1 versus v1.16.
		"""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		# Index 4 = vtable slot 11.
		self.assertEqual(ITactileDisplayAPI._methods_[4].name, "DisplayLiteraryBraille")

	def test_setBrailleLinePaddingAtSlot12(self) -> None:
		"""``SetBrailleLinePadding`` is at vtable slot 12 (list index 5).

		v1.22 binary-incompatible change: inserted mid-vtable between
		``DisplayLiteraryBraille`` (slot 11) and what was ``SetDrawingMode``
		in v1.21 (slot 12, now slot 14). Every method downstream shifts +2
		versus v1.21.
		"""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		# Index 5 = vtable slot 12.
		self.assertEqual(ITactileDisplayAPI._methods_[5].name, "SetBrailleLinePadding")

	def test_forceSixDotBrailleAtSlot13(self) -> None:
		"""``ForceSixDotBraille`` is at vtable slot 13 (list index 6).

		v1.22 binary-incompatible change: inserted mid-vtable alongside
		``SetBrailleLinePadding`` at slots 12-13.
		"""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		# Index 6 = vtable slot 13.
		self.assertEqual(ITactileDisplayAPI._methods_[6].name, "ForceSixDotBraille")

	def test_setHybridPrintAndBrailleModeAtSlot37(self) -> None:
		"""``SetHybridPrintAndBrailleMode`` is at vtable slot 37 (list index 30).

		v1.0.21 inserted it mid-vtable between ``ShowBrailleOnScreen``
		(slot 34 at the time) and ``EnableContractedBrailleInput``. The
		v1.22 mid-vtable insertion shifted it from slot 35 → 37.
		"""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayAPI

		# Index 30 = vtable slot 37.
		self.assertEqual(ITactileDisplayAPI._methods_[30].name, "SetHybridPrintAndBrailleMode")

	def test_wrapperFacadeExposesSimulateDisplay(self) -> None:
		"""``wrapper.py`` exposes ``simulateDisplay`` since feature 014.

		Feature 013 deliberately did NOT expose it (the COMMETHOD slot was
		declared but the Pythonic facade omitted it, deferring callback
		infrastructure to a follow-up). Feature 014 adopts caller-managed
		transport via SimulateDisplay; the facade method is required by
		FR-003 of that feature.
		"""
		from addon.tactileDisplayAPI import wrapper

		api = wrapper.TactileDisplayAPI
		self.assertTrue(
			hasattr(api, "simulateDisplay"),
			"wrapper.TactileDisplayAPI must expose simulateDisplay since feature 014",
		)


class TestITactileDisplayCallbacksVtable(unittest.TestCase):
	"""``ITactileDisplayCallbacks._methods_`` matches the v1.20 binary's expected vtable.

	The v1.20 typelib still only exposes two methods, but Joe's
	hardware testing showed the library's binary expects a 3-method
	vtable: omitting the third method AVs ``AddFocusedControl``. Feature
	024 implements the third method (``GetTranslation``) against NVDA's
	``louisHelper``.
	"""

	def test_methodOrderMatchesV118VtableShape(self) -> None:
		"""Slots 7-9 are TactileDisplayUpdated, BrailleDisplayUpdated, GetTranslation."""
		from addon.tactileDisplayAPI.comInterface import ITactileDisplayCallbacks

		actual = tuple(m.name for m in ITactileDisplayCallbacks._methods_)
		self.assertEqual(
			actual,
			("TactileDisplayUpdated", "BrailleDisplayUpdated", "GetTranslation"),
		)


class TestBrailleInputOperationCodes(unittest.TestCase):
	"""``BrailleInputOperation`` enum values match the v1.23 typelib.

	v1.23 inserted ``INVERT_LAST_TACTILE_IMAGE = 20`` between
	``SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE`` (19) and ``ROUTE_CURSOR``
	(which moved from 20 → 21). Feature 034 missed this update; feature 037
	corrects it. These assertions lock the corrected values so a re-introduced
	off-by-one is caught immediately rather than silently calling the wrong
	operation at runtime.
	"""

	def test_invertLastTactileImageIs20(self) -> None:
		"""``INVERT_LAST_TACTILE_IMAGE`` is code 20 in the v1.23 typelib."""
		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		self.assertEqual(int(BrailleInputOperation.INVERT_LAST_TACTILE_IMAGE), 20)

	def test_routeCursorIs21(self) -> None:
		"""``ROUTE_CURSOR`` is 21 after the v1.23 insertion (was 20 in v1.17)."""
		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		self.assertEqual(int(BrailleInputOperation.ROUTE_CURSOR), 21)

	def test_backspaceKeyIs35(self) -> None:
		"""``BACKSPACE_KEY`` is 35 after the v1.23 insertion (was 34 in v1.17)."""
		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		self.assertEqual(int(BrailleInputOperation.BACKSPACE_KEY), 35)


if __name__ == "__main__":
	unittest.main()
