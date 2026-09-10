# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests that a busy Excel leaves TablePresentation.isStillValid unanswered.

``PresentationManager._stillValid`` has a third answer — None, "could not tell"
— so a transient ``RPC_E_CALL_REJECTED`` does not drop a forced table or lift a
dismissal. That answer only exists if the raise reaches it: catching COM
failures inside ``isStillValid`` and returning False turns "Excel is busy" into
"the worksheet changed", which is a decision, and on an Excel table the
worksheet check runs before any other and would make the None branch
unreachable on exactly the table type it was written for.
"""

import unittest
from unittest.mock import Mock, patch

# addon.presentations first: addon.utils.table's runtime loadModule pulls the
# driver back through presentations, so importing it first here deadlocks the
# cycle when this module is run on its own.
import addon.presentations  # noqa: F401
from addon.presentations.manager import PresentationManager
from addon.presentations.table import TablePresentation


class _ComBusy(Exception):
	"""Stands in for RPC_E_CALL_REJECTED, which Excel raises whenever it is busy."""


def makePresentation(worksheet):
	"""A TablePresentation over an Excel worksheet, bypassing __init__."""
	presentation = TablePresentation.__new__(TablePresentation)
	tableObj = Mock()
	tableObj.windowHandle = 42
	tableObj.excelWorksheetObject = worksheet
	presentation._tableObj = tableObj
	return presentation


class TestBusyExcelIsUnanswerable(unittest.TestCase):
	def _navigatorOn(self, worksheet):
		navObj = Mock()
		navObj.windowHandle = 42
		navObj.excelWorksheetObject = worksheet
		return navObj

	def test_a_refused_com_call_propagates(self):
		"""Rather than being reported as a worksheet switch."""
		worksheet = Mock()
		type(worksheet).Name = property(lambda _self: (_ for _ in ()).throw(_ComBusy()))
		presentation = makePresentation(worksheet)

		with patch.object(
			TablePresentation,
			"_getRelevantObject",
			return_value=self._navigatorOn(Mock()),
		):
			with self.assertRaises(_ComBusy):
				presentation.isStillValid()

	def test_the_manager_reads_that_as_could_not_tell(self):
		worksheet = Mock()
		type(worksheet).Name = property(lambda _self: (_ for _ in ()).throw(_ComBusy()))
		presentation = makePresentation(worksheet)

		with patch.object(
			TablePresentation,
			"_getRelevantObject",
			return_value=self._navigatorOn(Mock()),
		):
			self.assertIsNone(PresentationManager._stillValid(presentation, None))

	def test_a_real_worksheet_switch_is_still_a_hard_no(self):
		"""The check must keep answering False when it can actually tell."""
		here = Mock()
		here.Name = "Sheet1"
		there = Mock()
		there.Name = "Sheet2"
		presentation = makePresentation(here)

		with patch.object(
			TablePresentation,
			"_getRelevantObject",
			return_value=self._navigatorOn(there),
		):
			self.assertFalse(presentation.isStillValid())


if __name__ == "__main__":
	unittest.main()
