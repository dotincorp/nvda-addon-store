# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Regression guard: ``renderBrailleBytes`` stays log-and-drop in feature 017.

The 20-cell text strip stays NVDA-driven in every mode (FR-009). The
library's ``BrailleDisplayUpdated`` callback (status-strip channel)
remains log-and-drop — consuming it is out of scope for feature 017 and
would surprise users by replacing NVDA's familiar strip behaviour with
the library's cursor / font metadata.

If a future refactor accidentally wires ``renderBrailleBytes`` to write
to a display surface, this test fails — surfacing the regression at CI
time instead of when a user notices the strip behaviour changed.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestRenderBrailleBytesStaysLogAndDrop(unittest.TestCase):
	"""``renderBrailleBytes`` must not write to any display surface."""

	def test_renderBrailleBytes_still_log_and_drop(self) -> None:
		from addon.tactileDisplayAPI import simulatedDisplay

		# Patch the entire braille handler module — if the function tries to
		# look up any display or call any handler method, this raises.
		fakeHandler = MagicMock(name="brailleHandler")
		with patch.object(simulatedDisplay, "_getBrailleHandler", return_value=fakeHandler):
			# Must not raise. Must not touch the handler.
			simulatedDisplay.renderBrailleBytes(b"\x01\x02\x03\x04\x05")

		# Handler-level methods MUST NOT have been called.
		self.assertFalse(
			fakeHandler.display.called or fakeHandler.method_calls,
			"renderBrailleBytes called handler methods — feature 017 forbids "
			"consuming the 20-cell strip channel; the library's status-strip "
			"output must stay log-and-drop.",
		)


if __name__ == "__main__":
	unittest.main()
