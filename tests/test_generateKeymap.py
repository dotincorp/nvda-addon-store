"""Tests for tools/generateKeymap.py.

The generator parses gesture bindings out of the addon source with ``ast``
rather than importing it, so these tests need no NVDA on ``sys.path``. Fixture
sources are inline strings; the integration tests at the bottom run against the
real repository.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import generateKeymap as gk  # noqa: E402


DRIVER_FIXTURE = textwrap.dedent(
	"""
	class BrailleDisplayDriver(braille.BrailleDisplayDriver):
		@script(
			description=_(
				# Translators: a description.
				"Scrolls the multiline display backwards",
			),
			category=SCRCAT_BRAILLE,
			gesture="br(dotPad):f1",
		)
		def script_multilineBack(self, _gesture):
			pass

		@script(
			description=_("Refreshes the Dot Pad display"),
			category=SCRCAT_BRAILLE,
		)
		def script_refresh(self, _gesture):
			pass

		def notAScript(self):
			pass

		gestureMap = inputCore.GlobalGestureMap(
			{
				"globalCommands.GlobalCommands": {
					"braille_scrollBack": "br(dotPad):panLeft",
					"review_activate": "br(dotPad):f3",
				},
			},
		)
	""",
)


class TestDescriptionExtraction(unittest.TestCase):
	"""``description=`` is unwrapped from the ``_()`` translator call."""

	def test_unwraps_translator_call(self) -> None:
		bindings = gk.parseScriptBindings(DRIVER_FIXTURE, tier=1, sourcePath="driver.py")
		byName = {b.scriptName: b for b in bindings}
		self.assertEqual(
			byName["script_multilineBack"].description,
			"Scrolls the multiline display backwards",
		)

	def test_handles_single_line_translator_call(self) -> None:
		bindings = gk.parseScriptBindings(DRIVER_FIXTURE, tier=1, sourcePath="driver.py")
		byName = {b.scriptName: b for b in bindings}
		self.assertEqual(byName["script_refresh"].description, "Refreshes the Dot Pad display")


class TestScriptBindingParsing(unittest.TestCase):
	"""``@script`` decorators are located and their ``gesture=`` read."""

	def test_finds_bound_script(self) -> None:
		bindings = gk.parseScriptBindings(DRIVER_FIXTURE, tier=1, sourcePath="driver.py")
		byName = {b.scriptName: b for b in bindings}
		self.assertEqual(byName["script_multilineBack"].gesture, "f1")

	def test_records_unbound_script_with_none_gesture(self) -> None:
		"""A ``@script`` without ``gesture=`` is user-assignable, not omitted.

		This is the drift that let ``script_refresh`` go undocumented.
		"""
		bindings = gk.parseScriptBindings(DRIVER_FIXTURE, tier=1, sourcePath="driver.py")
		byName = {b.scriptName: b for b in bindings}
		self.assertIn("script_refresh", byName)
		self.assertIsNone(byName["script_refresh"].gesture)

	def test_ignores_undecorated_methods(self) -> None:
		bindings = gk.parseScriptBindings(DRIVER_FIXTURE, tier=1, sourcePath="driver.py")
		self.assertNotIn("notAScript", {b.scriptName for b in bindings})

	def test_records_owning_class(self) -> None:
		bindings = gk.parseScriptBindings(DRIVER_FIXTURE, tier=1, sourcePath="driver.py")
		self.assertEqual({b.owner for b in bindings}, {"BrailleDisplayDriver"})


class TestGestureMapParsing(unittest.TestCase):
	"""The ``gestureMap`` dict literal yields tier 0 bindings."""

	def test_extracts_entries(self) -> None:
		bindings = gk.parseGestureMapBindings(DRIVER_FIXTURE, sourcePath="driver.py")
		byGesture = {b.gesture: b.scriptName for b in bindings}
		self.assertEqual(byGesture["panLeft"], "braille_scrollBack")
		self.assertEqual(byGesture["f3"], "review_activate")

	def test_entries_are_tier_zero(self) -> None:
		bindings = gk.parseGestureMapBindings(DRIVER_FIXTURE, sourcePath="driver.py")
		self.assertEqual({b.tier for b in bindings}, {0})


class TestGestureSorting(unittest.TestCase):
	"""Ordering is deterministic: singles, then chords, then long-press."""

	def test_singles_before_chords(self) -> None:
		ordered = sorted(["f2+f4", "f1", "f4"], key=gk.gestureSortKey)
		self.assertEqual(ordered, ["f1", "f4", "f2+f4"])

	def test_long_press_sorts_after_short_press(self) -> None:
		ordered = sorted(["longPress(f1)", "f4"], key=gk.gestureSortKey)
		self.assertEqual(ordered, ["f4", "longPress(f1)"])

	def test_hardware_key_order(self) -> None:
		ordered = sorted(["panLeft", "f3", "f1", "panRight"], key=gk.gestureSortKey)
		self.assertEqual(ordered, ["f1", "f3", "panLeft", "panRight"])


class TestMarkerReplacement(unittest.TestCase):
	"""Only the region between markers is rewritten."""

	MARKED = (
		"# Title\n\nProse above.\n\n"
		"<!-- BEGIN GENERATED: tier1 -->\nstale\n<!-- END GENERATED: tier1 -->\n\n"
		"Prose below.\n"
	)

	def test_replaces_between_markers(self) -> None:
		result = gk.applyGeneratedSections(self.MARKED, {"tier1": "fresh"})
		self.assertIn("fresh", result)
		self.assertNotIn("stale", result)

	def test_preserves_surrounding_prose(self) -> None:
		result = gk.applyGeneratedSections(self.MARKED, {"tier1": "fresh"})
		self.assertIn("Prose above.", result)
		self.assertIn("Prose below.", result)

	def test_keeps_markers_in_place(self) -> None:
		result = gk.applyGeneratedSections(self.MARKED, {"tier1": "fresh"})
		self.assertIn("<!-- BEGIN GENERATED: tier1 -->", result)
		self.assertIn("<!-- END GENERATED: tier1 -->", result)

	def test_missing_marker_raises(self) -> None:
		with self.assertRaises(gk.KeymapDocError):
			gk.applyGeneratedSections("# Title\n", {"tier1": "fresh"})

	def test_is_idempotent(self) -> None:
		once = gk.applyGeneratedSections(self.MARKED, {"tier1": "fresh"})
		twice = gk.applyGeneratedSections(once, {"tier1": "fresh"})
		self.assertEqual(once, twice)


class TestRemovedGestureValidation(unittest.TestCase):
	"""The hand-written "Removed gestures" table is checked against reality."""

	DOC = textwrap.dedent(
		"""
		## Removed gestures (rebinding via NVDA's Input Gestures dialog)

		| Old gesture | Old action | Rebinding path |
		|---|---|---|
		| `f1+f2` | control+home | System -> keyboard |
		| `f3+f4` | control+end | System -> keyboard |

		## Something else
		""",
	)

	def test_parses_removed_gestures(self) -> None:
		self.assertEqual(gk.parseRemovedGestures(self.DOC), ["f1+f2", "f3+f4"])

	def test_stops_at_next_heading(self) -> None:
		"""Rows from later tables must not leak into the removed list."""
		doc = self.DOC + "\n| `f1` | something | else |\n"
		self.assertEqual(gk.parseRemovedGestures(doc), ["f1+f2", "f3+f4"])

	def test_conflict_detected_when_removed_gesture_is_bound(self) -> None:
		conflicts = gk.findRemovedGestureConflicts(self.DOC, {"f1+f2", "f2+f4"})
		self.assertEqual(conflicts, ["f1+f2"])

	def test_no_conflict_when_removed_gestures_stay_unbound(self) -> None:
		conflicts = gk.findRemovedGestureConflicts(self.DOC, {"f2+f4"})
		self.assertEqual(conflicts, [])

	def test_tier_two_reuse_is_not_a_conflict(self) -> None:
		"""Only global bindings contradict the table.

		``f2`` is documented as a removed driver-level backspace while
		``GraphicPresentation`` binds it as pan-up. Passing only tier 0/1
		gestures is what keeps that legitimate reuse quiet.
		"""
		conflicts = gk.findRemovedGestureConflicts(self.DOC, set())
		self.assertEqual(conflicts, [])


class TestTableRendering(unittest.TestCase):
	"""Rendered rows are markdown tables with backticked gestures."""

	def test_renders_gesture_and_description(self) -> None:
		binding = gk.Binding(
			gesture="f1",
			scriptName="script_multilineBack",
			description="Scrolls the multiline display backwards",
			tier=1,
			owner="BrailleDisplayDriver",
			sourcePath="driver.py",
		)
		table = gk.renderBindingTable([binding])
		self.assertIn("| `f1` | Scrolls the multiline display backwards |", table)

	def test_empty_input_renders_placeholder(self) -> None:
		self.assertIn("None", gk.renderBindingTable([]))


class TestRealRepository(unittest.TestCase):
	"""Integration: the generator agrees with the checked-in documentation."""

	def test_collects_known_bindings(self) -> None:
		bindings = gk.collectBindings(REPO_ROOT)
		bound = {b.gesture for b in bindings if b.gesture}
		# Spot-check one binding per tier.
		self.assertIn("panLeft", bound)
		self.assertIn("longPress(f2+f3)", bound)
		self.assertIn("f1+f2+f3+f4", bound)

	def test_refresh_is_reported_as_unbound(self) -> None:
		bindings = gk.collectBindings(REPO_ROOT)
		unbound = {b.scriptName for b in bindings if b.gesture is None}
		self.assertIn("script_refresh", unbound)

	def test_graphic_bindings_are_tier_two(self) -> None:
		bindings = gk.collectBindings(REPO_ROOT)
		graphic = [b for b in bindings if b.owner == "GraphicPresentation"]
		self.assertTrue(graphic, "GraphicPresentation must contribute bindings")
		self.assertEqual({b.tier for b in graphic}, {2})

	def test_checked_in_doc_is_up_to_date(self) -> None:
		"""``--dry-run`` exits 0 against a clean tree.

		If this fails, run ``python tools/generateKeymap.py`` and commit.
		"""
		self.assertEqual(gk.main(["--dry-run"], repo_root=REPO_ROOT), 0)

	def test_generation_is_idempotent(self) -> None:
		docPath = REPO_ROOT / "docs" / "keymap.md"
		original = docPath.read_text(encoding="utf-8")
		once = gk.renderDocument(original, gk.collectBindings(REPO_ROOT))
		twice = gk.renderDocument(once, gk.collectBindings(REPO_ROOT))
		self.assertEqual(once, twice)


class TestMainExitCodes(unittest.TestCase):
	"""``--dry-run`` reports drift through the exit code, like generateLibraryInis."""

	def test_dry_run_exits_one_when_stale(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			fakeRoot = Path(tmp)
			(fakeRoot / "docs").mkdir()
			(fakeRoot / "tools").mkdir()
			# Copy the real sources so collection works, but stale the doc.
			gk_docs = fakeRoot / "docs" / "keymap.md"
			real = (REPO_ROOT / "docs" / "keymap.md").read_text(encoding="utf-8")
			gk_docs.write_text(
				gk.applyGeneratedSections(real, {name: "stale" for name in gk.SECTION_NAMES}),
				encoding="utf-8",
			)
			# --dry-run prints the whole diff; capture it so the suite stays readable.
			buffer = io.StringIO()
			with contextlib.redirect_stdout(buffer):
				exitCode = gk.main(["--dry-run"], repo_root=fakeRoot, sourceRoot=REPO_ROOT)
			self.assertEqual(exitCode, 1)
			self.assertIn("stale", buffer.getvalue())


if __name__ == "__main__":
	unittest.main()
