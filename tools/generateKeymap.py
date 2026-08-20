#!/usr/bin/env python3
"""Regenerate the gesture tables in ``docs/keymap.md`` from the addon source.

This is a maintainer-run script. It reads the addon's Python source with
``ast`` -- it does *not* import it -- and rewrites the tables in
``docs/keymap.md`` that live between ``<!-- BEGIN GENERATED: name -->`` and
``<!-- END GENERATED: name -->`` markers. Everything outside those markers is
prose that explains *why* the keymap looks the way it does; it is hand-written
and this script never touches it.

Parsing rather than importing keeps the script runnable anywhere -- pre-commit,
CI, a bare checkout -- without NVDA on ``sys.path``. It works because every
gesture in the addon is a plain string literal on a singular ``gesture=``
keyword. If a future binding is ever computed at runtime, this script will not
see it; add it to the prose by hand and note it here.

Run it after adding, removing or retargeting any ``@script`` handler.
``--dry-run`` writes nothing and exits 1 if the checked-in document would
change, which is how the pre-commit hook and CI catch drift.

Tiers
-----
A binding's tier is inferred from where it is declared, which mirrors the
resolution order NVDA actually uses (see "Resolution order" in the generated
document):

- **Tier 0** -- entries in the driver's ``gestureMap``. These map NVDA's own
  global scripts and resolve last.
- **Tier 1** -- ``@script`` handlers on the driver class. Active in every mode.
- **Tier 2** -- ``@script`` handlers on a ``Presentation`` subclass. Active only
  while that presentation is rendering, and they win over tiers 0 and 1.

Tier 2 sections are emitted per presentation class, so a presentation that
starts binding gestures appears in the document automatically rather than
waiting for somebody to remember to hand-write a section for it.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


#: Marker names this script owns, in the order they appear in the document.
SECTION_NAMES: tuple[str, ...] = ("tier0", "tier1", "tier2", "unbound")

#: Gesture identifiers in the addon are all prefixed with this source name.
GESTURE_PREFIX = "br(dotPad):"

#: Physical key order on the device, left to right. Drives table ordering so
#: the document reads in the same order the user's fingers find the buttons.
KEY_ORDER: tuple[str, ...] = ("f1", "f2", "f3", "f4", "panLeft", "panRight")

#: Human labels for the NVDA global scripts the driver maps in ``gestureMap``.
#: These scripts live in NVDA, not here, so there is no ``description=`` to
#: read. Unknown scripts fall back to their bare name.
NVDA_SCRIPT_LABELS: dict[str, str] = {
	"braille_scrollBack": "Scroll the 20-cell text braille display back",
	"braille_scrollForward": "Scroll the 20-cell text braille display forward",
	"review_activate": "Activate the current navigator object",
}

#: Source files scanned for tier 1 bindings, relative to the repository root.
DRIVER_SOURCE = Path("addon/brailleDisplayDrivers/dotPad/driver.py")

#: Directory scanned for tier 2 bindings, relative to the repository root.
PRESENTATIONS_DIR = Path("addon/presentations")

#: The document this script rewrites, relative to the repository root.
KEYMAP_DOC = Path("docs/keymap.md")

#: Heading that introduces the hand-written table of gestures feature 020
#: dropped. Rows under it are validated against the live bindings.
REMOVED_HEADING = "## Removed gestures"


class KeymapDocError(Exception):
	"""Raised when ``docs/keymap.md`` cannot be rewritten as expected."""


@dataclass(frozen=True)
class Binding:
	"""One gesture binding discovered in the source.

	``gesture`` is the identifier with the ``br(dotPad):`` prefix stripped, or
	``None`` for a ``@script`` that declares no default gesture. Those are
	real, user-assignable commands -- omitting them is how ``script_refresh``
	stayed undocumented -- so they get their own table rather than being
	dropped.
	"""

	gesture: str | None
	scriptName: str
	description: str
	tier: int
	owner: str
	sourcePath: str


def _stripGesturePrefix(identifier: str) -> str:
	"""Return ``identifier`` without the ``br(dotPad):`` source prefix."""
	if identifier.startswith(GESTURE_PREFIX):
		return identifier[len(GESTURE_PREFIX) :]
	return identifier


def _extractDescription(node: ast.expr | None) -> str:
	"""Return the string behind a ``description=`` argument.

	Handles the two shapes the addon uses: a bare string literal, and the
	usual ``_("...")`` translator call. Adjacent string literals are already
	concatenated by the parser, so implicit concatenation needs no special
	handling here.
	"""
	if node is None:
		return ""
	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return node.value.strip()
	if isinstance(node, ast.Call) and node.args:
		# ``_("...")`` -- unwrap the translator call and retry on its argument.
		return _extractDescription(node.args[0])
	return ""


def _scriptDecorator(node: ast.FunctionDef) -> ast.Call | None:
	"""Return the ``@script(...)`` decorator on ``node``, if it has one."""
	for decorator in node.decorator_list:
		if not isinstance(decorator, ast.Call):
			continue
		func = decorator.func
		name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
		if name == "script":
			return decorator
	return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
	"""Return the value of keyword argument ``name`` on ``call``."""
	for keyword in call.keywords:
		if keyword.arg == name:
			return keyword.value
	return None


def parseScriptBindings(source: str, *, tier: int, sourcePath: str) -> list[Binding]:
	"""Collect ``@script`` bindings from ``source``.

	Every decorated method becomes a :class:`Binding`, whether or not it
	declares a ``gesture=``. ``owner`` is the enclosing class name.
	"""
	tree = ast.parse(source)
	bindings: list[Binding] = []
	for classNode in ast.walk(tree):
		if not isinstance(classNode, ast.ClassDef):
			continue
		for member in classNode.body:
			if not isinstance(member, ast.FunctionDef):
				continue
			decorator = _scriptDecorator(member)
			if decorator is None:
				continue
			gestureNode = _keyword(decorator, "gesture")
			gesture: str | None = None
			if isinstance(gestureNode, ast.Constant) and isinstance(gestureNode.value, str):
				gesture = _stripGesturePrefix(gestureNode.value)
			bindings.append(
				Binding(
					gesture=gesture,
					scriptName=member.name,
					description=_extractDescription(_keyword(decorator, "description")),
					tier=tier,
					owner=classNode.name,
					sourcePath=sourcePath,
				),
			)
	return bindings


def parseGestureMapBindings(source: str, *, sourcePath: str) -> list[Binding]:
	"""Collect tier 0 bindings from a ``gestureMap = GlobalGestureMap({...})``.

	The map is a nested dict literal keyed by NVDA class name, then by script
	name. Only the inner ``{scriptName: gestureIdentifier}` pairs matter here.
	"""
	tree = ast.parse(source)
	bindings: list[Binding] = []
	for assign in ast.walk(tree):
		if not isinstance(assign, ast.Assign):
			continue
		targets = [t.id for t in assign.targets if isinstance(t, ast.Name)]
		if "gestureMap" not in targets:
			continue
		if not isinstance(assign.value, ast.Call) or not assign.value.args:
			continue
		outer = assign.value.args[0]
		if not isinstance(outer, ast.Dict):
			continue
		for inner in outer.values:
			if not isinstance(inner, ast.Dict):
				continue
			for scriptNode, gestureNode in zip(inner.keys, inner.values):
				if not isinstance(scriptNode, ast.Constant) or not isinstance(gestureNode, ast.Constant):
					continue
				scriptName = str(scriptNode.value)
				bindings.append(
					Binding(
						gesture=_stripGesturePrefix(str(gestureNode.value)),
						scriptName=scriptName,
						description=NVDA_SCRIPT_LABELS.get(scriptName, scriptName),
						tier=0,
						owner="gestureMap",
						sourcePath=sourcePath,
					),
				)
	return bindings


def presentationLabel(className: str) -> str:
	"""Turn a presentation class name into a heading a reader recognises.

	``GraphicPresentation`` -> "Graphic mode", ``ScreenCapturePresentation``
	-> "Screen capture mode". These are the names the code comments and Dot's
	QA reports already use, so deriving them beats a hand-maintained mapping
	that a new presentation would not be in.

	Acronyms would de-camel badly (``APIPresentation`` -> "A p i mode"). No
	presentation is named that way; if one ever is, special-case it here.
	"""
	stem = className.removesuffix("Presentation") or className
	spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", stem)
	return f"{spaced[:1].upper()}{spaced[1:].lower()} mode"


def gestureSortKey(gesture: str) -> tuple[int, int, tuple[int, ...], str]:
	"""Order gestures: short before long-press, singles before chords.

	Within a chord, keys sort by their physical left-to-right position so the
	tables read the way the device is laid out.
	"""
	isLongPress = gesture.startswith("longPress(")
	inner = gesture[len("longPress(") : -1] if isLongPress else gesture
	keys = inner.split("+")
	positions = tuple(KEY_ORDER.index(k) if k in KEY_ORDER else len(KEY_ORDER) for k in keys)
	return (int(isLongPress), len(keys), positions, gesture)


def _bindingSortKey(binding: Binding) -> tuple[int, int, tuple[int, ...], str]:
	assert binding.gesture is not None
	return gestureSortKey(binding.gesture)


def renderBindingTable(bindings: Sequence[Binding]) -> str:
	"""Render bound gestures as a two-column markdown table."""
	if not bindings:
		return "None currently bound."
	rows = ["| Gesture | Action |", "|---|---|"]
	for binding in sorted(bindings, key=_bindingSortKey):
		rows.append(f"| `{binding.gesture}` | {binding.description} |")
	return "\n".join(rows)


def renderUnboundTable(bindings: Sequence[Binding]) -> str:
	"""Render default-less scripts as a table of user-assignable commands."""
	if not bindings:
		return "None -- every script has a default gesture."
	rows = ["| Script | Description |", "|---|---|"]
	for binding in sorted(bindings, key=lambda b: b.scriptName):
		rows.append(f"| `{binding.scriptName}` | {binding.description} |")
	return "\n".join(rows)


def collectBindings(repoRoot: Path) -> list[Binding]:
	"""Collect every binding declared under ``repoRoot``."""
	driverPath = repoRoot / DRIVER_SOURCE
	if not driverPath.is_file():
		raise KeymapDocError(f"driver source not found: {driverPath}")
	driverSource = driverPath.read_text(encoding="utf-8")
	bindings: list[Binding] = []
	driverRel = DRIVER_SOURCE.as_posix()
	bindings.extend(parseGestureMapBindings(driverSource, sourcePath=driverRel))
	bindings.extend(parseScriptBindings(driverSource, tier=1, sourcePath=driverRel))
	for path in sorted((repoRoot / PRESENTATIONS_DIR).glob("*.py")):
		bindings.extend(
			parseScriptBindings(
				path.read_text(encoding="utf-8"),
				tier=2,
				sourcePath=path.relative_to(repoRoot).as_posix(),
			),
		)
	return bindings


def buildSections(bindings: Iterable[Binding]) -> dict[str, str]:
	"""Render every generated section, keyed by marker name."""
	allBindings = list(bindings)
	bound = [b for b in allBindings if b.gesture is not None]
	unbound = [b for b in allBindings if b.gesture is None]

	tier2Owners = sorted({b.owner for b in bound if b.tier == 2})
	tier2Parts: list[str] = []
	for owner in tier2Owners:
		ownerBindings = [b for b in bound if b.tier == 2 and b.owner == owner]
		# The class and file are traceability for maintainers, not something an
		# end user reading a gesture reference needs, so they go in a comment.
		provenance = f"<!-- {owner} in {ownerBindings[0].sourcePath} -->"
		tier2Parts.append(
			f"### {presentationLabel(owner)}\n\n{provenance}\n\n{renderBindingTable(ownerBindings)}",
		)
	tier2Body = "\n\n".join(tier2Parts) if tier2Parts else "No presentation binds any gesture."

	return {
		"tier0": renderBindingTable([b for b in bound if b.tier == 0]),
		"tier1": renderBindingTable([b for b in bound if b.tier == 1]),
		"tier2": tier2Body,
		"unbound": renderUnboundTable(unbound),
	}


def applyGeneratedSections(document: str, sections: dict[str, str]) -> str:
	"""Replace each marked region of ``document`` with its rendered section.

	Raises :class:`KeymapDocError` if a marker pair is missing, rather than
	silently producing a document with a stale table in it.
	"""
	result = document
	for name, body in sections.items():
		begin = f"<!-- BEGIN GENERATED: {name} -->"
		end = f"<!-- END GENERATED: {name} -->"
		startIndex = result.find(begin)
		endIndex = result.find(end)
		if startIndex == -1 or endIndex == -1 or endIndex < startIndex:
			raise KeymapDocError(
				f"missing or malformed marker pair for section {name!r} in {KEYMAP_DOC}. "
				f"Expected {begin} ... {end}.",
			)
		result = result[: startIndex + len(begin)] + "\n\n" + body + "\n\n" + result[endIndex:]
	return result


def parseRemovedGestures(document: str) -> list[str]:
	"""Return the gestures listed in the hand-written "Removed gestures" table.

	Reads only the rows between that heading and the next one, so tables
	elsewhere in the document cannot leak in.
	"""
	lines = document.splitlines()
	gestures: list[str] = []
	inSection = False
	for line in lines:
		if line.startswith(REMOVED_HEADING):
			inSection = True
			continue
		if inSection and line.startswith("## "):
			break
		if not inSection or not line.startswith("|"):
			continue
		firstCell = line.split("|")[1].strip()
		if firstCell.startswith("`") and firstCell.endswith("`"):
			gestures.append(firstCell.strip("`"))
	return gestures


def findRemovedGestureConflicts(document: str, globalGestures: set[str]) -> list[str]:
	"""Return gestures documented as removed that are bound globally again.

	Restoring a gesture is a legitimate change -- this only insists that the
	"Removed gestures" table stop claiming it is gone.

	``globalGestures`` must contain tier 0 and tier 1 bindings only. A tier 2
	presentation may reuse a removed identifier without contradicting the
	table: ``f2`` was dropped as a driver-level backspace and is now
	``GraphicPresentation``'s pan-up, which is exactly the reuse that
	per-presentation resolution exists to allow.
	"""
	return [g for g in parseRemovedGestures(document) if g in globalGestures]


def renderDocument(document: str, bindings: Iterable[Binding]) -> str:
	"""Return ``document`` with every generated section refreshed."""
	return applyGeneratedSections(document, buildSections(bindings))


def _buildArgParser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Regenerate the gesture tables in docs/keymap.md from the addon source.",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Write nothing; print a diff and exit 1 if the document would change.",
	)
	return parser


def main(
	argv: Sequence[str] | None = None,
	*,
	repo_root: Path | None = None,
	sourceRoot: Path | None = None,
) -> int:
	"""Entry point. Returns a process exit code.

	``repo_root`` locates ``docs/keymap.md``; ``sourceRoot`` locates the addon
	source and defaults to ``repo_root``. They are separable so tests can point
	a stale document at the real source tree.
	"""
	args = _buildArgParser().parse_args(argv)
	root = repo_root or Path(__file__).resolve().parent.parent
	sources = sourceRoot or root
	docPath = root / KEYMAP_DOC

	try:
		bindings = collectBindings(sources)
		if not docPath.is_file():
			raise KeymapDocError(f"keymap document not found: {docPath}")
		original = docPath.read_text(encoding="utf-8")
		updated = renderDocument(original, bindings)
	except KeymapDocError as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 2

	boundGestures = {b.gesture for b in bindings if b.gesture is not None}
	globalGestures = {b.gesture for b in bindings if b.gesture is not None and b.tier < 2}
	conflicts = findRemovedGestureConflicts(original, globalGestures)
	if conflicts:
		print(
			"error: these gestures are listed under "
			f'"{REMOVED_HEADING}" but are bound again: {", ".join(conflicts)}. '
			"Move them out of that table.",
			file=sys.stderr,
		)
		return 3

	if updated == original:
		if args.dry_run:
			print(f"{KEYMAP_DOC} is up to date.")
		return 0

	if args.dry_run:
		diff = difflib.unified_diff(
			original.splitlines(keepends=True),
			updated.splitlines(keepends=True),
			fromfile=f"{KEYMAP_DOC} (checked in)",
			tofile=f"{KEYMAP_DOC} (generated)",
		)
		sys.stdout.writelines(diff)
		print(f"{KEYMAP_DOC} is out of date. Run: python tools/generateKeymap.py", file=sys.stderr)
		return 1

	docPath.write_text(updated, encoding="utf-8")
	print(f"Wrote {KEYMAP_DOC} ({len(boundGestures)} bound gestures).")
	return 0


if __name__ == "__main__":
	sys.exit(main())
