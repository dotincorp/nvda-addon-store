# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for ``addon.tactileDisplayAPI.iniPatcher`` (feature 025).

Style: stdlib ``unittest.TestCase`` only — pytest is not installed in CI
(see CLAUDE.md). Per-test temp dirs use ``tempfile.TemporaryDirectory``;
NVDA-resolver and module-constant patches use ``unittest.mock.patch``.
"""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from addon.tactileDisplayAPI import iniPatcher
from addon.tactileDisplayAPI.iniPatcher import PatchResult

# Fixture INI bodies. Both decode to the same logical text — a minimal vendor-
# style INI containing the two target Liblouis keys (empty values), the
# untouched [Mathcat] keys, plus one section of unrelated content
# (`LiteraryTable=...`, `; comment`, blank line) the patcher must preserve verbatim.
_FIXTURE_INI_TEXT: str = (
	"[ControlTypes]\r\n"
	"button=btn\r\n"
	"\r\n"
	"[Liblouis]\r\n"
	"LiteraryTable=en-us-g2.ctb\r\n"
	"; user-selected literary table — vestigial after feature 024 but preserved\r\n"
	"LiblouisPath=\r\n"
	"TablesPath=\r\n"
	"\r\n"
	"[Mathcat]\r\n"
	"MathcatPath=\r\n"
	"RulesPath=\r\n"
	"\r\n"
	"[HID Braille Display Keymap Sections]\r\n"
	"APH Mantis Q40 HID=Vid_1c71&Pid_c111\r\n"
)
_FIXTURE_UTF8_NO_BOM: bytes = _FIXTURE_INI_TEXT.encode("utf-8")
_FIXTURE_UTF16LE_BOM: bytes = b"\xff\xfe" + _FIXTURE_INI_TEXT.encode("utf-16-le")


def _writeFixture(path: Path, body: bytes) -> None:
	"""Write a binary fixture, creating parent directories as needed."""
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(body)


def _stagedAddonTree(tmpRoot: Path, locales: list[str], body: bytes) -> Path:
	"""Create ``<tmpRoot>/tactileDisplayAPI/<locale>/TactileDisplayAPI.ini`` for each locale.

	Returns the ``tactileDisplayAPI/`` directory that ``get_library_path``
	should be patched to return.
	"""
	tactileDir = tmpRoot / "tactileDisplayAPI"
	for locale in locales:
		_writeFixture(tactileDir / locale / "TactileDisplayAPI.ini", body)
	return tactileDir


# ---------------------------------------------------------------------------
# T009: Foundational tests (contract tests 3 / 4 / 5 / 12)
# ---------------------------------------------------------------------------


class TestEncodingRoundTripUtf8(unittest.TestCase):
	"""Contract test 3: UTF-8 no-BOM detect → decode → encode → byte-equal."""

	def test_detectAndRoundTrip(self) -> None:
		encoding = iniPatcher._detectEncoding(_FIXTURE_UTF8_NO_BOM)
		self.assertIs(encoding, iniPatcher._Encoding.UTF_8)
		decoded = iniPatcher._decode(_FIXTURE_UTF8_NO_BOM, encoding)
		self.assertEqual(decoded, _FIXTURE_INI_TEXT)
		reEncoded = iniPatcher._encode(decoded, encoding)
		self.assertEqual(reEncoded, _FIXTURE_UTF8_NO_BOM)

	def test_utf8WithBomStrippedTolerantly(self) -> None:
		raw = b"\xef\xbb\xbf" + _FIXTURE_UTF8_NO_BOM
		encoding = iniPatcher._detectEncoding(raw)
		# UTF-8 BOM is NOT classified as UTF-16LE; treated as UTF-8 with the BOM
		# tolerantly stripped on decode (matches the generator's behaviour).
		self.assertIs(encoding, iniPatcher._Encoding.UTF_8)
		decoded = iniPatcher._decode(raw, encoding)
		self.assertEqual(decoded, _FIXTURE_INI_TEXT)


class TestEncodingRoundTripUtf16LeBom(unittest.TestCase):
	"""Contract test 4: UTF-16LE+BOM detect → decode → encode → byte-equal, CRLF preserved."""

	def test_detectAndRoundTrip(self) -> None:
		encoding = iniPatcher._detectEncoding(_FIXTURE_UTF16LE_BOM)
		self.assertIs(encoding, iniPatcher._Encoding.UTF_16_LE_BOM)
		decoded = iniPatcher._decode(_FIXTURE_UTF16LE_BOM, encoding)
		self.assertEqual(decoded, _FIXTURE_INI_TEXT)
		reEncoded = iniPatcher._encode(decoded, encoding)
		self.assertEqual(reEncoded, _FIXTURE_UTF16LE_BOM)

	def test_crlfEncodesAsFourBytes(self) -> None:
		# CRLF in UTF-16LE is 0x0D 0x00 0x0A 0x00. Sanity check that our
		# round-trip preserves this exact byte pattern.
		decoded = iniPatcher._decode(_FIXTURE_UTF16LE_BOM, iniPatcher._Encoding.UTF_16_LE_BOM)
		reEncoded = iniPatcher._encode(decoded, iniPatcher._Encoding.UTF_16_LE_BOM)
		self.assertIn(b"\x0d\x00\x0a\x00", reEncoded)


class TestAtomicWriteCrashRecovery(unittest.TestCase):
	"""Contract test 5: ``os.replace`` failure leaves original untouched and removes temp."""

	def test_replaceFailureLeavesOriginalUntouched(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "x.ini"
			originalBytes = b"original-content"
			target.write_bytes(originalBytes)
			with patch.object(iniPatcher.os, "replace", side_effect=OSError("simulated")):
				with self.assertRaises(OSError):
					iniPatcher._atomicWrite(target, b"new-content")
			# Original bytes intact.
			self.assertEqual(target.read_bytes(), originalBytes)
			# No temp file remains in the parent directory.
			tmpFiles = [p for p in Path(tmp).iterdir() if p.name.startswith(".tdai-")]
			self.assertEqual(tmpFiles, [])


class TestNonMutatedContentPreserved(unittest.TestCase):
	"""Contract test 12: surgical edit preserves all non-target bytes verbatim."""

	def test_preservesUnrelatedSectionsCommentsBlankLinesAndVestigialTableKey(self) -> None:
		replacements = {
			("Liblouis", "LiblouisPath"): r"C:\NVDA\liblouis.dll",
			("Liblouis", "TablesPath"): r"C:\NVDA\louis\tables",
		}
		patched = iniPatcher._replaceKeyValues(_FIXTURE_INI_TEXT, replacements)
		# Every non-target line MUST appear byte-identical in the patched output.
		preservedLines = [
			"[ControlTypes]\r\n",
			"button=btn\r\n",
			"[Liblouis]\r\n",
			"LiteraryTable=en-us-g2.ctb\r\n",
			"; user-selected literary table — vestigial after feature 024 but preserved\r\n",
			"[Mathcat]\r\n",
			"[HID Braille Display Keymap Sections]\r\n",
			"APH Mantis Q40 HID=Vid_1c71&Pid_c111\r\n",
		]
		for line in preservedLines:
			self.assertIn(line, patched, f"Lost or mutated: {line!r}")
		# Target keys updated.
		self.assertIn("LiblouisPath=C:\\NVDA\\liblouis.dll\r\n", patched)
		self.assertIn("TablesPath=C:\\NVDA\\louis\\tables\r\n", patched)
		# The [Mathcat] keys are not targets — they survive verbatim as `Key=\r\n`.
		self.assertIn("MathcatPath=\r\n", patched)
		self.assertIn("RulesPath=\r\n", patched)

	def test_unrelatedKeyOutsideTargetSectionsNotTouched(self) -> None:
		# ``MathcatPath`` only inside ``[Mathcat]`` — a key with the same name
		# in another section MUST NOT be rewritten.
		text = "[Mathcat]\r\nMathcatPath=\r\n[OtherSection]\r\nMathcatPath=should-survive\r\n"
		patched = iniPatcher._replaceKeyValues(text, {("Mathcat", "MathcatPath"): "NEW"})
		self.assertIn("[Mathcat]\r\nMathcatPath=NEW\r\n", patched)
		self.assertIn("[OtherSection]\r\nMathcatPath=should-survive\r\n", patched)


# ---------------------------------------------------------------------------
# T010: Dev-mode signal tests (contract tests 15 / 16 / 17 / 18 / 19)
# ---------------------------------------------------------------------------


class TestDevModeSkipGitDirectoryAtParent(unittest.TestCase):
	"""Contract test 15: ``.git`` directory immediately above addon path → SKIPPED."""

	def test_gitDirectoryFoundAtParent(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			# Resolved: _isDevMode resolves too, and CI's %TEMP% sits under an
			# 8.3 short name (RUNNER~1) that resolving expands. Comparing a raw
			# temp path against a resolved one fails there and nowhere else.
			root = Path(tmp).resolve()
			(root / ".git").mkdir()
			addonPath = root / "addon"
			addonPath.mkdir()
			result = iniPatcher._isDevMode(addonPath)
			self.assertEqual(result, root)


class TestDevModeSkipGitFileAtParent(unittest.TestCase):
	"""Contract test 16: ``.git`` *file* (submodule worktree style) at parent → SKIPPED."""

	def test_gitFileFoundAtParent(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			# Resolved: _isDevMode resolves too, and CI's %TEMP% sits under an
			# 8.3 short name (RUNNER~1) that resolving expands. Comparing a raw
			# temp path against a resolved one fails there and nowhere else.
			root = Path(tmp).resolve()
			(root / ".git").write_text("gitdir: ../.git/modules/sub\n", encoding="utf-8")
			addonPath = root / "addon"
			addonPath.mkdir()
			result = iniPatcher._isDevMode(addonPath)
			self.assertEqual(result, root)


class TestDevModeSkipGitAtGrandparent(unittest.TestCase):
	"""Contract test 17: ``.git`` two levels above the addon path is still discovered."""

	def test_gitFoundAtGrandparent(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			# Resolved: _isDevMode resolves too, and CI's %TEMP% sits under an
			# 8.3 short name (RUNNER~1) that resolving expands. Comparing a raw
			# temp path against a resolved one fails there and nowhere else.
			root = Path(tmp).resolve()
			(root / ".git").mkdir()
			deep = root / "sub" / "addon"
			deep.mkdir(parents=True)
			result = iniPatcher._isDevMode(deep)
			self.assertEqual(result, root)


def _linkDir(test: unittest.TestCase, link: Path, target: Path) -> None:
	"""Point ``link`` at ``target``, however this machine will allow.

	``os.symlink`` needs privilege or Developer Mode on Windows, which CI does not
	have, and a skipped test would prove nothing about the case it exists for. A
	directory junction needs neither and ``Path.resolve()`` follows it just the same.
	"""
	try:
		link.symlink_to(target, target_is_directory=True)
		return
	except OSError:
		pass
	if os.name != "nt":  # pragma: no cover - the addon is Windows-only
		test.skipTest("symlinks unavailable and junctions are Windows-only")
	result = subprocess.run(
		["cmd", "/c", "mklink", "/J", str(link), str(target)],
		capture_output=True,
		text=True,
		check=False,
	)
	if result.returncode != 0:  # pragma: no cover - neither link type available
		test.skipTest(f"could not link {link} -> {target}: {result.stderr.strip()}")


class TestDevModeSkipThroughASymlinkedAddonPath(unittest.TestCase):
	"""A dev install is a symlink from NVDA's addons directory to the working copy.

	``__file__`` keeps the path a module was loaded through, so the path handed to
	``_isDevMode`` is the symlink, whose parents are NVDA's configuration directory --
	no ``.git`` anywhere above it. Without resolving, the guard misses and the patcher
	rewrites tracked files on every NVDA start.
	"""

	def test_gitFoundThroughASymlink(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			repo = root / "repo"
			(repo / "addon").mkdir(parents=True)
			(repo / ".git").mkdir()
			# Stands in for %APPDATA%/nvda/addons/, which has no .git above it.
			installed = root / "nvdaConfig" / "addons"
			installed.mkdir(parents=True)
			link = installed / "dotpad"
			_linkDir(self, link, repo / "addon")

			result = iniPatcher._isDevMode(link / "tactileDisplayAPI")

			self.assertEqual(result, repo.resolve())

	def test_aRealInstallIsStillNotDevMode(self) -> None:
		"""Resolving must not turn an ordinary install into a false positive."""
		with tempfile.TemporaryDirectory() as tmp:
			addonPath = Path(tmp) / "nvdaConfig" / "addons" / "dotpad"
			addonPath.mkdir(parents=True)

			self.assertIsNone(iniPatcher._isDevMode(addonPath))


class TestDevModeOverrideConstantBypassesSkip(unittest.TestCase):
	"""Contract test 18: ``_OVERRIDE_DEV_MODE_SKIP = True`` suppresses the signal."""

	def test_overrideSuppressesSignal(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / ".git").mkdir()
			addonPath = root / "addon"
			addonPath.mkdir()
			with patch.object(iniPatcher, "_OVERRIDE_DEV_MODE_SKIP", True):
				result = iniPatcher._isDevMode(addonPath)
			self.assertIsNone(result)


class TestNoGitNormalPatching(unittest.TestCase):
	"""Contract test 19: no ``.git`` anywhere up the tree → ``None`` (normal patching)."""

	def test_noGitAnywhere(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			deep = Path(tmp) / "a" / "b" / "c"
			deep.mkdir(parents=True)
			# Ensure no .git exists anywhere from `deep` up to its filesystem root.
			# tempfile creates the path under the system temp dir; on test
			# machines that dir does not contain `.git`. If a future CI host
			# violates this, the test will need a chroot-style isolation.
			# Walk up and assert no .git is present in any parent for sanity.
			for parent in (deep, *deep.parents):
				if (parent / ".git").exists():
					self.skipTest(f"unexpected .git ancestor at {parent}; cannot validate negative case")
			result = iniPatcher._isDevMode(deep)
			self.assertIsNone(result)


# ---------------------------------------------------------------------------
# T014: US1 tests (contract tests 1 / 2 / 13 / 14)
# ---------------------------------------------------------------------------


_FAKE_LIBLOUIS_DLL = r"C:\FakeNVDA\liblouis.dll"
_FAKE_TABLES_DIR = r"C:\FakeNVDA\louis\tables"


class _US1Base(unittest.TestCase):
	"""Shared scaffolding for US1 tests: stage an addon tree, mock NVDA paths."""

	def setUp(self) -> None:
		self._tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self._tmp.cleanup)
		self.root = Path(self._tmp.name)
		# Stage a deep enough tree that ``.git`` is NOT found above ``addon/``
		# (the system temp dir on test hosts has no ``.git`` ancestor).
		self.tactileDir = _stagedAddonTree(self.root / "addon", ["enu", "deu", "jpn"], _FIXTURE_UTF8_NO_BOM)
		# Patch the addon's library-path helper so the patcher targets our temp tree.
		self._libPatch = patch.object(iniPatcher, "get_library_path", return_value=self.tactileDir)
		self._libPatch.start()
		self.addCleanup(self._libPatch.stop)
		# Patch the liblouis resolver to deterministic fake paths.
		self._resolverPatch = patch.object(
			iniPatcher,
			"_resolveNvdaLiblouis",
			return_value=(Path(_FAKE_LIBLOUIS_DLL), Path(_FAKE_TABLES_DIR)),
		)
		self._resolverPatch.start()
		self.addCleanup(self._resolverPatch.stop)


class TestFirstWriteContent(_US1Base):
	"""Contract test 2: empty target keys → filled with the resolved paths."""

	def test_liblouisKeysAreSet(self) -> None:
		results = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(set(results.values()), {PatchResult.WROTE})
		for locale in ("enu", "deu", "jpn"):
			# Read as bytes then decode without newline translation so CRLF
			# (the on-disk line ending) is observable in the assertion strings.
			text = (self.tactileDir / locale / "TactileDisplayAPI.ini").read_bytes().decode("utf-8")
			self.assertIn(f"LiblouisPath={_FAKE_LIBLOUIS_DLL}\r\n", text)
			self.assertIn(f"TablesPath={_FAKE_TABLES_DIR}\r\n", text)
			# The [Mathcat] keys are not patched: NVDA ships no libmathcat_c.dll,
			# so they stay empty and the library uses its own bundled MathCAT.
			self.assertIn("MathcatPath=\r\n", text)
			self.assertIn("RulesPath=\r\n", text)


class TestIdempotency(_US1Base):
	"""Contract test 1: second invocation returns UNCHANGED with byte-identical files."""

	def test_secondCallIsUnchanged(self) -> None:
		first = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(set(first.values()), {PatchResult.WROTE})
		# Snapshot the bytes after the first patch.
		afterFirst = {
			locale: (self.tactileDir / locale / "TactileDisplayAPI.ini").read_bytes()
			for locale in ("enu", "deu", "jpn")
		}
		second = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(set(second.values()), {PatchResult.UNCHANGED})
		# Bytes byte-identical between call 1 result and call 2 final state.
		for locale, bytesAfterFirst in afterFirst.items():
			self.assertEqual(
				(self.tactileDir / locale / "TactileDisplayAPI.ini").read_bytes(),
				bytesAfterFirst,
			)


class TestPatchEveryLocale(_US1Base):
	"""Contract test 14: every discovered locale is patched; non-INI subdirs ignored."""

	def test_threeLocalesPatchedAndSpuriousDirIgnored(self) -> None:
		# Add a locale subdirectory WITHOUT the expected INI; patcher must ignore.
		(self.tactileDir / "fakeloc").mkdir()
		results = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(set(results.keys()), {"enu", "deu", "jpn"})
		self.assertEqual(set(results.values()), {PatchResult.WROTE})
		# Confirm the spurious dir was not touched.
		self.assertFalse((self.tactileDir / "fakeloc" / "TactileDisplayAPI.ini").exists())


class TestOtherSideValidation(_US1Base):
	"""Contract test 13: parsing the patched INI back via the same helpers recovers values."""

	def test_patchedValuesRoundTripThroughHelpers(self) -> None:
		iniPatcher.patchTactileDisplayAPIIni()
		path = self.tactileDir / "enu" / "TactileDisplayAPI.ini"
		raw = path.read_bytes()
		encoding = iniPatcher._detectEncoding(raw)
		decoded = iniPatcher._decode(raw, encoding)
		self.assertIn(f"LiblouisPath={_FAKE_LIBLOUIS_DLL}", decoded)
		self.assertIn(f"TablesPath={_FAKE_TABLES_DIR}", decoded)
		# Round-tripping the same replacements is a true no-op.
		replacements = {
			("Liblouis", "LiblouisPath"): _FAKE_LIBLOUIS_DLL,
			("Liblouis", "TablesPath"): _FAKE_TABLES_DIR,
		}
		self.assertEqual(iniPatcher._replaceKeyValues(decoded, replacements), decoded)


# ---------------------------------------------------------------------------
# T018: US2 tests (contract tests 6 / 7 / 20)
# ---------------------------------------------------------------------------


class TestReadOnlyFileFallback(_US1Base):
	"""Contract test 6: a single read-only INI returns FAILED; siblings still succeed."""

	def test_oneReadOnlyLocaleFailsButOthersSucceed(self) -> None:
		readOnlyPath = self.tactileDir / "deu" / "TactileDisplayAPI.ini"
		os.chmod(readOnlyPath, stat.S_IREAD)
		# Always restore writability so TemporaryDirectory cleanup can delete it.
		self.addCleanup(os.chmod, readOnlyPath, stat.S_IREAD | stat.S_IWRITE)
		results = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(results["deu"], PatchResult.FAILED)
		# Siblings still got patched.
		self.assertEqual(results["enu"], PatchResult.WROTE)
		self.assertEqual(results["jpn"], PatchResult.WROTE)
		# The read-only file's bytes are untouched (no partial write).
		self.assertEqual(readOnlyPath.read_bytes(), _FIXTURE_UTF8_NO_BOM)


class TestReadOnlyDirectoryFallback(_US1Base):
	"""Contract test 7: ``_atomicWrite`` raising still maps to FAILED per locale."""

	def test_atomicWriteRaisesForOneLocaleOnly(self) -> None:
		failingPath = self.tactileDir / "deu" / "TactileDisplayAPI.ini"
		realAtomicWrite = iniPatcher._atomicWrite

		def selectiveAtomicWrite(path: Path, data: bytes) -> None:
			if path == failingPath:
				raise PermissionError("simulated directory-level read-only")
			realAtomicWrite(path, data)

		with patch.object(iniPatcher, "_atomicWrite", side_effect=selectiveAtomicWrite):
			results = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(results["deu"], PatchResult.FAILED)
		self.assertEqual(results["enu"], PatchResult.WROTE)
		self.assertEqual(results["jpn"], PatchResult.WROTE)
		self.assertEqual(failingPath.read_bytes(), _FIXTURE_UTF8_NO_BOM)


class TestAggregatedLogOutput(_US1Base):
	"""Contract test 20: one INFO summary + per-failure DEBUG lines on mixed outcomes."""

	def test_summaryAndDebugLinesEmitted(self) -> None:
		# First pass: all three locales reach steady-state patched bytes.
		results_first_pass = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(set(results_first_pass.values()), {PatchResult.WROTE})
		# For the measured pass we want one WROTE + one UNCHANGED + one FAILED.
		# Revert "enu" and "deu" so they have non-matching bytes; leave "jpn"
		# correctly patched (UNCHANGED). Then mock the writer to fail on "deu"
		# while letting "enu" through.
		(self.tactileDir / "enu" / "TactileDisplayAPI.ini").write_bytes(_FIXTURE_UTF8_NO_BOM)
		(self.tactileDir / "deu" / "TactileDisplayAPI.ini").write_bytes(_FIXTURE_UTF8_NO_BOM)
		failingPath = self.tactileDir / "deu" / "TactileDisplayAPI.ini"
		realAtomicWrite = iniPatcher._atomicWrite

		def selectiveAtomicWrite(path: Path, data: bytes) -> None:
			if path == failingPath:
				raise OSError(13, "simulated permission denied")
			realAtomicWrite(path, data)

		with self.assertLogs("nvda", level=logging.DEBUG) as logCtx:
			with patch.object(iniPatcher, "_atomicWrite", side_effect=selectiveAtomicWrite):
				results = iniPatcher.patchTactileDisplayAPIIni()
		# Expected outcome distribution.
		self.assertEqual(results["enu"], PatchResult.WROTE)
		self.assertEqual(results["jpn"], PatchResult.UNCHANGED)
		self.assertEqual(results["deu"], PatchResult.FAILED)
		# Aggregated INFO summary with all three counts (failure-suffix variant).
		infoLines = [r for r in logCtx.records if r.levelno == logging.INFO]
		self.assertEqual(len(infoLines), 1)
		self.assertIn("1 wrote", infoLines[0].getMessage())
		self.assertIn("1 unchanged", infoLines[0].getMessage())
		self.assertIn("1 failed", infoLines[0].getMessage())
		self.assertIn("see DEBUG for details", infoLines[0].getMessage())
		# Per-failure DEBUG line names the failing path and the exception class.
		debugLines = [r.getMessage() for r in logCtx.records if r.levelno == logging.DEBUG]
		# Python auto-types ``OSError(EACCES, ...)`` as ``PermissionError``.
		self.assertTrue(
			any("FAILED" in m and str(failingPath) in m and "PermissionError" in m for m in debugLines),
			f"expected per-failure DEBUG line for {failingPath}; got: {debugLines}",
		)

	def test_summaryOmitsFailureSuffixWhenAllSucceed(self) -> None:
		with self.assertLogs("nvda", level=logging.INFO) as logCtx:
			iniPatcher.patchTactileDisplayAPIIni()
		infoLines = [r for r in logCtx.records if r.levelno == logging.INFO]
		self.assertEqual(len(infoLines), 1)
		msg = infoLines[0].getMessage()
		self.assertIn("3 wrote", msg)
		self.assertIn("0 unchanged", msg)
		self.assertNotIn("failed", msg)


class TestUtf16LeBomEndToEnd(_US1Base):
	"""End-to-end UTF-16LE+BOM: encoding preserved across read/patch/write."""

	def setUp(self) -> None:
		super().setUp()
		# Replace the staged UTF-8 fixtures with their UTF-16LE+BOM counterparts.
		for locale in ("enu", "deu", "jpn"):
			(self.tactileDir / locale / "TactileDisplayAPI.ini").write_bytes(_FIXTURE_UTF16LE_BOM)

	def test_utf16leBomPreservedAndContentPatched(self) -> None:
		results = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(set(results.values()), {PatchResult.WROTE})
		for locale in ("enu", "deu", "jpn"):
			raw = (self.tactileDir / locale / "TactileDisplayAPI.ini").read_bytes()
			self.assertTrue(raw.startswith(b"\xff\xfe"), f"BOM missing in {locale}")
			# CRLF in UTF-16LE: byte sequence 0D 00 0A 00.
			self.assertIn(b"\x0d\x00\x0a\x00", raw)
			decoded = raw[2:].decode("utf-16-le")
			self.assertIn(f"LiblouisPath={_FAKE_LIBLOUIS_DLL}", decoded)


# ---------------------------------------------------------------------------
# T019: US3 tests — portable NVDA, no caching, Unicode-safe paths
# ---------------------------------------------------------------------------


class TestNoCachingAcrossInvocations(unittest.TestCase):
	"""US3: live NVDA paths are re-resolved on every invocation; no session caching."""

	def setUp(self) -> None:
		self._tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self._tmp.cleanup)
		self.tactileDir = _stagedAddonTree(
			Path(self._tmp.name) / "addon",
			["enu"],
			_FIXTURE_UTF16LE_BOM,
		)
		self._libPatch = patch.object(iniPatcher, "get_library_path", return_value=self.tactileDir)
		self._libPatch.start()
		self.addCleanup(self._libPatch.stop)

	def test_changingNvdaLocationBetweenSessionsRewritesPath(self) -> None:
		firstDll = Path(r"E:\portableNVDA\liblouis.dll")
		firstTables = Path(r"E:\portableNVDA\louis\tables")
		secondDll = Path(r"F:\portableNVDA\liblouis.dll")
		secondTables = Path(r"F:\portableNVDA\louis\tables")
		with patch.object(iniPatcher, "_resolveNvdaLiblouis", return_value=(firstDll, firstTables)):
			r1 = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(r1["enu"], PatchResult.WROTE)
		afterFirst = (self.tactileDir / "enu" / "TactileDisplayAPI.ini").read_bytes()
		self.assertIn(b"E:\\portableNVDA\\liblouis.dll", afterFirst.decode("utf-16-le").encode("utf-8"))
		with patch.object(iniPatcher, "_resolveNvdaLiblouis", return_value=(secondDll, secondTables)):
			r2 = iniPatcher.patchTactileDisplayAPIIni()
		# Second invocation MUST write again because the resolved bytes differ.
		self.assertEqual(r2["enu"], PatchResult.WROTE)
		afterSecond = (self.tactileDir / "enu" / "TactileDisplayAPI.ini").read_bytes()
		decodedAfterSecond = afterSecond.decode("utf-16-le")
		self.assertIn("F:\\portableNVDA\\liblouis.dll", decodedAfterSecond)
		self.assertNotIn("E:\\portableNVDA", decodedAfterSecond)


class TestUnicodePathRoundTrip(unittest.TestCase):
	"""US3: paths containing non-ASCII characters round-trip without corruption."""

	def setUp(self) -> None:
		self._tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self._tmp.cleanup)
		self.tactileDir = _stagedAddonTree(
			Path(self._tmp.name) / "addon",
			["enu"],
			_FIXTURE_UTF16LE_BOM,
		)
		self._libPatch = patch.object(iniPatcher, "get_library_path", return_value=self.tactileDir)
		self._libPatch.start()
		self.addCleanup(self._libPatch.stop)

	def test_unicodeNvdaPathPreserved(self) -> None:
		unicodeRoot = "E:\\nvda български"
		dll = Path(unicodeRoot) / "liblouis.dll"
		tables = Path(unicodeRoot) / "louis" / "tables"
		with patch.object(iniPatcher, "_resolveNvdaLiblouis", return_value=(dll, tables)):
			results = iniPatcher.patchTactileDisplayAPIIni()
		self.assertEqual(results["enu"], PatchResult.WROTE)
		raw = (self.tactileDir / "enu" / "TactileDisplayAPI.ini").read_bytes()
		self.assertTrue(raw.startswith(b"\xff\xfe"))
		decoded = raw[2:].decode("utf-16-le")
		self.assertIn(f"LiblouisPath={dll}", decoded)
		self.assertIn(f"TablesPath={tables}", decoded)
		# Sanity: the non-ASCII string survived intact (no replacement chars).
		self.assertIn("български", decoded)


if __name__ == "__main__":
	unittest.main()
