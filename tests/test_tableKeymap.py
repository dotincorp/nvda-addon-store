# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for table mode's gesture bindings.

Mirrors ``TestGraphicPresentationGestures`` in ``test_unified_keymap.py``: table
mode takes the same key layout as graphic mode, so the two are held to the same
standard.
"""

import unittest
from unittest.mock import MagicMock, patch

import controlTypes

from addon.presentations.table import TablePresentation


class _MockGesture:
	"""Stand-in for an InputGesture carrying only the identifiers getScript reads.

	``@script`` registers its gestures under NVDA's normalized form, so the mock
	normalizes too and tests can use natural casing.
	"""

	def __init__(self, identifier: str) -> None:
		from inputCore import normalizeGestureIdentifier

		normalized = normalizeGestureIdentifier(identifier)
		self.id = normalized
		self.normalizedIdentifiers = [normalized]


def makePresentation() -> TablePresentation:
	"""A TablePresentation over a mocked table object and display."""
	tableObj = MagicMock()
	tableObj.role = controlTypes.Role.TABLE
	tableObj.name = "Test Table"
	# Not an Excel worksheet, so the plain Table model is used.
	del tableObj.excelWorksheetObject
	display = MagicMock()
	display.horizontalCellSpacing = 1
	display.verticalCellSpacing = 2
	return TablePresentation(tableObj, display)


class TestTableGestureBindings(unittest.TestCase):
	def _assertBound(self, gestures: dict[str, str]) -> None:
		presentation = makePresentation()
		for gesture, expectedName in gestures.items():
			scriptObj = presentation.getScript(_MockGesture(gesture))
			self.assertIsNotNone(scriptObj, f"no handler for {gesture}")
			self.assertEqual(
				getattr(scriptObj, "__name__", ""),
				expectedName,
				f"{gesture} bound to the wrong handler",
			)

	def test_single_key_page_steps(self):
		"""f1/f4 horizontal, f2/f3 vertical — the same layout as graphic mode."""
		self._assertBound(
			{
				"br(dotPad):f1": "script_pageLeft",
				"br(dotPad):f2": "script_pageUp",
				"br(dotPad):f3": "script_pageDown",
				"br(dotPad):f4": "script_pageRight",
			},
		)

	def test_chorded_single_steps(self):
		self._assertBound(
			{
				"br(dotPad):f1+f2": "script_rowUp",
				"br(dotPad):f3+f4": "script_rowDown",
				"br(dotPad):panLeft+f1": "script_columnLeft",
				"br(dotPad):panRight+f4": "script_columnRight",
			},
		)

	def test_long_press_edge_jumps(self):
		self._assertBound(
			{
				"br(dotPad):longPress(f1)": "script_jumpToFirstColumn",
				"br(dotPad):longPress(f2)": "script_jumpToFirstRow",
				"br(dotPad):longPress(f3)": "script_jumpToLastRow",
				"br(dotPad):longPress(f4)": "script_jumpToLastColumn",
			},
		)

	def test_the_mode_switches_stay_reachable(self):
		"""Table mode must not shadow the driver-level escapes.

		These fall through to the driver, which is how a user leaves table mode
		or enters graphic mode or screen capture from it.
		"""
		presentation = makePresentation()
		for gesture in (
			"br(dotPad):f2+f4",
			"br(dotPad):f1+f3",
			"br(dotPad):f2+f3",
			"br(dotPad):longPress(f1+f3)",
			"br(dotPad):longPress(f2+f3)",
		):
			self.assertIsNone(
				presentation.getScript(_MockGesture(gesture)),
				f"{gesture} must fall through to the driver",
			)


class TestTableGestureActions(unittest.TestCase):
	"""Each handler moves the viewport and asks for a redraw."""

	def setUp(self):
		self.presentation = makePresentation()
		self.tableData = MagicMock()
		self.presentation._tableData = self.tableData
		self.renderer = MagicMock()
		patcher = patch("addon.presentations.table.getActiveRenderer", return_value=self.renderer)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _run(self, scriptName: str):
		getattr(self.presentation, scriptName)(MagicMock())

	def test_page_steps_move_a_screenful(self):
		for scriptName, method in (
			("script_pageLeft", "scrollLeft"),
			("script_pageRight", "scrollRight"),
			("script_pageUp", "scrollUp"),
			("script_pageDown", "scrollDown"),
		):
			with self.subTest(scriptName):
				self.tableData.reset_mock()
				self._run(scriptName)
				getattr(self.tableData, method).assert_called_once_with()

	def test_single_steps_move_one_row_or_column(self):
		for scriptName, method, amount in (
			("script_rowUp", "scrollByRows", -1),
			("script_rowDown", "scrollByRows", 1),
			("script_columnLeft", "scrollByCols", -1),
			("script_columnRight", "scrollByCols", 1),
		):
			with self.subTest(scriptName):
				self.tableData.reset_mock()
				self._run(scriptName)
				getattr(self.tableData, method).assert_called_once_with(amount)

	def test_edge_jumps(self):
		for scriptName, method in (
			("script_jumpToFirstRow", "scrollToFirstRow"),
			("script_jumpToLastRow", "scrollToLastRow"),
			("script_jumpToFirstColumn", "scrollToFirstCol"),
			("script_jumpToLastColumn", "scrollToLastCol"),
		):
			with self.subTest(scriptName):
				self.tableData.reset_mock()
				self._run(scriptName)
				getattr(self.tableData, method).assert_called_once_with()

	def test_a_move_requests_a_redraw(self):
		self.tableData.scrollByRows.return_value = True

		self._run("script_rowDown")

		self.renderer.requestRender.assert_called_once_with()

	def test_the_navigator_follows_the_users_setting(self):
		"""Only scrollForward/scrollBack moved the navigator; every step must."""
		self.tableData.scrollByRows.return_value = True

		self._run("script_rowDown")

		self.tableData.moveNavigatorAfterScroll.assert_called_once_with()

	def test_a_refused_move_neither_redraws_nor_moves_the_navigator(self):
		"""At an edge nothing changed, so there is nothing to redraw."""
		self.tableData.scrollByRows.return_value = False

		self._run("script_rowDown")

		self.renderer.requestRender.assert_not_called()
		self.tableData.moveNavigatorAfterScroll.assert_not_called()

	def test_a_missing_renderer_is_a_silent_no_op(self):
		self.tableData.scrollByRows.return_value = True
		with patch("addon.presentations.table.getActiveRenderer", return_value=None):
			self._run("script_rowDown")


if __name__ == "__main__":
	unittest.main()
