# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Guards on the release metadata that has to move whenever the version does.

``buildVars.addon_changelog`` is the "what's new" text the add-on store shows
next to the add-on. It silently announced "New in version 0.2" and that
release's three features for as long as the version sat at 0.2.0 -- nothing
tied the two together, so nothing complained.

It cannot be generated from ``CHANGELOG.md`` at build time: ``_`` is an
identity marker (``site_scons/site_tools/NVDATool/utils.py``) and xgettext
extracts translatable strings by scanning the source, so the argument has to
stay a literal or the string stops being translatable. Hence these are checks,
not generation -- releasing with stale metadata fails the test run instead of
reaching users.

See ``docs/releasing.md``.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"

# "New in version 0.9:" -- the first line of the store's what's-new text.
_CHANGELOG_HEADER_RE = re.compile(r"^New in version (?P<major>\d+)\.(?P<minor>\d+)\s*:")


def _projectVersion() -> str:
	with open(_REPO_ROOT / "pyproject.toml", "rb") as f:
		return str(tomllib.load(f)["project"]["version"])


def _addonInfo() -> dict[str, object]:
	# Imported lazily: buildVars reads pyproject.toml relative to the current
	# working directory, so it must not be imported at collection time from a
	# different cwd.
	import os

	previous = Path.cwd()
	os.chdir(_REPO_ROOT)
	try:
		import buildVars

		return dict(buildVars.addon_info)
	finally:
		os.chdir(previous)


def _versionTuple(version: str) -> tuple[int, ...]:
	return tuple(int(part) for part in version.split("."))


class TestStoreChangelog(unittest.TestCase):
	"""The store's what's-new text tracks the version it ships with."""

	def test_changelogHeaderMatchesProjectVersion(self) -> None:
		changelog = str(_addonInfo()["addon_changelog"]).strip()
		match = _CHANGELOG_HEADER_RE.match(changelog)
		self.assertIsNotNone(
			match,
			"addon_changelog must start with a 'New in version <major>.<minor>:' line; "
			f"got {changelog.splitlines()[0]!r}",
		)
		assert match is not None
		headerVersion = (int(match["major"]), int(match["minor"]))
		projectVersion = _versionTuple(_projectVersion())[:2]
		# Current *or upcoming*, not equal. The text is written and approved
		# before the version moves, and for a dev/beta the version never moves
		# at all -- a 1.0.90 beta previewing 1.1 ships with pyproject.toml still
		# at 1.0.0, and its what's-new text should name 1.1, the release it
		# actually describes. Demanding equality would either forbid that or
		# force the version bump into the same commit as the prose.
		#
		# The failure this exists to catch is staleness: the text announced
		# "New in version 0.2" for as long as the version sat at 0.2.0, and kept
		# announcing it afterwards. An older header still fails. A header from
		# the far future does not -- accepted, since nothing rots that way.
		self.assertGreaterEqual(
			headerVersion,
			projectVersion,
			"buildVars.addon_changelog announces version "
			f"{headerVersion[0]}.{headerVersion[1]}, which is older than "
			f"{projectVersion[0]}.{projectVersion[1]} in pyproject.toml. This text is "
			"shown to users in the add-on store: update it to describe what ships.",
		)

	def test_changelogHasContent(self) -> None:
		changelog = str(_addonInfo()["addon_changelog"]).strip()
		bullets = [line for line in changelog.splitlines() if line.strip().startswith("-")]
		self.assertTrue(
			bullets,
			"addon_changelog has a version header but no bullet points.",
		)


class TestStoreTextHygiene(unittest.TestCase):
	"""Text the add-on store renders verbatim carries no stray whitespace.

	The store shows ``addon_changelog`` as-is, so whitespace inside the
	literal reaches users. A tab did: the string's closing triple quote sat
	on its own tab-indented line, so the value ended with a newline and a
	tab, and that tab was published in ``addons/dotPad/0.9.90.json``.

	The checks above could not catch it -- they all ``.strip()`` the value
	before looking at it, which is right for a version header and exactly
	wrong for this.
	"""

	def test_changelogHasNoSurroundingWhitespace(self) -> None:
		changelog = str(_addonInfo()["addon_changelog"])
		self.assertEqual(
			changelog,
			changelog.strip(),
			"buildVars.addon_changelog begins or ends with whitespace, which the "
			"add-on store publishes verbatim. Close the triple-quoted string on "
			"the same line as its last bullet.",
		)

	def test_changelogLinesHaveNoTrailingWhitespace(self) -> None:
		changelog = str(_addonInfo()["addon_changelog"])
		offenders = [
			(number, line)
			for number, line in enumerate(changelog.splitlines(), start=1)
			if line != line.rstrip()
		]
		self.assertEqual(
			offenders,
			[],
			"buildVars.addon_changelog has lines ending in whitespace, which the "
			f"add-on store publishes verbatim: {offenders}",
		)


class TestRepoChangelog(unittest.TestCase):
	"""CHANGELOG.md keeps a landing zone for entries that have not shipped yet."""

	def test_unreleasedSectionExists(self) -> None:
		# Deliberately narrow. The tempting check -- "there is a section for the
		# current version" -- cannot hold during normal development: between
		# releases pyproject.toml still names the last stable version while its
		# entries accumulate under [Unreleased], so requiring a `## [0.9.0]`
		# heading would fail every commit that is not a release. What is always
		# true, and what cutting a release depends on, is that [Unreleased]
		# exists to be renamed. Step 1 of cut-a-release.md renames it and opens
		# a fresh one; forgetting the second half trips this.
		text = _CHANGELOG.read_text(encoding="utf-8")
		headings = re.findall(r"(?m)^## \[([^\]]+)\]", text)
		self.assertIn(
			"Unreleased",
			headings,
			"CHANGELOG.md has no '## [Unreleased]' section for new entries to "
			f"accumulate into. Headings found: {headings[:5]}",
		)


class TestNVDAVersionMetadata(unittest.TestCase):
	"""minimum / lastTested NVDA versions stay consistent with each other."""

	def test_lastTestedNotBelowMinimum(self) -> None:
		info = _addonInfo()
		minimum = _versionTuple(str(info["addon_minimumNVDAVersion"]))
		lastTested = _versionTuple(str(info["addon_lastTestedNVDAVersion"]))
		# Pad so 2026.1 and 2026.1.1 compare on equal footing.
		length = max(len(minimum), len(lastTested))
		minimum += (0,) * (length - len(minimum))
		lastTested += (0,) * (length - len(lastTested))
		self.assertGreaterEqual(
			lastTested,
			minimum,
			"addon_lastTestedNVDAVersion is older than addon_minimumNVDAVersion.",
		)


if __name__ == "__main__":
	unittest.main()
