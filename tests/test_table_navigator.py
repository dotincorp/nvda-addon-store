# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for table navigator movement after scroll."""

import unittest
from unittest.mock import MagicMock, Mock, patch

from addon.configuration import TableNavigatorAfterScroll
from addon.utils import table


class FakeCellObject:
	"""Mock cell object for testing."""

	def __init__(self, row: int, col: int):
		self.rowNumber = row
		self.columnNumber = col


class TestMoveNavigatorAfterScroll(unittest.TestCase):
	"""Test the _moveNavigatorAfterScroll method."""

	def setUp(self):
		"""Set up test fixtures."""
		# Create mock table object
		self.mockTableObj = Mock()
		self.mockTableObj.role = table.ROLE_TABLE
		self.mockTableObj.name = "Test Table"

		# Create Table instance
		self.tableInstance = table.Table(self.mockTableObj, hCellPadding=1, vCellPadding=1)
		self.tableInstance.numVisibleRows = 3
		self.tableInstance.numVisibleCols = 4
		self.tableInstance.firstVisibleRow = 0
		self.tableInstance.firstVisibleCol = 0

	@patch("addon.utils.table.configuration")
	def test_setting_do_nothing_does_not_move(self, mock_config):
		"""When setting is DO_NOTHING, navigator should not move."""
		mock_config.getTableNavigatorAfterScroll.return_value = TableNavigatorAfterScroll.DO_NOTHING
		mock_config.TableNavigatorAfterScroll = TableNavigatorAfterScroll

		with patch.object(self.tableInstance, "_selectCell", return_value=True) as mock_selectCell:
			self.tableInstance._moveNavigatorAfterScroll()

			# Verify _selectCell was not called
			mock_selectCell.assert_not_called()

	@patch("addon.utils.table.configuration")
	def test_moves_to_first_cell(self, mock_config):
		"""When setting is FIRST_CELL, _selectCell should be called with first visible cell."""
		mock_config.getTableNavigatorAfterScroll.return_value = TableNavigatorAfterScroll.FIRST_CELL
		mock_config.TableNavigatorAfterScroll = TableNavigatorAfterScroll

		# Create fake cells
		cells = [
			FakeCellObject(1, 1),  # First cell (1-based indexing)
			FakeCellObject(1, 2),
			FakeCellObject(2, 1),
		]

		with patch.object(self.tableInstance, "_selectCell", return_value=True) as mock_selectCell:
			with patch.object(self.tableInstance, "getTableCells", return_value=iter(cells)):
				self.tableInstance._moveNavigatorAfterScroll()

				# Verify _selectCell was called with first cell
				mock_selectCell.assert_called_once_with(cells[0], 0, 0)

	@patch("addon.utils.table.configuration")
	def test_moves_to_center_cell(self, mock_config):
		"""When setting is CENTER_CELL, _selectCell should be called with center cell."""
		mock_config.getTableNavigatorAfterScroll.return_value = TableNavigatorAfterScroll.CENTER_CELL
		mock_config.TableNavigatorAfterScroll = TableNavigatorAfterScroll

		# Set up table dimensions: 3 rows, 4 cols
		# Center: row 1 (3 // 2), col 2 (4 // 2)
		# In 1-based indexing: row 2, col 3
		cells = [
			FakeCellObject(1, 1),
			FakeCellObject(1, 2),
			FakeCellObject(1, 3),
			FakeCellObject(2, 1),
			FakeCellObject(2, 2),
			FakeCellObject(2, 3),  # This is the center: (0 + 3//2) = 1, (0 + 4//2) = 2
		]

		# Mock table dimensions for center cell calculation
		with patch.object(type(self.tableInstance), "tableRowCount", 3):
			with patch.object(type(self.tableInstance), "tableColumnCount", 4):
				with patch.object(self.tableInstance, "_selectCell", return_value=True) as mock_selectCell:
					with patch.object(self.tableInstance, "getTableCells", return_value=iter(cells)):
						self.tableInstance._moveNavigatorAfterScroll()

						# Center is at 0-based (1, 2), which is 1-based (2, 3)
						# That's cells[5] in our list
						mock_selectCell.assert_called_once_with(cells[5], 1, 2)

	@patch("addon.utils.table.configuration")
	def test_returns_early_if_not_yet_drawn(self, mock_config):
		"""Should return early if table dimensions not set."""
		mock_config.getTableNavigatorAfterScroll.return_value = TableNavigatorAfterScroll.FIRST_CELL
		mock_config.TableNavigatorAfterScroll = TableNavigatorAfterScroll

		# Clear dimensions
		self.tableInstance.numVisibleRows = None
		self.tableInstance.numVisibleCols = None

		with patch.object(self.tableInstance, "_selectCell", return_value=True) as mock_selectCell:
			self.tableInstance._moveNavigatorAfterScroll()

			# Verify _selectCell was not called
			mock_selectCell.assert_not_called()

	@patch("addon.utils.table.configuration")
	@patch("addon.utils.table.log")
	def test_logs_when_cell_not_found(self, mock_log, mock_config):
		"""Should log debug message when target cell not found."""
		mock_config.getTableNavigatorAfterScroll.return_value = TableNavigatorAfterScroll.FIRST_CELL
		mock_config.TableNavigatorAfterScroll = TableNavigatorAfterScroll

		# Empty cells list - target won't be found
		cells: list[FakeCellObject] = []

		with patch.object(self.tableInstance, "_selectCell", return_value=True) as mock_selectCell:
			with patch.object(self.tableInstance, "getTableCells", return_value=iter(cells)):
				self.tableInstance._moveNavigatorAfterScroll()

				# Verify debug log was called
				mock_log.debug.assert_called_once()
				# Verify _selectCell was not called (no matching cell)
				mock_selectCell.assert_not_called()


class TestCenterCellClamping(unittest.TestCase):
	"""Test center cell calculation clamps to actual table dimensions."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mockTableObj = Mock()
		self.mockTableObj.role = table.ROLE_TABLE
		self.mockTableObj.name = "Test Table"

		self.tableInstance = table.Table(self.mockTableObj, hCellPadding=1, vCellPadding=1)

	@patch("addon.utils.table.configuration")
	def test_center_cell_clamped_when_table_smaller_than_window(self, mock_config):
		"""Center cell should be clamped when table is smaller than visible window."""
		mock_config.getTableNavigatorAfterScroll.return_value = TableNavigatorAfterScroll.CENTER_CELL
		mock_config.TableNavigatorAfterScroll = TableNavigatorAfterScroll

		# Set up: visible window is 4x6, but table is only 5x3
		self.tableInstance.numVisibleRows = 4
		self.tableInstance.numVisibleCols = 6
		self.tableInstance.firstVisibleRow = 0
		self.tableInstance.firstVisibleCol = 0

		# Mock table dimensions
		with patch.object(type(self.tableInstance), "tableRowCount", 5):
			with patch.object(type(self.tableInstance), "tableColumnCount", 3):
				# Table has 3 cols, visible window wants 6
				# actualVisibleCols = min(6, 3 - 0) = 3
				# targetCol = 0 + (3 // 2) = 1 (center of 3 columns)
				# Table has 5 rows, visible window wants 4
				# actualVisibleRows = min(4, 5 - 0) = 4
				# targetRow = 0 + (4 // 2) = 2

				# Create cells including the expected center
				cells = [
					FakeCellObject(1, 1),
					FakeCellObject(1, 2),  # col 1 (0-based)
					FakeCellObject(2, 1),
					FakeCellObject(2, 2),
					FakeCellObject(3, 1),
					FakeCellObject(3, 2),  # row 2, col 1 (0-based) - the center
				]

				with patch.object(self.tableInstance, "_selectCell", return_value=True) as mock_selectCell:
					with patch.object(self.tableInstance, "getTableCells", return_value=iter(cells)):
						self.tableInstance._moveNavigatorAfterScroll()

						# Center should be row 2, col 1 (0-based) = row 3, col 2 (1-based)
						mock_selectCell.assert_called_once_with(cells[5], 2, 1)

	@patch("addon.utils.table.configuration")
	def test_center_cell_at_end_of_table(self, mock_config):
		"""Center cell should be within bounds when scrolled to end of table."""
		mock_config.getTableNavigatorAfterScroll.return_value = TableNavigatorAfterScroll.CENTER_CELL
		mock_config.TableNavigatorAfterScroll = TableNavigatorAfterScroll

		# Scrolled to end: firstVisibleRow=4, but table only has 5 rows
		self.tableInstance.numVisibleRows = 4
		self.tableInstance.numVisibleCols = 6
		self.tableInstance.firstVisibleRow = 4  # Near end
		self.tableInstance.firstVisibleCol = 0

		with patch.object(type(self.tableInstance), "tableRowCount", 5):
			with patch.object(type(self.tableInstance), "tableColumnCount", 3):
				# actualVisibleRows = min(4, 5 - 4) = 1 (only 1 row visible)
				# targetRow = 4 + (1 // 2) = 4 (the only visible row)
				# actualVisibleCols = min(6, 3 - 0) = 3
				# targetCol = 0 + (3 // 2) = 1

				cells = [
					FakeCellObject(5, 1),
					FakeCellObject(5, 2),  # row 4, col 1 (0-based) - the center
					FakeCellObject(5, 3),
				]

				with patch.object(self.tableInstance, "_selectCell", return_value=True) as mock_selectCell:
					with patch.object(self.tableInstance, "getTableCells", return_value=iter(cells)):
						self.tableInstance._moveNavigatorAfterScroll()

						# Center should be row 4, col 1 (0-based) = row 5, col 2 (1-based)
						mock_selectCell.assert_called_once_with(cells[1], 4, 1)


class TestSelectCellRegularTable(unittest.TestCase):
	"""Test _selectCell for regular tables (no TreeInterceptor)."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mockTableObj = Mock()
		self.mockTableObj.role = table.ROLE_TABLE
		self.mockTableObj.UIAElement = None  # Not a UIA table
		self.tableInstance = table.Table(self.mockTableObj, hCellPadding=1, vCellPadding=1)

	@patch("addon.utils.table.core")
	@patch("addon.utils.table.api")
	def test_returns_false_for_non_nvda_object(self, mock_api, mock_core):
		"""Should return False if cell is not an NVDAObject."""
		fake_cell = FakeCellObject(1, 1)  # Not an NVDAObject

		result = self.tableInstance._selectCell(fake_cell, 0, 0)  # type: ignore

		self.assertFalse(result)
		mock_core.callLater.assert_not_called()

	@patch("addon.utils.table.core")
	@patch("addon.utils.table.api")
	@patch("addon.utils.table.NVDAObject", new_callable=lambda: type("NVDAObject", (), {}))
	def test_defers_navigator_movement(self, mock_NVDAObject, mock_api, mock_core):
		"""Should defer navigator movement via core.callLater."""
		# Create a mock cell that passes isinstance check
		mock_cell = MagicMock(spec=mock_NVDAObject)
		mock_cell.treeInterceptor = None  # No TreeInterceptor

		result = self.tableInstance._selectCell(mock_cell, 0, 0)

		self.assertTrue(result)
		mock_core.callLater.assert_called_once()
		# First arg should be delay (10ms)
		call_args = mock_core.callLater.call_args
		self.assertEqual(call_args[0][0], 10)

	@patch("addon.utils.table.core")
	@patch("addon.utils.table.api")
	@patch("addon.utils.table.NVDAObject", new_callable=lambda: type("NVDAObject", (), {}))
	def test_calls_set_navigator_for_regular_table(self, mock_NVDAObject, mock_api, mock_core):
		"""Should call setNavigatorObject for regular tables."""
		mock_cell = MagicMock(spec=mock_NVDAObject)
		mock_cell.treeInterceptor = None

		self.tableInstance._selectCell(mock_cell, 0, 0)

		# Get the deferred function and call it
		deferred_func = mock_core.callLater.call_args[0][1]
		deferred_func()

		mock_api.setNavigatorObject.assert_called_once_with(mock_cell)


class TestSelectCellVirtualBuffer(unittest.TestCase):
	"""Test _selectCell for virtual buffer tables (web documents)."""

	def setUp(self):
		"""Set up test fixtures."""
		self.mockTableObj = Mock()
		self.mockTableObj.role = table.ROLE_TABLE
		self.mockTableObj.UIAElement = None  # Not a UIA table for these tests
		self.tableInstance = table.Table(self.mockTableObj, hCellPadding=1, vCellPadding=1)

	@patch("addon.utils.table.core")
	@patch("addon.utils.table.api")
	@patch("addon.utils.table.NVDAObject", new_callable=lambda: type("NVDAObject", (), {}))
	def test_moves_browse_mode_caret_for_virtual_buffer(self, mock_NVDAObject, mock_api, mock_core):
		"""Should move browse mode caret for cells in virtual buffers in browse mode."""
		mock_cell = MagicMock(spec=mock_NVDAObject)

		# Set up TreeInterceptor mock in browse mode (passThrough=False)
		mock_text_info = MagicMock()
		mock_tree_interceptor = MagicMock()
		mock_tree_interceptor.isReady = True
		mock_tree_interceptor.passThrough = False  # Browse mode
		mock_tree_interceptor.makeTextInfo.return_value = mock_text_info
		mock_cell.treeInterceptor = mock_tree_interceptor

		self.tableInstance._selectCell(mock_cell, 0, 0)

		# Get the deferred function and call it
		deferred_func = mock_core.callLater.call_args[0][1]
		deferred_func()

		# Verify TreeInterceptor was used
		mock_tree_interceptor.makeTextInfo.assert_called_once_with(mock_cell)
		mock_text_info.collapse.assert_called_once()
		# Verify selection was set
		self.assertEqual(mock_tree_interceptor.selection, mock_text_info)
		# Verify navigator was NOT called (TreeInterceptor handles it)
		mock_api.setNavigatorObject.assert_not_called()

	@patch("addon.utils.table.core")
	@patch("addon.utils.table.api")
	@patch("addon.utils.table.NVDAObject", new_callable=lambda: type("NVDAObject", (), {}))
	def test_falls_back_to_setFocus_on_tree_interceptor_error(
		self,
		mock_NVDAObject,
		mock_api,
		mock_core,
	):
		"""Should fall back to setFocus if TreeInterceptor fails in browse mode."""
		mock_cell = MagicMock(spec=mock_NVDAObject)
		mock_cell.setFocus = MagicMock()  # Add setFocus method

		# Set up TreeInterceptor that raises an error in browse mode
		mock_tree_interceptor = MagicMock()
		mock_tree_interceptor.isReady = True
		mock_tree_interceptor.passThrough = False  # Browse mode
		mock_tree_interceptor.makeTextInfo.side_effect = NotImplementedError("Test error")
		mock_cell.treeInterceptor = mock_tree_interceptor

		self.tableInstance._selectCell(mock_cell, 0, 0)

		# Get the deferred function and call it
		deferred_func = mock_core.callLater.call_args[0][1]
		deferred_func()

		# Verify fallback to setFocus
		mock_cell.setFocus.assert_called_once()

	@patch("addon.utils.table.core")
	@patch("addon.utils.table.api")
	@patch("addon.utils.table.NVDAObject", new_callable=lambda: type("NVDAObject", (), {}))
	def test_uses_setFocus_when_tree_interceptor_not_ready(
		self,
		mock_NVDAObject,
		mock_api,
		mock_core,
	):
		"""Should use setFocus when TreeInterceptor exists but is not ready."""
		mock_cell = MagicMock(spec=mock_NVDAObject)
		mock_cell.setFocus = MagicMock()  # Add setFocus method for UIA objects

		# Set up TreeInterceptor that is not ready
		mock_tree_interceptor = MagicMock()
		mock_tree_interceptor.isReady = False
		mock_cell.treeInterceptor = mock_tree_interceptor

		self.tableInstance._selectCell(mock_cell, 0, 0)

		# Get the deferred function and call it
		deferred_func = mock_core.callLater.call_args[0][1]
		deferred_func()

		# Verify setFocus was used (not TreeInterceptor or navigator)
		mock_cell.setFocus.assert_called_once()
		mock_tree_interceptor.makeTextInfo.assert_not_called()
		mock_api.setNavigatorObject.assert_not_called()

	@patch("addon.utils.table.core")
	@patch("addon.utils.table.api")
	@patch("addon.utils.table.NVDAObject", new_callable=lambda: type("NVDAObject", (), {}))
	def test_uses_setFocus_in_focus_mode(
		self,
		mock_NVDAObject,
		mock_api,
		mock_core,
	):
		"""Should use setFocus when TreeInterceptor is in focus mode (passThrough=True)."""
		mock_cell = MagicMock(spec=mock_NVDAObject)
		mock_cell.setFocus = MagicMock()  # Add setFocus method for UIA objects

		# Set up TreeInterceptor in focus mode (passThrough=True)
		mock_tree_interceptor = MagicMock()
		mock_tree_interceptor.isReady = True
		mock_tree_interceptor.passThrough = True  # Focus mode
		mock_cell.treeInterceptor = mock_tree_interceptor

		self.tableInstance._selectCell(mock_cell, 0, 0)

		# Get the deferred function and call it
		deferred_func = mock_core.callLater.call_args[0][1]
		deferred_func()

		# Verify setFocus was used (not TreeInterceptor browse mode)
		mock_cell.setFocus.assert_called_once()
		mock_tree_interceptor.makeTextInfo.assert_not_called()
		mock_api.setNavigatorObject.assert_not_called()


if __name__ == "__main__":
	unittest.main()
