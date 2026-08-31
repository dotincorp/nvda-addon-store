# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Negative tests for symbols deleted in feature 015.

After feature 015, the listed symbols / literals MUST NOT appear in
``addon/`` Python source — the graphic-session surfaces collapsed into
``GraphicPresentation``.

This is a structural / source-code test — it walks the tree and asserts
the absence of each symbol. Runs in CI without hardware.
"""

from __future__ import annotations

import unittest
from pathlib import Path


_ADDON_ROOT = Path(__file__).resolve().parent.parent / "addon"


# Each entry: (symbol-or-substring, brief justification for the deletion).
# Substrings are matched literally — no regex.
_REMOVED_SURFACES: tuple[tuple[str, str], ...] = (
	# Config / settings panel (FR-002)
	("useSimulateDisplay", "config flag retired"),
	("USE_SIMULATE_DISPLAY_SETTING_NAME", "config constant retired"),
	("getUseSimulateDisplay", "config getter retired"),
	# Connect-path transport (FR-001)
	("_enterViaConnect", "Connect path retired"),
	("_submitConnect", "Connect path retired"),
	("_afterConnect", "Connect path retired"),
	("_recoverBraille", "Connect-path recovery retired"),
	("_restoreBraille", "Connect-path recovery retired"),
	("TransportPath", "single transport now (SimulateDisplay)"),
	# Hand-off scaffolding (FR-003)
	("markForHandoff", "no braille-driver handoff"),
	("clearHandoffFlag", "no braille-driver handoff"),
	("waitForRelease", "no braille-driver handoff"),
	("_releaseComplete", "no braille-driver handoff"),
	("_handoffInProgress", "no braille-driver handoff"),
	("_releasedToNvda", "no braille-driver handoff"),
	("_lastPortName", "no braille-driver handoff"),
	("_userConfiguredDisplay", "no braille-driver handoff"),
	("verifyPortReleased", "no OS-level port probe"),
	("BDDETECT_DRAIN_TIMEOUT_S", "no bdDetect drain"),
	("LIBRARY_SETTLING_DELAY_S", "no settling delay"),
	("HANDOFF_TIMEOUT_USB_S", "no per-transport handoff timeout"),
	("HANDOFF_TIMEOUT_BT_S", "no per-transport handoff timeout"),
	("HANDOFF_TIMEOUT_AUTO_S", "no per-transport handoff timeout"),
	("selectHandoffTimeout", "no per-transport handoff timeout"),
	# User-facing scripts (FR-008)
	("script_exitGraphicDisplay", "manual exit gesture retired"),
	# Removed announcement (FR-010)
	("Graphic view available", "auto-entry replaces this notification"),
	# Session-collapse refactor (post-implementation; research §F)
	("GraphicDisplaySession", "session collapsed into GraphicPresentation"),
	("SessionState", "session state machine retired (graphic-mode logic is render-driven)"),
	("_triggerGraphicEnter", "session-helper removed; render-driven flow"),
	("_triggerGraphicExit", "session-helper removed; render-driven flow"),
	("_isDriverLibraryReady", "session-helper removed; checks moved into GraphicPresentation"),
	("_getGraphicSession", "session-helper removed; GraphicPresentation owns its own work"),
	("_graphicSessionModule", "session module-cache field retired"),
)


def _walkAddonPython() -> list[Path]:
	"""Return all addon source files we lint for the removed symbols."""
	files: list[Path] = []
	for candidate in _ADDON_ROOT.rglob("*.py"):
		# Exclude vendored libraries — they're not addon-owned source.
		parts = candidate.relative_to(_ADDON_ROOT).parts
		if parts and parts[0] in {"_vendor", "bleak", "bleak_winrt"}:
			continue
		files.append(candidate)
	return files


class TestRemovedSurfaces(unittest.TestCase):
	"""Each symbol in ``_REMOVED_SURFACES`` has zero occurrences in addon source."""

	def test_allSymbolsAbsent(self) -> None:
		offenders: dict[str, list[str]] = {}
		pythonFiles = _walkAddonPython()
		self.assertGreater(
			len(pythonFiles),
			0,
			"sanity check: addon/ should contain at least some .py files",
		)
		for symbol, _reason in _REMOVED_SURFACES:
			hits: list[str] = []
			for file in pythonFiles:
				try:
					text = file.read_text(encoding="utf-8")
				except UnicodeDecodeError:
					continue
				if symbol in text:
					hits.append(str(file.relative_to(_ADDON_ROOT)))
			if hits:
				offenders[symbol] = hits
		if offenders:
			lines = ["Removed surfaces still present in addon/:"]
			for symbol, files in sorted(offenders.items()):
				lines.append(f"  - {symbol}: {len(files)} file(s)")
				for file in files:
					lines.append(f"    {file}")
			self.fail("\n".join(lines))


if __name__ == "__main__":
	unittest.main()
