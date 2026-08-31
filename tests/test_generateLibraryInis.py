# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for tools/generateLibraryInis.py (feature 018)."""

import contextlib
import io
import logging
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import generateLibraryInis as gli  # noqa: E402


@contextlib.contextmanager
def _temporarily_flip_unicode_gate(value):
	"""Override ``gli.LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI`` for the duration of the block.

	The gate is a module-level constant the generator reads at every call;
	tests that need to exercise both branches toggle it via this helper rather
	than reaching in directly so the cleanup is guaranteed even on assertion
	failure.
	"""
	previous = gli.LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI
	gli.LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI = value
	try:
		yield
	finally:
		gli.LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI = previous


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "generateLibraryInis"
VENDOR_FIXTURE = FIXTURES / "vendor_reference.ini"
BRAILLE_FIXTURE = FIXTURES / "braille_excerpt.py"
NL_PO_FIXTURE = FIXTURES / "locale_excerpts" / "nl.po"
DE_PO_FIXTURE = FIXTURES / "locale_excerpts" / "de.po"
REAL_VENDOR_INI = REPO_ROOT / "addon" / "tactileDisplayAPI" / "enu" / "TactileDisplayAPI.ini"


class TestIniParser(unittest.TestCase):
	"""Parser round-trip on the fixture and on the live vendor reference (FR-014 case a)."""

	def test_parser_round_trip(self):
		records = gli.parse_ini(VENDOR_FIXTURE)
		rebuilt = gli.emit_ini(records)
		expected = VENDOR_FIXTURE.read_bytes().decode("utf-8")
		self.assertEqual(rebuilt, expected)

	def test_parser_round_trip_real_vendor_ini(self):
		self.assertTrue(REAL_VENDOR_INI.exists(), "real vendor ini must exist for this test")
		records = gli.parse_ini(REAL_VENDOR_INI)
		rebuilt = gli.emit_ini(records)
		# v1.19+ vendor inis are UTF-16 LE with BOM; older ones are UTF-8.
		# Use the encoding-aware helper so the round-trip check works for both.
		expected, _encoding = gli._decode_ini_bytes(REAL_VENDOR_INI.read_bytes())
		self.assertEqual(rebuilt, expected)

	def test_encoding_round_trip_utf16_le_bom(self):
		"""UTF-16 LE + BOM payload round-trips byte-for-byte through encode/decode."""
		original_bytes = b"\xff\xfe[\x00C\x00]\x00\r\x00\n\x00k\x00=\x00v\x00\r\x00\n\x00"
		text, encoding = gli._decode_ini_bytes(original_bytes)
		self.assertEqual(encoding, "utf-16-le-bom")
		self.assertEqual(text, "[C]\r\nk=v\r\n")
		self.assertEqual(gli.encode_ini_text(text, encoding), original_bytes)

	def test_encoding_round_trip_utf8(self):
		"""UTF-8 (no BOM) payload round-trips byte-for-byte."""
		original_bytes = b"[C]\r\nk=v\r\n"
		text, encoding = gli._decode_ini_bytes(original_bytes)
		self.assertEqual(encoding, "utf-8")
		self.assertEqual(text, "[C]\r\nk=v\r\n")
		self.assertEqual(gli.encode_ini_text(text, encoding), original_bytes)


class TestAstExtractor(unittest.TestCase):
	"""AST-based extraction of NVDA's braille label tables."""

	def test_extract_nvda_labels_from_ast(self):
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		self.assertEqual(set(labels.keys()), {"roleLabels", "positiveStateLabels", "negativeStateLabels"})
		roles = labels["roleLabels"]
		self.assertEqual(
			roles["BUTTON"],
			gli.NvdaLabel(member_name="BUTTON", english="btn", translatable=True),
		)
		self.assertEqual(
			roles["SEPARATOR"],
			gli.NvdaLabel(member_name="SEPARATOR", english="⠤⠤⠤⠤⠤", translatable=False),
		)
		pos = labels["positiveStateLabels"]
		self.assertEqual(
			pos["CHECKED"],
			gli.NvdaLabel(member_name="CHECKED", english="⣏⣿⣹", translatable=False),
		)
		self.assertEqual(
			pos["READONLY"],
			gli.NvdaLabel(member_name="READONLY", english="ro", translatable=True),
		)
		neg = labels["negativeStateLabels"]
		self.assertEqual(
			neg["CHECKED"],
			gli.NvdaLabel(member_name="CHECKED", english="⣏⣀⣹", translatable=False),
		)

	def test_extract_nvda_labels_raises_when_dict_missing(self):
		with tempfile.TemporaryDirectory() as td:
			bad = Path(td) / "braille.py"
			bad.write_text("# nothing here\n", encoding="utf-8")
			with self.assertRaises(RuntimeError) as cm:
				gli.extract_nvda_labels(bad)
		self.assertIn("roleLabels", str(cm.exception))


class TestPoParser(unittest.TestCase):
	"""``.po`` extractor (FR-014 case c)."""

	def test_po_parser_extracts_msgstr(self):
		catalogue = gli.parse_po(NL_PO_FIXTURE, "nl")
		self.assertEqual(catalogue.translate("btn"), "kn")
		self.assertEqual(catalogue.translate("chk"), "slv")
		self.assertEqual(catalogue.translate("rbtn"), "kr")
		# Untranslated (empty msgstr) — None.
		self.assertIsNone(catalogue.translate("untranslated"))
		# Fuzzy — None.
		self.assertIsNone(catalogue.translate("fuzzy_entry"))
		# Missing — None.
		self.assertIsNone(catalogue.translate("nonexistent"))


class TestGenerator(unittest.TestCase):
	"""End-to-end generation: NVDA-aligned values, vendor preservation, Unicode fallback."""

	def test_generate_english_role_section(self):
		"""FR-014 case b: NVDA-aligned English [ControlTypes] section."""
		records = gli.parse_ini(VENDOR_FIXTURE)
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		new_records, changed, _preserved, _suppressed = gli.generate_locale(records, labels, po=None)
		control_by_key = {
			r.key: r.value for r in new_records if r.kind == "key_value" and r.section == "ControlTypes"
		}
		self.assertEqual(control_by_key["button"], "btn")  # was vendor "bt"
		self.assertEqual(control_by_key["checkbox"], "chk")  # matched
		self.assertEqual(control_by_key["radiobutton"], "rbtn")  # was vendor "rbt"
		# slider has no NVDA Role mapping → preserved
		self.assertEqual(control_by_key["slider"], "sld")
		# separator (NVDA: "⠤⠤⠤⠤⠤") flows through with the v1.19+ gate on.
		# See test_unicode_braille_flows_through_with_gate_true.
		self.assertEqual(control_by_key["separator"], "⠤⠤⠤⠤⠤")
		# changed_keys should include the keys whose value actually changed.
		self.assertIn("[ControlTypes]button", changed)
		self.assertIn("[ControlTypes]radiobutton", changed)

	def test_unmapped_library_key_preserves_vendor_default(self):
		"""FR-014 case f: library key with no NVDA-Role mapping keeps vendor value."""
		records = gli.parse_ini(VENDOR_FIXTURE)
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		new_records, _changed, preserved, _suppressed = gli.generate_locale(records, labels, po=None)
		slider_record = next(r for r in new_records if r.kind == "key_value" and r.key == "slider")
		self.assertEqual(slider_record.value, "sld")
		self.assertIn("[ControlTypes]slider", preserved)

	def test_unavailable_state_preserves_vendor_default(self):
		"""``unavailable`` state has no NVDA-State mapping; vendor default preserved."""
		records = gli.parse_ini(VENDOR_FIXTURE)
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		new_records, _changed, preserved, _suppressed = gli.generate_locale(records, labels, po=None)
		unavail = next(r for r in new_records if r.kind == "key_value" and r.key == "unavailable")
		self.assertEqual(unavail.value, "xx")
		self.assertIn("[StateFlags]unavailable", preserved)

	def test_unicode_braille_flows_through_with_gate_true(self):
		"""With ``LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI`` True (v1.19+ default),
		NVDA's Unicode-braille labels reach the ini verbatim.

		The previous behaviour (vendor-default fallback) was a workaround for
		v1.16/v1.17/v1.18 which couldn't decode U+2800-U+28FF from the 8-bit
		ini wire format. v1.19 flipped to UTF-16 LE + BOM so the codepoints
		survive the load path; the gate flips to True alongside the bundled
		library bump. See ``test_unicode_braille_falls_back_when_gate_false``
		for the legacy behaviour.
		"""
		records = gli.parse_ini(VENDOR_FIXTURE)
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		dutch = gli.parse_po(NL_PO_FIXTURE, "nl")
		new_records, _changed, _preserved, suppressed = gli.generate_locale(records, labels, dutch)
		separator = next(r for r in new_records if r.kind == "key_value" and r.key == "separator")
		self.assertEqual(separator.value, "⠤⠤⠤⠤⠤")
		checked = next(r for r in new_records if r.kind == "key_value" and r.key == "checked")
		self.assertEqual(checked.value, "⣏⣿⣹")
		# Nothing should be suppressed when the gate is True.
		self.assertEqual(suppressed, ())

	def test_unicode_braille_falls_back_when_gate_false(self):
		"""Toggling ``LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI`` back to False
		restores the vendor-default fallback path used for v1.16/v1.17/v1.18.

		Kept as a regression guard: if a future library version regresses
		Unicode-braille rendering, the maintainer flips the gate back and
		this contract must still hold.
		"""
		records = gli.parse_ini(VENDOR_FIXTURE)
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		dutch = gli.parse_po(NL_PO_FIXTURE, "nl")
		with _temporarily_flip_unicode_gate(False):
			new_records, _changed, _preserved, suppressed = gli.generate_locale(records, labels, dutch)
		separator = next(r for r in new_records if r.kind == "key_value" and r.key == "separator")
		self.assertEqual(separator.value, "---")
		checked = next(r for r in new_records if r.kind == "key_value" and r.key == "checked")
		self.assertEqual(checked.value, "<x>")
		self.assertIn("[ControlTypes]separator", suppressed)
		self.assertIn("[StateFlags]checked", suppressed)

	def test_generate_locale_uses_po_translation(self):
		"""Dutch .po translation drives the output for translatable labels."""
		records = gli.parse_ini(VENDOR_FIXTURE)
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		dutch = gli.parse_po(NL_PO_FIXTURE, "nl")
		new_records, _changed, _preserved, _suppressed = gli.generate_locale(records, labels, dutch)
		button = next(r for r in new_records if r.kind == "key_value" and r.key == "button")
		self.assertEqual(button.value, "kn")  # Dutch translation
		checkbox = next(r for r in new_records if r.kind == "key_value" and r.key == "checkbox")
		self.assertEqual(checkbox.value, "slv")

	def test_generate_locale_falls_back_to_english_for_missing_msgid(self):
		"""Missing msgid in target .po → English fallback + WARNING log."""
		records = gli.parse_ini(VENDOR_FIXTURE)
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		german = gli.parse_po(DE_PO_FIXTURE, "de")
		# 'sel' translates in nl but not in de. The selected state is in our vendor fixture.
		with self.assertLogs("generateLibraryInis", level=logging.WARNING) as cm:
			new_records, _changed, _preserved, _suppressed = gli.generate_locale(records, labels, german)
		selected = next(r for r in new_records if r.kind == "key_value" and r.key == "selected")
		# Falls back to NVDA's English value ("sel") since de.po has no translation.
		self.assertEqual(selected.value, "sel")
		self.assertTrue(
			any("No translation for msgid 'sel'" in rec.message for rec in cm.records),
			f"WARNING log not found in {[rec.message for rec in cm.records]}",
		)

	def test_unicode_braille_suppression_consistent_across_locales_with_gate_false(self):
		"""When the gate is False, Unicode-braille suppression applies in every locale."""
		records = gli.parse_ini(VENDOR_FIXTURE)
		labels = gli.extract_nvda_labels(BRAILLE_FIXTURE)
		dutch = gli.parse_po(NL_PO_FIXTURE, "nl")
		with _temporarily_flip_unicode_gate(False):
			new_records, _changed, _preserved, suppressed = gli.generate_locale(records, labels, dutch)
		separator = next(r for r in new_records if r.kind == "key_value" and r.key == "separator")
		self.assertEqual(separator.value, "---")  # vendor default — Dutch / any locale
		self.assertIn("[ControlTypes]separator", suppressed)


class TestUnmappedLocaleLogging(unittest.TestCase):
	"""INFO-log for NVDA locales not in our LCID mapping table (FR-014 case e)."""

	def test_unmapped_nvda_locale_skipped_with_info_log(self):
		with tempfile.TemporaryDirectory() as td:
			nvda_source = Path(td) / "nvda" / "source"
			(nvda_source / "locale" / "ar_LB" / "LC_MESSAGES").mkdir(parents=True)
			(nvda_source / "locale" / "ar_LB" / "LC_MESSAGES" / "nvda.po").write_text(
				'msgid ""\nmsgstr ""\n',
				encoding="utf-8",
			)
			with self.assertLogs("generateLibraryInis", level=logging.INFO) as cm:
				gli._log_unmapped_locales(nvda_source)
		self.assertTrue(
			any("Skipping ar_LB" in rec.message for rec in cm.records),
			f"INFO log not found in {[rec.message for rec in cm.records]}",
		)


class TestMain(unittest.TestCase):
	"""CLI / main() behaviour: idempotency, --dry-run, input-validation exit codes."""

	def _stageFixtureLayout(self, td: str):
		"""Build a minimal NVDA source + vendor ini under ``td``. Returns paths."""
		root = Path(td)
		nvda_source = root / "nvda" / "source"
		nvda_source.mkdir(parents=True)
		(nvda_source / "braille.py").write_text(
			BRAILLE_FIXTURE.read_text(encoding="utf-8"),
			encoding="utf-8",
		)
		(nvda_source / "locale" / "nl" / "LC_MESSAGES").mkdir(parents=True)
		(nvda_source / "locale" / "nl" / "LC_MESSAGES" / "nvda.po").write_text(
			NL_PO_FIXTURE.read_text(encoding="utf-8"),
			encoding="utf-8",
		)
		vendor = root / "vendor.ini"
		vendor.write_bytes(VENDOR_FIXTURE.read_bytes())
		output_root = root / "out"
		return nvda_source, vendor, output_root

	def test_utf8_vendor_reference_still_emits_utf16_with_gate_on(self):
		"""A UTF-8 vendor reference must not drag the per-locale inis back to UTF-8.

		The v1.0.34 drop shipped its ``enu`` reference as plain UTF-8 after six
		releases of UTF-16 LE. Because that reference is pure ASCII it says
		nothing about the library's reader, and mirroring it would silently
		revert every locale to the format that truncates U+2800-U+28FF.
		"""
		self.assertEqual(gli.detect_ini_encoding(VENDOR_FIXTURE), "utf-8")
		with tempfile.TemporaryDirectory() as td:
			nvda_source, vendor, output_root = self._stageFixtureLayout(td)
			with _temporarily_flip_unicode_gate(True):
				results = gli.generate_all(
					nvda_source=nvda_source,
					vendor_reference=vendor,
					output_root=output_root,
					requested_locales=["en", "nl"],
				)
				gli.write_results(results)
			for result in results:
				self.assertEqual(result.encoding, "utf-16-le-bom", result.library_lcid)
				self.assertEqual(
					result.output_path.read_bytes()[:2],
					b"\xff\xfe",
					f"{result.library_lcid} ini is missing the UTF-16 LE BOM",
				)

	def test_utf8_vendor_reference_mirrored_when_gate_off(self):
		"""With the gate off there is no Unicode to protect, so the mirror stands."""
		with tempfile.TemporaryDirectory() as td:
			nvda_source, vendor, output_root = self._stageFixtureLayout(td)
			with _temporarily_flip_unicode_gate(False):
				results = gli.generate_all(
					nvda_source=nvda_source,
					vendor_reference=vendor,
					output_root=output_root,
					requested_locales=["en"],
				)
				gli.write_results(results)
			for result in results:
				self.assertEqual(result.encoding, "utf-8", result.library_lcid)
				self.assertNotEqual(result.output_path.read_bytes()[:2], b"\xff\xfe")

	def test_wrong_on_disk_encoding_counts_as_changed(self):
		"""Same text, wrong wire format — `--dry-run` must still report drift."""
		with tempfile.TemporaryDirectory() as td:
			nvda_source, vendor, output_root = self._stageFixtureLayout(td)
			with _temporarily_flip_unicode_gate(True):
				results = gli.generate_all(
					nvda_source=nvda_source,
					vendor_reference=vendor,
					output_root=output_root,
					requested_locales=["en"],
				)
				gli.write_results(results)
				# Rewrite the identical text as UTF-8: text compares equal,
				# bytes do not.
				target = results[0].output_path
				target.write_bytes(gli.encode_ini_text(results[0].new_content, "utf-8"))
				rerun = gli.generate_all(
					nvda_source=nvda_source,
					vendor_reference=vendor,
					output_root=output_root,
					requested_locales=["en"],
				)
			self.assertEqual(rerun[0].existing_content, results[0].new_content)
			self.assertFalse(rerun[0].is_unchanged)

	def test_idempotent_double_run(self):
		"""FR-014 case d: running the generator twice produces identical files."""
		with tempfile.TemporaryDirectory() as td:
			nvda_source, vendor, output_root = self._stageFixtureLayout(td)
			# First run.
			results1 = gli.generate_all(
				nvda_source=nvda_source,
				vendor_reference=vendor,
				output_root=output_root,
				requested_locales=["en", "nl"],
			)
			gli.write_results(results1)
			files_before = {p: p.read_bytes() for p in output_root.rglob("*.ini")}
			# Second run.
			results2 = gli.generate_all(
				nvda_source=nvda_source,
				vendor_reference=vendor,
				output_root=output_root,
				requested_locales=["en", "nl"],
			)
			gli.write_results(results2)
			files_after = {p: p.read_bytes() for p in output_root.rglob("*.ini")}
			self.assertEqual(files_before, files_after, "Second run must produce identical files")
			for r in results2:
				self.assertTrue(
					r.is_unchanged,
					f"Result for {r.library_lcid} unexpectedly changed on second run",
				)

	def test_dry_run_writes_no_files(self):
		with tempfile.TemporaryDirectory() as td:
			nvda_source, vendor, output_root = self._stageFixtureLayout(td)
			exit_code = gli.main(
				[
					"--nvda-source",
					str(nvda_source),
					"--vendor-reference",
					str(vendor),
					"--output-root",
					str(output_root),
					"--locale",
					"en",
					"--dry-run",
				],
			)
			self.assertEqual(exit_code, 1)  # Drift detected (no existing files).
			if output_root.exists():
				self.assertFalse(list(output_root.rglob("*.ini")))

	def test_dry_run_clean_exits_zero(self):
		"""After a normal run, a subsequent --dry-run sees no drift."""
		with tempfile.TemporaryDirectory() as td:
			nvda_source, vendor, output_root = self._stageFixtureLayout(td)
			first = gli.main(
				[
					"--nvda-source",
					str(nvda_source),
					"--vendor-reference",
					str(vendor),
					"--output-root",
					str(output_root),
					"--locale",
					"en",
				],
			)
			self.assertEqual(first, 0)
			second = gli.main(
				[
					"--nvda-source",
					str(nvda_source),
					"--vendor-reference",
					str(vendor),
					"--output-root",
					str(output_root),
					"--locale",
					"en",
					"--dry-run",
				],
			)
			self.assertEqual(second, 0)

	def test_missing_nvda_source_exits_2(self):
		with tempfile.TemporaryDirectory() as td:
			vendor = Path(td) / "vendor.ini"
			vendor.write_bytes(VENDOR_FIXTURE.read_bytes())
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				exit_code = gli.main(
					[
						"--nvda-source",
						str(Path(td) / "does_not_exist"),
						"--vendor-reference",
						str(vendor),
						"--output-root",
						str(Path(td) / "out"),
					],
				)
			self.assertEqual(exit_code, 2)
			err_text = err.getvalue().lower()
			self.assertTrue("braille.py" in err_text or "nvda" in err_text)

	def test_missing_vendor_reference_exits_2(self):
		with tempfile.TemporaryDirectory() as td:
			nvda_source = Path(td) / "nvda" / "source"
			nvda_source.mkdir(parents=True)
			(nvda_source / "braille.py").write_text(
				BRAILLE_FIXTURE.read_text(encoding="utf-8"),
				encoding="utf-8",
			)
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				exit_code = gli.main(
					[
						"--nvda-source",
						str(nvda_source),
						"--vendor-reference",
						str(Path(td) / "does_not_exist.ini"),
						"--output-root",
						str(Path(td) / "out"),
					],
				)
			self.assertEqual(exit_code, 2)
			self.assertIn("vendor", err.getvalue().lower())

	def test_braille_py_missing_dict_exits_2(self):
		with tempfile.TemporaryDirectory() as td:
			nvda_source = Path(td) / "nvda" / "source"
			nvda_source.mkdir(parents=True)
			# braille.py exists but lacks roleLabels / positiveStateLabels / negativeStateLabels.
			(nvda_source / "braille.py").write_text("# empty\n", encoding="utf-8")
			vendor = Path(td) / "vendor.ini"
			vendor.write_bytes(VENDOR_FIXTURE.read_bytes())
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				exit_code = gli.main(
					[
						"--nvda-source",
						str(nvda_source),
						"--vendor-reference",
						str(vendor),
						"--output-root",
						str(Path(td) / "out"),
					],
				)
			self.assertEqual(exit_code, 2)
			err_text = err.getvalue()
			self.assertTrue("roleLabels" in err_text or "missing" in err_text.lower())


class TestReplaceValue(unittest.TestCase):
	"""``replace_value`` preserves line endings, spacing, and trailing comments."""

	def test_replace_value_preserves_line_ending(self):
		record = gli.IniRecord("key_value", "ControlTypes", "button", "bt", "button=bt\r\n")
		new = gli.replace_value(record, "btn")
		self.assertEqual(new.raw_line, "button=btn\r\n")

	def test_replace_value_preserves_spacing_and_comment(self):
		record = gli.IniRecord(
			"key_value",
			"ControlTypes",
			"button",
			"bt",
			"  button = bt ; legacy alias\n",
		)
		new = gli.replace_value(record, "btn")
		self.assertEqual(new.raw_line, "  button = btn ; legacy alias\n")


class TestUnescapePo(unittest.TestCase):
	"""Feature 023 — ``_unescape_po`` resolves ``.po`` backslash-escape sequences
	without corrupting non-ASCII Unicode codepoints.

	The previous implementation round-tripped through ``unicode_escape`` which
	interprets each byte of the UTF-8 encoding as a Latin-1 codepoint —
	fragmenting any character above U+007F. The new implementation walks the
	input string directly and substitutes from a small escape table, so any
	Unicode codepoint passes through 1:1.
	"""

	def test_ascii_passthrough(self):
		self.assertEqual(gli._unescape_po("hello"), "hello")
		self.assertEqual(gli._unescape_po(""), "")

	def test_all_five_escapes(self):
		self.assertEqual(gli._unescape_po("a\\nb"), "a\nb")
		self.assertEqual(gli._unescape_po("a\\tb"), "a\tb")
		self.assertEqual(gli._unescape_po("a\\rb"), "a\rb")
		self.assertEqual(gli._unescape_po('a\\"b'), 'a"b')
		self.assertEqual(gli._unescape_po("a\\\\b"), "a\\b")

	def test_latin1_supplement_preserved(self):
		"""German label with ``ä`` (U+00E4) — must round-trip as one codepoint."""
		result = gli._unescape_po("Schaltfläche")
		self.assertEqual(result, "Schaltfläche")
		self.assertEqual(len(result), 12)
		self.assertIn("ä", result)
		# Negative assertion against the old mojibake signature:
		self.assertNotIn("Ã", result)

	def test_cjk_preserved(self):
		"""Japanese label — three CJK codepoints must stay three codepoints."""
		result = gli._unescape_po("ボタン")
		self.assertEqual(result, "ボタン")
		self.assertEqual(len(result), 3)

	def test_rtl_preserved(self):
		"""Hebrew + Arabic single-codepoint preservation."""
		self.assertEqual(gli._unescape_po("א"), "א")
		self.assertEqual(len(gli._unescape_po("א")), 1)
		self.assertEqual(gli._unescape_po("ا"), "ا")
		self.assertEqual(len(gli._unescape_po("ا")), 1)

	def test_mixed_unicode_and_escapes(self):
		"""Latin-1 + escape + ASCII all in one string."""
		result = gli._unescape_po("Über\\nseite")
		self.assertEqual(result, "Über\nseite")
		# Ü, b, e, r, \n, s, e, i, t, e = 10 codepoints (input ``\\n`` collapsed to one).
		self.assertEqual(len(result), 10)
		self.assertIn("\n", result)
		self.assertIn("Ü", result)

	def test_unrecognised_escape_lenient(self):
		"""``\\q`` is not a known escape: drop the backslash, keep ``q``."""
		self.assertEqual(gli._unescape_po("\\q"), "q")
		self.assertEqual(gli._unescape_po("foo\\xbar"), "fooxbar")

	def test_trailing_lone_backslash_passes_through(self):
		"""Input ending in a lone ``\\`` with no follower — backslash is preserved
		literally per the contract (no follower to consume, the else branch of
		the loop appends the backslash itself)."""
		result = gli._unescape_po("abc\\")
		self.assertEqual(result, "abc\\")
		self.assertEqual(len(result), 4)


if __name__ == "__main__":
	unittest.main()
