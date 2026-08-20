# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Runtime patcher for the bundled TactileDisplayAPI library's per-locale INI files.

On every NVDA startup, before the bundled library's COM object is constructed,
this module rewrites two path keys in every per-locale TactileDisplayAPI.ini::

	[Liblouis]
	LiblouisPath=<absolute path to NVDA-bundled liblouis.dll>
	TablesPath=<absolute path to NVDA-bundled louis tables directory>

The ``[Mathcat]`` ``MathcatPath`` / ``RulesPath`` keys are deliberately left
untouched: NVDA ships ``libmathcat_py.pyd`` (Python bindings), not the
``libmathcat_c.dll`` C ABI the library would link against, so there is nothing
on the NVDA side to point those keys at. Leaving them at their shipped (empty)
values lets the library use its own bundled MathCAT engine and rules.

The patch is:

- **Surgical**: only the two target ``Key=Value`` lines are mutated. All other
  content (HID device tables, per-display keymaps, comments, library-mid-session
  writes to vestigial table keys such as ``LiteraryTable=``) is preserved verbatim.
- **Idempotent**: re-running on already-patched bytes is a no-op; no filesystem
  write occurs.
- **Atomic**: writes go to a sibling temp file, then ``os.replace()``.
- **Encoding-preserving**: auto-detects UTF-8 vs UTF-16LE+BOM from the BOM
  and re-emits the file in the same encoding.
- **Per-locale isolated**: a single locale's IO failure does not block other
  locales.
- **Read-only safe**: write failures are logged at DEBUG and absorbed without
  propagating; the addon continues. The library loads NVDA's liblouis via the
  patched ``LiblouisPath``, and the addon's own braille translation runs
  through NVDA's ``louisHelper`` via the ``GetTranslation`` callback
  regardless of the library's internal liblouis state.
- **Dev-mode aware**: when running from a git working copy (``.git`` found at or
  above the addon's installation path), the patcher skips all writes by default.
  Set ``_OVERRIDE_DEV_MODE_SKIP`` to ``True`` locally for end-to-end testing on
  a dev install (revert before commit).

Threading: not thread-safe. Call exactly once per NVDA session, synchronously,
on the main thread, before ``LibraryWorker.start()`` spawns the worker that
constructs the COM object.
"""

from __future__ import annotations

import enum
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

import brailleTables
import globalVars
from logHandler import log

from . import get_library_path

# Set to True locally for end-to-end testing of the patcher on a dev install
# (where ``.git`` lives at or above the addon's installation path). MUST stay
# False in every commit — an accidentally-True value in main would rewrite
# every contributor's 27 INIs on every NVDA launch and put their developer-
# machine paths into the repo at the first ``git add .``.
_OVERRIDE_DEV_MODE_SKIP: bool = False


#: UTF-16LE byte-order mark.
_UTF16_LE_BOM: bytes = b"\xff\xfe"
#: UTF-8 byte-order mark (stripped tolerantly on read; never emitted on write).
_UTF8_BOM: bytes = b"\xef\xbb\xbf"


class PatchResult(enum.Enum):
	"""Outcome of one per-locale patch attempt."""

	WROTE = "wrote"
	"""Bytes on disk differed; new bytes written atomically."""

	UNCHANGED = "unchanged"
	"""Computed bytes equal on-disk bytes; write skipped (idempotent steady state)."""

	FAILED = "failed"
	"""I/O error during read or write; INI bytes unchanged (atomic-rename invariant)."""

	SKIPPED = "skipped"
	"""Dev-mode signal fired; no probes, no I/O on this locale."""


class _Encoding(enum.Enum):
	"""Detected and re-emitted INI encoding."""

	UTF_8 = "utf-8"
	UTF_16_LE_BOM = "utf-16-le-bom"


def _detectEncoding(rawBytes: bytes) -> _Encoding:
	"""Detect the INI's encoding from its leading bytes (BOM-based)."""
	if rawBytes.startswith(_UTF16_LE_BOM):
		return _Encoding.UTF_16_LE_BOM
	return _Encoding.UTF_8


def _decode(rawBytes: bytes, encoding: _Encoding) -> str:
	"""Decode INI bytes to text, tolerantly stripping a leading BOM."""
	if encoding is _Encoding.UTF_16_LE_BOM:
		return rawBytes[len(_UTF16_LE_BOM) :].decode("utf-16-le")
	# UTF-8: tolerate (and strip) an optional UTF-8 BOM the generator never
	# emits but a hand-edit might have introduced.
	if rawBytes.startswith(_UTF8_BOM):
		return rawBytes[len(_UTF8_BOM) :].decode("utf-8")
	return rawBytes.decode("utf-8")


def _encode(text: str, encoding: _Encoding) -> bytes:
	"""Encode INI text back to wire bytes, re-emitting the input encoding."""
	if encoding is _Encoding.UTF_16_LE_BOM:
		return _UTF16_LE_BOM + text.encode("utf-16-le")
	return text.encode("utf-8")


def _atomicWrite(path: Path, data: bytes) -> None:
	"""Write ``data`` to ``path`` atomically via temp-file + ``os.replace``.

	The temp file is created in the same directory as the target so the
	rename is same-volume (atomic on NTFS / ReFS). On any exception during
	write or rename, the temp file is removed and the original ``path``
	is untouched.
	"""
	parent = path.parent
	tmpFd, tmpName = tempfile.mkstemp(dir=str(parent), prefix=".tdai-", suffix=".tmp")
	tmpPath = Path(tmpName)
	try:
		with os.fdopen(tmpFd, "wb") as f:
			f.write(data)
			f.flush()
			os.fsync(f.fileno())
		os.replace(tmpPath, path)
	except BaseException:
		# Best-effort cleanup of the temp file on any failure (permission,
		# replace error, disk full, KeyboardInterrupt).
		try:
			tmpPath.unlink(missing_ok=True)
		except OSError:
			pass
		raise


# Section header: optional leading whitespace, ``[NAME]``, optional trailing whitespace.
_SECTION_HEADER_RE: re.Pattern[str] = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*$")


def _replaceKeyValues(text: str, replacements: Mapping[tuple[str, str], str]) -> str:
	"""Surgically rewrite ``Key=Value`` lines inside named sections.

	``replacements`` maps ``(sectionName, keyName)`` to its new value. Only
	matching lines are modified; every other byte / line / comment / blank
	line / line-ending in ``text`` is preserved verbatim. Section names are
	matched case-sensitively (library convention); leading / trailing
	whitespace around the section header brackets is tolerated. The key
	portion of each line is matched after stripping whitespace.
	"""
	lines = text.splitlines(keepends=True)
	currentSection: str | None = None
	for i, rawLine in enumerate(lines):
		# Split the original line ending off so the header / key parse doesn't
		# see trailing CR/LF; reattach the exact ending after replacement so
		# CRLF / LF / CR / final-line-without-newline all round-trip.
		if rawLine.endswith("\r\n"):
			content, ending = rawLine[:-2], "\r\n"
		elif rawLine.endswith("\n"):
			content, ending = rawLine[:-1], "\n"
		elif rawLine.endswith("\r"):
			content, ending = rawLine[:-1], "\r"
		else:
			content, ending = rawLine, ""
		sectionMatch = _SECTION_HEADER_RE.match(content)
		if sectionMatch:
			currentSection = sectionMatch.group(1)
			continue
		if currentSection is None:
			continue
		eqIdx = content.find("=")
		if eqIdx <= 0:
			continue
		key = content[:eqIdx].strip()
		target = replacements.get((currentSection, key))
		if target is None:
			continue
		# Preserve the original "Key=" prefix (including any spacing) and reattach
		# the original line ending; only the value portion is replaced.
		prefix = content[: eqIdx + 1]
		lines[i] = f"{prefix}{target}{ending}"
	return "".join(lines)


def _findTargetInis() -> list[Path]:
	"""Return all per-locale ``TactileDisplayAPI.ini`` files shipped with the addon.

	Globs ``<addon>/tactileDisplayAPI/*/TactileDisplayAPI.ini``. Locale
	subdirectories that lack the expected INI are silently skipped. Sorted
	by locale name for deterministic ordering.
	"""
	base = get_library_path()
	return sorted(p for p in base.glob("*/TactileDisplayAPI.ini") if p.is_file())


def _isDevMode(addonPath: Path) -> Path | None:
	"""Return the git-root path if running from a working copy, else ``None``.

	Walks up from ``addonPath`` through its parents; matches a ``.git`` entry
	that is either a directory (normal worktree) or a regular file (submodule
	worktree with a ``gitdir: ...`` redirect). The ``_OVERRIDE_DEV_MODE_SKIP``
	module constant suppresses the signal regardless of ``.git`` presence.

	The path is resolved first. A dev install is commonly a symlink from NVDA's
	addons directory to the working copy, and ``__file__`` -- which is where this
	path comes from -- keeps the path the module was *loaded* through. Walking that
	unresolved climbs NVDA's configuration directory instead of the repository, finds
	no ``.git``, and the patcher then rewrites tracked files on every start.
	"""
	if _OVERRIDE_DEV_MODE_SKIP:
		return None
	addonPath = addonPath.resolve()
	for parent in (addonPath, *addonPath.parents):
		candidate = parent / ".git"
		if candidate.exists():
			return parent
	return None


def _resolveNvdaLiblouis() -> tuple[Path, Path]:
	"""Return ``(liblouis.dll path, louis tables directory)`` from NVDA's runtime layout.

	Both paths are derived from public NVDA APIs:

	- ``liblouis.dll`` lives at ``globalVars.appDir / "liblouis.dll"`` (the
	  same location ``louisHelper.py`` loads it from via ``os.add_dll_directory``).
	- The tables directory is ``brailleTables.TABLES_DIR``, a public module-
	  level constant defined as ``os.path.join(globalVars.appDir, "louis", "tables")``.

	The paths are resolved on every call (never cached) so portable-NVDA
	drive-letter changes are picked up automatically on next session.
	"""
	return (
		Path(globalVars.appDir) / "liblouis.dll",
		Path(brailleTables.TABLES_DIR),
	)


def _patchOneIni(
	iniPath: Path,
	replacements: Mapping[tuple[str, str], str],
) -> PatchResult:
	"""Patch one INI; return ``WROTE`` / ``UNCHANGED`` / ``FAILED`` without raising.

	All exceptions are caught at this boundary so a single locale's IO
	failure cannot block the others or escape into the addon-init path.
	"""
	try:
		rawBytes = iniPath.read_bytes()
		encoding = _detectEncoding(rawBytes)
		text = _decode(rawBytes, encoding)
		patchedText = _replaceKeyValues(text, replacements)
		patchedBytes = _encode(patchedText, encoding)
		if patchedBytes == rawBytes:
			return PatchResult.UNCHANGED
		_atomicWrite(iniPath, patchedBytes)
		return PatchResult.WROTE
	except Exception as exc:
		log.debug(
			f"TactileDisplayAPI INI patch: FAILED ({iniPath}) — {type(exc).__name__}: {exc}",
		)
		return PatchResult.FAILED


def patchTactileDisplayAPIIni() -> dict[str, PatchResult]:
	"""Idempotently patch every per-locale INI with NVDA's liblouis paths.

	Returns a mapping of locale name (e.g. ``"enu"``) to per-locale outcome.
	Never raises; any unexpected error during discovery or path resolution
	is caught at the outermost boundary and converted to ``FAILED`` for
	every discovered locale.
	"""
	try:
		addonPath = get_library_path()
		targets = _findTargetInis()
		if not targets:
			# Nothing to patch (addon layout error or unusual install); nothing
			# to log either — every other call site will hit the empty dict and
			# move on.
			return {}
		devModeRoot = _isDevMode(addonPath)
		if devModeRoot is not None:
			log.debug(f"TactileDisplayAPI INI patch: SKIPPED-DEV ({devModeRoot})")
			return {p.parent.name: PatchResult.SKIPPED for p in targets}
		liblouisPath, tablesPath = _resolveNvdaLiblouis()
		replacements: dict[tuple[str, str], str] = {
			("Liblouis", "LiblouisPath"): str(liblouisPath),
			("Liblouis", "TablesPath"): str(tablesPath),
		}
		results: dict[str, PatchResult] = {}
		for iniPath in targets:
			locale = iniPath.parent.name
			results[locale] = _patchOneIni(iniPath, replacements)
	except Exception as exc:
		# Outermost safety net — discovery / resolver failure beyond the
		# per-locale loop. Emit one DEBUG line and return an empty dict so
		# the addon continues to load. The library resolves liblouis from
		# whatever its (unpatched) INI points at; the addon's own braille
		# translation goes through NVDA's louisHelper regardless.
		log.debug(
			f"TactileDisplayAPI INI patch: aborted before per-locale loop — {type(exc).__name__}: {exc}",
		)
		return {}
	# Aggregated summary log.
	nWrote = sum(1 for r in results.values() if r is PatchResult.WROTE)
	nUnchanged = sum(1 for r in results.values() if r is PatchResult.UNCHANGED)
	nFailed = sum(1 for r in results.values() if r is PatchResult.FAILED)
	if nFailed:
		log.info(
			f"TactileDisplayAPI INI patch: {nWrote} wrote, {nUnchanged} unchanged, "
			f"{nFailed} failed (see DEBUG for details)",
		)
	elif nWrote:
		log.info(f"TactileDisplayAPI INI patch: {nWrote} wrote, {nUnchanged} unchanged")
	else:
		# Steady state: every locale was already correct. Nothing happened, so
		# there is nothing for a user to read in a default-level log.
		log.debug(f"TactileDisplayAPI INI patch: {nUnchanged} unchanged")
	return results
