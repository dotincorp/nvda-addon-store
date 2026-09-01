#!/usr/bin/env python3
# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Regenerate per-language ``TactileDisplayAPI.ini`` files for the bundled library.

This is a maintainer-run script. It reads NVDA's ``braille.py`` source and
``.po`` translation catalogues, then emits per-locale ``.ini`` files under
``addon/tactileDisplayAPI/<libLcid>/``. The ``[ControlTypes]`` and
``[StateFlags]`` sections are rewritten to mirror NVDA's
``braille.roleLabels`` / ``positiveStateLabels`` / ``negativeStateLabels``, and
the handful of ``[Settings]`` keys in ``SETTINGS_OVERRIDES`` are forced to the
values this addon needs. Every other section is preserved verbatim from the
vendor's English reference.

Run it after a vendor library drop, an NVDA translation refresh, or a change to
NVDA's ``roleLabels`` / state labels. ``--dry-run`` writes nothing and exits 1
if any file would change (idempotency / drift check).

Adding a language
-----------------
Map NVDA's locale code to the library's directory name — the library resolves
its per-locale directory by Microsoft 3-letter LCID, and the match must be
exact (see `MS-LCID
<https://learn.microsoft.com/openspecs/windows_protocols/ms-lcid/a9eac961-e77d-41a6-90a5-ce1a8b0cdb9c>`_).
Add the pair to ``NVDA_LOCALE_TO_LIBRARY_LCID`` below, re-run, and commit the
script change together with the generated ini.

Unicode braille in ini values
-----------------------------
NVDA uses raw U+2800–U+28FF braille for a few labels (``Role.SEPARATOR``,
``State.CHECKED`` and friends). Whether those survive into the library's
rendering is gated by ``LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI`` below — see
the comment there for the version history and how to flip it back if a future
library release regresses.

That same gate also decides the emitted wire encoding (see
``resolve_output_encoding``): UTF-16 LE + BOM when it is on. The vendor
reference's own encoding is *not* mirrored — it is pure ASCII, so it carries no
information about what the library's reader accepts, and v1.0.34 shipped it as
plain UTF-8 after six releases of UTF-16.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Mapping, Sequence


log = logging.getLogger("generateLibraryInis")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


RecordKind = Literal["section_header", "key_value", "comment", "blank", "raw"]


@dataclass(frozen=True, slots=True)
class IniRecord:
	"""A single logical line of a parsed ini file."""

	kind: RecordKind
	section: str
	key: str
	value: str
	raw_line: str


@dataclass(frozen=True, slots=True)
class NvdaLabel:
	"""A single ``braille.py`` table entry extracted via AST."""

	member_name: str
	english: str
	translatable: bool


class PoCatalogue:
	"""A parsed ``.po`` file: msgid → msgstr map. Fuzzy / empty msgstr omitted."""

	def __init__(self, locale: str, entries: Mapping[str, str]) -> None:
		self.locale = locale
		self._entries: dict[str, str] = dict(entries)

	def translate(self, msgid: str) -> str | None:
		return self._entries.get(msgid)

	def __len__(self) -> int:
		return len(self._entries)


@dataclass(frozen=True, slots=True)
class StateMappingTarget:
	"""Where in NVDA's tables a library state key sources its value."""

	member_name: str
	polarity: Literal["positive", "negative"]


@dataclass(frozen=True, slots=True)
class GenerationResult:
	"""Outcome of generating one locale's ini."""

	library_lcid: str
	nvda_locale: str
	output_path: Path
	new_content: str
	existing_content: str | None
	changed_keys: tuple[str, ...]
	preserved_keys: tuple[str, ...]
	unicode_braille_suppressed_keys: tuple[str, ...]
	encoding: str = "utf-8"
	"""Byte encoding emitted for the per-locale file.

	Chosen by :func:`resolve_output_encoding` from the Unicode-braille gate, not
	by mirroring the vendor reference — see that function for why.
	"""
	existing_encoding: str | None = None
	"""Wire encoding of the file already on disk, or ``None`` if there is none.

	Tracked so a file whose *text* matches but whose *bytes* are in the wrong
	encoding still counts as changed: that is exactly the drift a vendor drop
	with a differently-encoded reference introduces, and it is invisible to a
	text-only comparison.
	"""

	@property
	def is_unchanged(self) -> bool:
		return (
			self.existing_content is not None
			and self.existing_content == self.new_content
			and self.existing_encoding == self.encoding
		)


# ---------------------------------------------------------------------------
# Static mapping tables
# ---------------------------------------------------------------------------


# Library [ControlTypes] keys → NVDA Role enum member name (or None to preserve vendor default).
LIBRARY_CONTROL_TO_NVDA_ROLE: Final[Mapping[str, str | None]] = {
	"button": "BUTTON",
	"checkbox": "CHECKBOX",
	"radiobutton": "RADIOBUTTON",
	"combobox": "COMBOBOX",
	"edit": "EDITABLETEXT",
	"hyperlink": "LINK",
	"list": "LIST",
	"menu": "MENU",
	"menubar": "MENUBAR",
	"progressbar": "PROGRESSBAR",
	"scrollbar": "SCROLLBAR",
	"slider": None,
	"spinner": "SPINBUTTON",
	"tab": "TABCONTROL",
	"toolbar": "TOOLBAR",
	"tooltip": "TOOLTIP",
	"tree": "TREEVIEW",
	"groupbox": "GROUPING",
	"dialog": "DIALOG",
	"table": "TABLE",
	"dataitem": None,
	"tableitem": None,
	"separator": "SEPARATOR",
	"header": None,
	"calendar": None,
	"splitbutton": "SPLITBUTTON",
}


# Library [StateFlags] keys → (NVDA State enum member name, polarity) or None.
LIBRARY_STATE_TO_NVDA_STATE: Final[Mapping[str, StateMappingTarget | None]] = {
	"unavailable": None,
	"selected": StateMappingTarget("SELECTED", "positive"),
	"pressed": StateMappingTarget("PRESSED", "positive"),
	"checked": StateMappingTarget("CHECKED", "positive"),
	"mixed": StateMappingTarget("HALFCHECKED", "positive"),
	"unchecked": StateMappingTarget("CHECKED", "negative"),
	"readonly": StateMappingTarget("READONLY", "positive"),
	"expanded": StateMappingTarget("EXPANDED", "positive"),
	"collapsed": StateMappingTarget("COLLAPSED", "positive"),
}


# NVDA locale code → library 3-letter LCID directory name.
NVDA_LOCALE_TO_LIBRARY_LCID: Final[Mapping[str, str]] = {
	"en": "enu",
	"en_GB": "enb",
	"nl": "nld",
	"nl_NL": "nld",
	"de": "deu",
	"de_CH": "des",
	"fr": "fra",
	"fr_FR": "fra",
	"fr_CA": "frc",
	"es": "esn",
	"es_ES": "esn",
	"pt_BR": "ptb",
	"pt_PT": "ptg",
	"it": "ita",
	"it_IT": "ita",
	"ja": "jpn",
	"ko": "kor",
	"zh_CN": "chs",
	"zh_TW": "cht",
	"pl": "plk",
	"ru": "rus",
	"cs": "csy",
	"da": "dan",
	"fi": "fin",
	"sv": "sve",
	"tr": "trk",
	"hu": "hun",
	"no": "nor",
	"el": "ell",
	"he": "heb",
	"ar": "ara",
}


# Sections whose values are resolved against NVDA's label tables. ``[Settings]``
# is mutated too, but from the fixed table below rather than from NVDA; anything
# else is preserved verbatim.
MUTABLE_SECTIONS: Final[frozenset[str]] = frozenset({"ControlTypes", "StateFlags"})


#: The ini section holding the library's behaviour switches.
SETTINGS_SECTION: Final[str] = "Settings"


#: ``[Settings]`` keys this addon forces, whatever the vendor reference says.
#:
#: The vendor's ``enu`` reference doubles as this generator's input, so a vendor
#: drop overwrites anything hand-edited into it. Forcing the values here instead
#: means they survive every drop, and keeps the rationale next to the value.
#: Keys absent from the reference are appended to the section; keys present have
#: their value replaced.
SETTINGS_OVERRIDES: Final[Mapping[str, str]] = {
	# v1.36+. The library labels a graphed equation on the separate braille
	# display when one is available, and at the bottom of the tactile area when
	# it is not. The addon hands the library zero text cells — NVDA keeps the
	# 20-cell line to itself, see ``simulatedDisplay.computeSimulateDisplayArgs``
	# — so the library always takes the second path and paints the label over
	# the graphic, while NVDA is already showing that same text on the 20-cell
	# line. Turn the library's label off and let NVDA own it.
	"EquationShowLabel": "0",
	# v1.36+. Same root cause: with zero text cells the library falls back to
	# painting braille under the tactile representation, where it collides with
	# the dot 7/8 markings and duplicates what NVDA already renders on the
	# 20-cell line.
	"SuppressHybridBraille": "1",
}


# ---------------------------------------------------------------------------
# Ini parser / writer
# ---------------------------------------------------------------------------


_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*(?:;.*)?$")
_KEY_VALUE_RE = re.compile(r"^(?P<key>[^=;#\s][^=]*?)\s*=\s*(?P<value>[^;]*?)\s*(?:;.*)?$")
_COMMENT_RE = re.compile(r"^\s*[;#]")
_BLANK_RE = re.compile(r"^\s*$")


_UTF16_LE_BOM = b"\xff\xfe"
_UTF8_BOM = b"\xef\xbb\xbf"


def _decode_ini_bytes(raw_bytes: bytes) -> tuple[str, str]:
	"""Decode ini bytes to text, auto-detecting the vendor's encoding.

	v1.19 of TactileDisplayAPI switched the vendor enu ini to UTF-16 LE with
	BOM ``ff fe`` so Unicode braille values are preserved on load. Older vendor
	files (and our test fixtures) are UTF-8.

	Returns ``(text, encoding)`` where ``encoding`` is ``"utf-16-le-bom"`` or
	``"utf-8"``. The caller threads that string back into :func:`encode_ini_text`
	so per-locale files round-trip in the same wire format the library expects.
	"""
	if raw_bytes.startswith(_UTF16_LE_BOM):
		return raw_bytes[len(_UTF16_LE_BOM) :].decode("utf-16-le"), "utf-16-le-bom"
	if raw_bytes.startswith(_UTF8_BOM):
		return raw_bytes[len(_UTF8_BOM) :].decode("utf-8"), "utf-8"
	return raw_bytes.decode("utf-8"), "utf-8"


def encode_ini_text(text: str, encoding: str) -> bytes:
	"""Encode generator output back to wire bytes for the given encoding.

	Mirrors :func:`_decode_ini_bytes`: UTF-16 LE outputs are prefixed with the
	``ff fe`` BOM (required by the v1.19+ library); UTF-8 outputs are emitted
	without a BOM (matches legacy vendor files and the test fixtures).
	"""
	if encoding == "utf-16-le-bom":
		return _UTF16_LE_BOM + text.encode("utf-16-le")
	if encoding == "utf-8":
		return text.encode("utf-8")
	raise ValueError(f"Unsupported ini encoding: {encoding!r}")


def parse_ini(path: Path) -> list[IniRecord]:
	"""Parse a vendor ini file into a list of ``IniRecord`` preserving formatting.

	The parser is lossless w.r.t. *decoded text*: emitting the returned records
	back via :func:`emit_ini` and then :func:`encode_ini_text` (with the matching
	encoding from :func:`detect_ini_encoding`) produces the original file
	byte-for-byte.
	"""
	text, _encoding = _decode_ini_bytes(path.read_bytes())
	lines = text.splitlines(keepends=True)
	records: list[IniRecord] = []
	current_section = ""
	for raw_line in lines:
		# Strip the trailing newline for matching, but keep raw_line for verbatim emission.
		body = raw_line
		while body.endswith(("\r", "\n")):
			body = body[:-1]
		if _BLANK_RE.match(body):
			records.append(IniRecord("blank", current_section, "", "", raw_line))
			continue
		if _COMMENT_RE.match(body):
			records.append(IniRecord("comment", current_section, "", "", raw_line))
			continue
		section_match = _SECTION_RE.match(body)
		if section_match is not None:
			current_section = section_match.group("name")
			records.append(IniRecord("section_header", current_section, "", "", raw_line))
			continue
		kv_match = _KEY_VALUE_RE.match(body)
		if kv_match is not None:
			records.append(
				IniRecord(
					"key_value",
					current_section,
					kv_match.group("key"),
					kv_match.group("value"),
					raw_line,
				),
			)
			continue
		# Fallback: unrecognised content.
		records.append(IniRecord("raw", current_section, "", "", raw_line))
	return records


def detect_ini_encoding(path: Path) -> str:
	"""Return the wire encoding of a vendor ini file ("utf-16-le-bom" or "utf-8")."""
	return _decode_ini_bytes(path.read_bytes())[1]


def emit_ini(records: Sequence[IniRecord]) -> str:
	"""Serialise records back to a string. Returns the joined ``raw_line`` values."""
	return "".join(record.raw_line for record in records)


def apply_settings_overrides(
	records: Sequence[IniRecord],
) -> tuple[list[IniRecord], tuple[str, ...]]:
	"""Force :data:`SETTINGS_OVERRIDES` into a parsed ini's ``[Settings]`` section.

	A key already present has its value replaced (formatting preserved); a key
	the vendor reference does not carry is appended after the section's last
	``Key=Value`` line, so it lands inside the section rather than after any
	trailing blank line that separates it from the next one. Ini keys are
	matched case-insensitively but appended under the spelling in
	:data:`SETTINGS_OVERRIDES`.

	If the reference has no ``[Settings]`` section at all the records are
	returned untouched — the library treats every override as opt-in and
	defaults to its previous behaviour, so a missing section is a vendor change
	worth noticing rather than something to paper over.

	:returns: ``(new_records, changed_keys)`` where ``changed_keys`` holds
		``"[Settings]key"`` identifiers whose emitted line actually differs.
	"""
	if not any(record.section == SETTINGS_SECTION for record in records):
		log.warning(
			"vendor reference has no [%s] section; skipping %d addon override(s)",
			SETTINGS_SECTION,
			len(SETTINGS_OVERRIDES),
		)
		return list(records), ()

	lowered = {key.lower(): key for key in SETTINGS_OVERRIDES}
	changed: list[str] = []
	seen: set[str] = set()
	new_records: list[IniRecord] = []
	last_key_index: int | None = None
	line_ending = "\r\n"

	for record in records:
		if record.section == SETTINGS_SECTION and record.kind == "key_value":
			line_ending = _detect_line_ending(record.raw_line) or line_ending
			canonical = lowered.get(record.key.strip().lower())
			if canonical is not None:
				seen.add(canonical)
				wanted = SETTINGS_OVERRIDES[canonical]
				if record.value != wanted:
					record = replace_value(record, wanted)
					changed.append(f"[{SETTINGS_SECTION}]{canonical}")
			last_key_index = len(new_records)
		new_records.append(record)

	# Append whatever the reference did not carry, in declaration order.
	missing = [key for key in SETTINGS_OVERRIDES if key not in seen]
	if missing:
		# With a [Settings] section present but no keys in it, fall in right
		# after the header.
		if last_key_index is None:
			last_key_index = next(
				index
				for index, record in enumerate(new_records)
				if record.kind == "section_header" and record.section == SETTINGS_SECTION
			)
		additions = [
			IniRecord(
				"key_value",
				SETTINGS_SECTION,
				key,
				SETTINGS_OVERRIDES[key],
				f"{key}={SETTINGS_OVERRIDES[key]}{line_ending}",
			)
			for key in missing
		]
		new_records[last_key_index + 1 : last_key_index + 1] = additions
		changed.extend(f"[{SETTINGS_SECTION}]{key}" for key in missing)

	return new_records, tuple(changed)


def _detect_line_ending(raw_line: str) -> str:
	if raw_line.endswith("\r\n"):
		return "\r\n"
	if raw_line.endswith("\n"):
		return "\n"
	if raw_line.endswith("\r"):
		return "\r"
	return ""


def replace_value(record: IniRecord, new_value: str) -> IniRecord:
	"""Produce a new ``key_value`` record with ``value`` replaced, preserving formatting.

	The reconstruction preserves: leading whitespace, key text, the original
	``=`` spacing convention, any trailing whitespace+comment, and the original
	line ending.
	"""
	if record.kind != "key_value":
		raise ValueError(f"replace_value called on non-key_value record: {record.kind}")
	ending = _detect_line_ending(record.raw_line)
	body = record.raw_line[: len(record.raw_line) - len(ending)]
	match = re.match(
		r"^(?P<lead>\s*)(?P<key>[^=]*?)(?P<eq>\s*=\s*)(?P<value>[^;]*?)(?P<trail>\s*(?:;.*)?)$",
		body,
	)
	if match is None:
		# Should never happen given the record came from parse_ini, but be safe.
		new_raw = f"{record.key}={new_value}{ending}"
	else:
		new_raw = (
			f"{match.group('lead')}{match.group('key')}{match.group('eq')}"
			f"{new_value}{match.group('trail')}{ending}"
		)
	return IniRecord("key_value", record.section, record.key, new_value, new_raw)


# ---------------------------------------------------------------------------
# NVDA braille.py AST extractor
# ---------------------------------------------------------------------------


_TABLE_NAMES: Final[tuple[str, ...]] = ("roleLabels", "positiveStateLabels", "negativeStateLabels")


# Resolves gettext's standard ``.po`` backslash-escape sequences. Walking the
# input string against this table preserves Unicode codepoints 1:1, unlike a
# round-trip through Python's ``unicode_escape`` codec, which decodes each
# input byte as a Latin-1 codepoint and shreds any character above U+007F.
_PO_ESCAPES: Final[dict[str, str]] = {
	"n": "\n",
	"t": "\t",
	"r": "\r",
	'"': '"',
	"\\": "\\",
}


def _extract_member_name(key_node: ast.expr) -> str | None:
	"""Return the enum member name from ``controlTypes.Role.FOO`` or ``State.FOO``."""
	if not isinstance(key_node, ast.Attribute):
		return None
	# Outer attribute: .MEMBER
	member = key_node.attr
	inner = key_node.value
	# Inner is either Attribute(Name("controlTypes"), "Role"|"State") or Name("State")
	# (positiveStateLabels imports State directly via `from controlTypes.state import State`).
	if isinstance(inner, ast.Attribute):
		# controlTypes.Role.MEMBER  /  controlTypes.State.MEMBER
		if not isinstance(inner.value, ast.Name):
			return None
		if inner.value.id != "controlTypes":
			return None
		if inner.attr not in {"Role", "State"}:
			return None
		return member
	if isinstance(inner, ast.Name):
		if inner.id in {"Role", "State"}:
			return member
	return None


def _extract_value(value_node: ast.expr) -> tuple[str, bool] | None:
	"""Return (english, translatable). Translatable iff wrapped in a ``_()`` call."""
	if isinstance(value_node, ast.Call):
		func = value_node.func
		if isinstance(func, ast.Name) and func.id == "_":
			if len(value_node.args) >= 1 and isinstance(value_node.args[0], ast.Constant):
				const = value_node.args[0].value
				if isinstance(const, str):
					return const, True
		return None
	if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
		return value_node.value, False
	return None


def _extract_dict(dict_node: ast.Dict, table_name: str) -> dict[str, NvdaLabel]:
	"""Extract entries from one ``Dict`` AST node into a member-name → NvdaLabel map."""
	result: dict[str, NvdaLabel] = {}
	for key_node, value_node in zip(dict_node.keys, dict_node.values):
		if key_node is None:
			continue
		member = _extract_member_name(key_node)
		if member is None:
			continue
		extracted = _extract_value(value_node)
		if extracted is None:
			log.debug("Skipping non-string value for %s entry in %s", member, table_name)
			continue
		english, translatable = extracted
		result[member] = NvdaLabel(member_name=member, english=english, translatable=translatable)
	return result


def extract_nvda_labels(braille_py: Path) -> dict[str, dict[str, NvdaLabel]]:
	"""Parse NVDA's ``braille.py`` and extract the three label tables.

	Returns a dict keyed by table name: ``roleLabels``, ``positiveStateLabels``,
	``negativeStateLabels``. Raises ``RuntimeError`` if any of the three tables
	cannot be located.
	"""
	source = braille_py.read_text(encoding="utf-8")
	module = ast.parse(source, filename=str(braille_py))
	found: dict[str, dict[str, NvdaLabel]] = {}
	for node in module.body:
		target: ast.expr | None = None
		value: ast.expr | None = None
		if isinstance(node, ast.AnnAssign):
			target = node.target
			value = node.value
		elif isinstance(node, ast.Assign) and len(node.targets) == 1:
			target = node.targets[0]
			value = node.value
		if target is None or value is None:
			continue
		if not isinstance(target, ast.Name) or target.id not in _TABLE_NAMES:
			continue
		if not isinstance(value, ast.Dict):
			continue
		found[target.id] = _extract_dict(value, target.id)
	missing = [name for name in _TABLE_NAMES if name not in found]
	if missing:
		raise RuntimeError(
			f"braille.py at {braille_py} is missing expected dict(s): {', '.join(missing)}. "
			"NVDA may have refactored the source — update the AST extractor.",
		)
	return found


# ---------------------------------------------------------------------------
# .po parser
# ---------------------------------------------------------------------------


def _unescape_po(s: str) -> str:
	"""Resolve standard ``.po`` backslash-escape sequences in a Unicode string.

	Walks the input character-by-character; for ``\\X`` pairs, substitutes from
	``_PO_ESCAPES`` (recognised) or drops the backslash and keeps ``X``
	(unrecognised — matches gettext's lenient behaviour). A trailing lone
	backslash with no follower is preserved literally.

	Operates on Python ``str`` throughout; never round-trips through any codec.
	Preserves all non-ASCII codepoints unchanged regardless of Unicode plane.
	"""
	result: list[str] = []
	i = 0
	length = len(s)
	while i < length:
		c = s[i]
		if c == "\\" and i + 1 < length:
			result.append(_PO_ESCAPES.get(s[i + 1], s[i + 1]))
			i += 2
		else:
			result.append(c)
			i += 1
	return "".join(result)


def parse_po(path: Path, locale: str) -> PoCatalogue:
	"""Parse a gettext ``.po`` file into a ``PoCatalogue``.

	Multi-line msgid / msgstr are joined. Fuzzy and empty-msgstr entries are
	omitted (treated as no translation). ``msgctxt`` is ignored — NVDA's
	braille abbreviations use plain ``_()`` lookups without context.
	"""
	entries: dict[str, str] = {}
	current_msgid: list[str] | None = None
	current_msgstr: list[str] | None = None
	current_target: Literal["msgid", "msgstr"] | None = None
	is_fuzzy = False
	# Track whether we've seen msgctxt for the current entry; if so, skip it.
	has_msgctxt = False
	text = path.read_text(encoding="utf-8")

	def commit() -> None:
		nonlocal is_fuzzy, has_msgctxt
		if current_msgid is None or current_msgstr is None:
			return
		msgid = "".join(current_msgid)
		msgstr = "".join(current_msgstr)
		if msgid == "":
			# Header entry; skip.
			pass
		elif is_fuzzy:
			pass
		elif msgstr == "":
			pass
		elif has_msgctxt:
			# Context-qualified entries collide with plain _() lookups; skip.
			pass
		else:
			entries[msgid] = msgstr
		is_fuzzy = False
		has_msgctxt = False

	for raw_line in text.splitlines():
		line = raw_line.strip()
		if not line:
			# Entry boundary.
			commit()
			current_msgid = None
			current_msgstr = None
			current_target = None
			continue
		if line.startswith("#,"):
			if "fuzzy" in line.split("#,", 1)[1]:
				is_fuzzy = True
			continue
		if line.startswith("#"):
			# Comment; ignore.
			continue
		if line.startswith("msgctxt "):
			has_msgctxt = True
			continue
		if line.startswith("msgid_plural "):
			current_target = None
			continue
		if line.startswith("msgid "):
			# Possibly a new entry begins; commit the previous if pending.
			if current_msgid is not None:
				commit()
			current_msgid = [_extract_po_string(line[len("msgid ") :])]
			current_msgstr = None
			current_target = "msgid"
			continue
		if line.startswith("msgstr["):
			# Plural form; ignore for our purposes.
			current_target = None
			continue
		if line.startswith("msgstr "):
			current_msgstr = [_extract_po_string(line[len("msgstr ") :])]
			current_target = "msgstr"
			continue
		if line.startswith('"') and line.endswith('"'):
			# Continuation of the active string.
			if current_target == "msgid" and current_msgid is not None:
				current_msgid.append(_extract_po_string(line))
			elif current_target == "msgstr" and current_msgstr is not None:
				current_msgstr.append(_extract_po_string(line))
			continue
	# Flush the final entry.
	commit()
	return PoCatalogue(locale, entries)


def _extract_po_string(token: str) -> str:
	"""Extract the contents of a ``.po`` double-quoted string."""
	token = token.strip()
	if len(token) < 2 or not token.startswith('"') or not token.endswith('"'):
		return ""
	return _unescape_po(token[1:-1])


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


_UNICODE_BRAILLE_RE = re.compile(r"[⠀-⣿]")


# Flipped to True for TactileDisplayAPI v1.19+: the vendor announced
# "Fixed format of tactileDisplayAPI.ini file so unicode Braille values
# are supported" and switched the ini wire format from 8-bit text to
# UTF-16 LE + BOM so codepoints above U+007F survive the load path. With
# this gate True, NVDA's native Unicode-braille labels flow through to
# the per-locale inis — Role.SEPARATOR ("⠤⠤⠤⠤⠤"), State.PRESSED
# ("⢎⣿⡱"), State.CHECKED positive ("⣏⣿⣹") / negative ("⣏⣀⣹"),
# State.HALFCHECKED ("⣏⣸⣹") — matching what NVDA's own braille output
# shows elsewhere instead of the vendor's ASCII fallback (`<=>`, `<x>`,
# `---`).
#
# History: v1.16/v1.17/v1.18 did not handle Unicode in inis at all
# (8-bit format truncated U+2800-U+28FF to nothing); hardware testing on
# 2026-05-17 confirmed pin patterns rendered as garbage. v1.19's format
# flip fixed the load-path side; the addon's PR #116 (lib bump to v1.20)
# flips this gate alongside the bundled DLL update so the change is
# coordinated. If a future library version regresses Unicode-braille
# rendering, flip back to False until the vendor restores it.
LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI = True


def resolve_output_encoding(vendor_encoding: str) -> str:
	"""Return the wire encoding to emit, given the vendor reference's own encoding.

	Deliberately *not* a mirror of the vendor reference. Up to v1.0.33 the two
	coincided, and the generator simply echoed whatever the reference used; the
	v1.0.34 drop shipped its ``enu`` reference as plain UTF-8 again, which would
	have silently reverted all 27 locales to the pre-v1.19 8-bit format that
	truncates U+2800-U+28FF (see the gate comment above for the hardware
	evidence).

	The vendor reference is pure ASCII, so its encoding says nothing about what
	the library's *reader* accepts — and the reader has handled UTF-16 LE + BOM
	since v1.19. So the format follows the gate: Unicode braille wanted in the
	inis means UTF-16 LE + BOM, whatever bytes the reference happened to use.
	Only with the gate off do we fall back to mirroring, which keeps the
	pre-v1.19 behaviour (and the plain-UTF-8 test fixtures) intact.
	"""
	if LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI:
		return "utf-16-le-bom"
	return vendor_encoding


def _contains_unicode_braille(s: str) -> bool:
	return bool(_UNICODE_BRAILLE_RE.search(s))


@dataclass(frozen=True, slots=True)
class ResolvedValue:
	"""Outcome of resolving one library key against NVDA's labels."""

	value: str
	was_replaced: bool
	unicode_braille_suppressed: bool


def resolve_value(
	library_key: str,
	section: str,
	vendor_value: str,
	nvda_labels: dict[str, dict[str, NvdaLabel]],
	po: PoCatalogue | None,
) -> ResolvedValue:
	"""Decide the value for one ini key.

	``was_replaced=False`` means the vendor's value is preserved (no mapping,
	no NVDA equivalent, or NVDA's value contains Unicode braille and the
	library can't render it). ``unicode_braille_suppressed=True`` signals
	the third case so the caller can log per-locale.
	"""
	if section == "ControlTypes":
		nvda_member = LIBRARY_CONTROL_TO_NVDA_ROLE.get(library_key)
		if nvda_member is None:
			return ResolvedValue(vendor_value, False, False)
		label = nvda_labels["roleLabels"].get(nvda_member)
		if label is None:
			log.warning(
				"NVDA roleLabels missing entry for Role.%s (mapped from library key %r); preserving vendor default",
				nvda_member,
				library_key,
			)
			return ResolvedValue(vendor_value, False, False)
		return _apply_unicode_gate(_maybe_translate(label, po), vendor_value, section, library_key)
	if section == "StateFlags":
		target = LIBRARY_STATE_TO_NVDA_STATE.get(library_key)
		if target is None:
			return ResolvedValue(vendor_value, False, False)
		table = "positiveStateLabels" if target.polarity == "positive" else "negativeStateLabels"
		label = nvda_labels[table].get(target.member_name)
		if label is None:
			log.warning(
				"NVDA %s missing entry for State.%s (mapped from library key %r); preserving vendor default",
				table,
				target.member_name,
				library_key,
			)
			return ResolvedValue(vendor_value, False, False)
		return _apply_unicode_gate(_maybe_translate(label, po), vendor_value, section, library_key)
	return ResolvedValue(vendor_value, False, False)


def _apply_unicode_gate(resolved: str, vendor_value: str, section: str, library_key: str) -> ResolvedValue:
	if not LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI and _contains_unicode_braille(resolved):
		log.debug(
			"Library can't render Unicode braille in [%s]%s; using vendor default %r",
			section,
			library_key,
			vendor_value,
		)
		return ResolvedValue(vendor_value, False, True)
	return ResolvedValue(resolved, True, False)


def _maybe_translate(label: NvdaLabel, po: PoCatalogue | None) -> str:
	if not label.translatable or po is None:
		return label.english
	translated = po.translate(label.english)
	if translated is None:
		log.warning(
			"No translation for msgid %r in locale %r; using English fallback",
			label.english,
			po.locale,
		)
		return label.english
	return translated


def generate_locale(
	records: Sequence[IniRecord],
	nvda_labels: dict[str, dict[str, NvdaLabel]],
	po: PoCatalogue | None,
) -> tuple[list[IniRecord], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
	"""Build the per-locale record list.

	Returns ``(new_records, changed_keys, preserved_keys, unicode_braille_suppressed_keys)``.
	The latter three are lists of ``"[Section]key"`` identifiers for logging.
	"""
	records, settings_changed = apply_settings_overrides(records)
	new_records: list[IniRecord] = []
	changed: list[str] = list(settings_changed)
	preserved: list[str] = []
	unicode_suppressed: list[str] = []
	for record in records:
		if record.kind != "key_value" or record.section not in MUTABLE_SECTIONS:
			new_records.append(record)
			continue
		resolved = resolve_value(record.key, record.section, record.value, nvda_labels, po)
		identifier = f"[{record.section}]{record.key}"
		if resolved.unicode_braille_suppressed:
			unicode_suppressed.append(identifier)
		if not resolved.was_replaced:
			preserved.append(identifier)
			new_records.append(record)
			continue
		if resolved.value == record.value:
			# No actual change; emit original record (idempotent).
			new_records.append(record)
		else:
			new_records.append(replace_value(record, resolved.value))
			changed.append(identifier)
	return new_records, tuple(changed), tuple(preserved), tuple(unicode_suppressed)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _dedupe_locale_mapping(
	nvda_source: Path,
	requested_locales: Sequence[str] | None,
) -> list[tuple[str, str]]:
	"""Return ``(nvda_locale, lib_lcid)`` pairs, one per target LCID.

	When multiple NVDA locales map to the same library LCID (e.g. ``nl`` and
	``nl_NL`` both go to ``nld``), prefer the most-specific (longest) NVDA
	locale code whose ``.po`` file actually exists. Locales not in the mapping
	table are logged at INFO and skipped.
	"""
	# Group entries by target LCID.
	by_lcid: dict[str, list[str]] = {}
	for nvda_locale, lib_lcid in NVDA_LOCALE_TO_LIBRARY_LCID.items():
		if requested_locales is not None and nvda_locale not in requested_locales:
			continue
		by_lcid.setdefault(lib_lcid, []).append(nvda_locale)
	# For each LCID, prefer the most-specific NVDA locale with a real .po file.
	selected: list[tuple[str, str]] = []
	for lib_lcid, candidates in by_lcid.items():
		# Sort by length descending (most-specific first), then lexicographically for stability.
		candidates.sort(key=lambda c: (-len(c), c))
		chosen: str | None = None
		for candidate in candidates:
			if _po_path_for_locale(nvda_source, candidate).exists() or candidate == "en":
				chosen = candidate
				break
		if chosen is None:
			# Fall back to the first candidate; later code will log a missing-.po warning.
			chosen = candidates[0]
		selected.append((chosen, lib_lcid))
	# Stable ordering: sort by lib_lcid for deterministic output.
	selected.sort(key=lambda pair: pair[1])
	return selected


def _po_path_for_locale(nvda_source: Path, nvda_locale: str) -> Path:
	return nvda_source / "locale" / nvda_locale / "LC_MESSAGES" / "nvda.po"


def _log_unmapped_locales(nvda_source: Path) -> None:
	"""Walk NVDA's locale/ directory and INFO-log any locale not in the mapping table."""
	locale_dir = nvda_source / "locale"
	if not locale_dir.is_dir():
		return
	mapped = set(NVDA_LOCALE_TO_LIBRARY_LCID.keys())
	for entry in sorted(locale_dir.iterdir()):
		if not entry.is_dir():
			continue
		if entry.name in mapped:
			continue
		# Only count entries that actually have a .po (skip empty/placeholder dirs).
		if not _po_path_for_locale(nvda_source, entry.name).exists():
			continue
		log.info("Skipping %s: not in locale mapping table; library will fall back to enu/", entry.name)


def generate_all(
	*,
	nvda_source: Path,
	vendor_reference: Path,
	output_root: Path,
	requested_locales: Sequence[str] | None = None,
) -> list[GenerationResult]:
	"""Compute per-locale ``GenerationResult`` records. Performs no disk writes."""
	output_encoding = resolve_output_encoding(detect_ini_encoding(vendor_reference))
	records = parse_ini(vendor_reference)
	braille_py = nvda_source / "braille.py"
	if not braille_py.exists():
		raise FileNotFoundError(
			f"NVDA braille.py not found at {braille_py}. Check --nvda-source / $NVDA_REPO_DIR.",
		)
	nvda_labels = extract_nvda_labels(braille_py)
	results: list[GenerationResult] = []
	for nvda_locale, lib_lcid in _dedupe_locale_mapping(nvda_source, requested_locales):
		po: PoCatalogue | None
		if nvda_locale == "en":
			po = None
		else:
			po_path = _po_path_for_locale(nvda_source, nvda_locale)
			if not po_path.exists():
				log.warning(
					"Missing .po for %s; using English fallback for translatable values",
					nvda_locale,
				)
				po = None
			else:
				po = parse_po(po_path, nvda_locale)
		new_records, changed, preserved, unicode_suppressed = generate_locale(records, nvda_labels, po)
		new_content = emit_ini(new_records)
		output_path = output_root / lib_lcid / "TactileDisplayAPI.ini"
		existing_content: str | None
		existing_encoding: str | None
		if output_path.exists():
			# Decode with the same auto-detection as the vendor file so a
			# v1.18-era 8-bit ini on disk compares cleanly against a fresh
			# v1.19+ UTF-16 generation (the bytes differ; the text won't
			# unless the values themselves changed). The detected encoding is
			# kept so `is_unchanged` can still flag a wire-format-only drift.
			existing_content, existing_encoding = _decode_ini_bytes(output_path.read_bytes())
		else:
			existing_content = None
			existing_encoding = None
		results.append(
			GenerationResult(
				library_lcid=lib_lcid,
				nvda_locale=nvda_locale,
				output_path=output_path,
				new_content=new_content,
				existing_content=existing_content,
				changed_keys=changed,
				preserved_keys=preserved,
				unicode_braille_suppressed_keys=unicode_suppressed,
				encoding=output_encoding,
				existing_encoding=existing_encoding,
			),
		)
	return results


def write_results(results: Sequence[GenerationResult]) -> None:
	"""Write generated content to disk. Creates locale directories as needed."""
	for result in results:
		result.output_path.parent.mkdir(parents=True, exist_ok=True)
		# Write bytes to bypass any text-mode newline translation; the encoding
		# comes from `resolve_output_encoding` (UTF-16 LE + BOM whenever Unicode
		# braille is wanted in the inis), not from the vendor reference.
		result.output_path.write_bytes(encode_ini_text(result.new_content, result.encoding))


def print_dry_run_diff(results: Sequence[GenerationResult]) -> bool:
	"""Print per-locale diffs to stdout. Returns True if any change would have occurred.

	Writes via stdout's binary buffer so Unicode braille values survive Windows
	consoles whose default encoding (cp1252) can't represent them.
	"""
	any_changed = False
	for result in results:
		if result.is_unchanged:
			continue
		any_changed = True
		old_lines = (result.existing_content or "").splitlines(keepends=True)
		new_lines = result.new_content.splitlines(keepends=True)
		diff_text = (
			"".join(
				difflib.unified_diff(
					old_lines,
					new_lines,
					fromfile=f"a/{result.output_path}",
					tofile=f"b/{result.output_path}",
					n=3,
				),
			)
			+ "\n"
		)
		sys.stdout.buffer.write(diff_text.encode("utf-8"))
	return any_changed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_paths(args: argparse.Namespace, repo_root: Path) -> tuple[Path, Path, Path]:
	"""Resolve user-supplied paths against the repo root. Returns (nvda_source, vendor, output_root)."""
	nvda_source_str = args.nvda_source
	if nvda_source_str is None:
		nvda_source_str = os.environ.get("NVDA_REPO_DIR") or str(repo_root / ".." / "nvda" / "source")
	nvda_source = Path(nvda_source_str).resolve()
	vendor = (
		Path(args.vendor_reference).resolve()
		if args.vendor_reference
		else ((repo_root / "addon" / "tactileDisplayAPI" / "enu" / "TactileDisplayAPI.ini").resolve())
	)
	output_root = (
		Path(args.output_root).resolve()
		if args.output_root
		else ((repo_root / "addon" / "tactileDisplayAPI").resolve())
	)
	return nvda_source, vendor, output_root


def _build_arg_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description=(
			"Regenerate per-language TactileDisplayAPI.ini files using NVDA's braille "
			"abbreviations. See the module docstring for the full procedure."
		),
		epilog=(
			"Re-run when: (a) the bundled TactileDisplayAPI library updates, "
			"(b) NVDA's braille.roleLabels / positiveStateLabels / negativeStateLabels "
			"change, or (c) you want to add support for a new NVDA language. "
			"See CLAUDE.md for the full procedure."
		),
	)
	parser.add_argument(
		"--nvda-source",
		help="Path to NVDA source clone (default: ../nvda/source or $NVDA_REPO_DIR).",
	)
	parser.add_argument(
		"--vendor-reference",
		help="Path to the vendor's English reference ini "
		"(default: addon/tactileDisplayAPI/enu/TactileDisplayAPI.ini).",
	)
	parser.add_argument(
		"--output-root",
		help="Directory under which per-locale subdirs are created (default: addon/tactileDisplayAPI/).",
	)
	parser.add_argument(
		"--locale",
		action="append",
		dest="locales",
		help="Restrict to this NVDA locale code (repeatable). Default: all mapped locales.",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Print per-locale diffs; write nothing. Exit 1 if any file would change.",
	)
	verbosity = parser.add_mutually_exclusive_group()
	verbosity.add_argument("--verbose", "-v", action="store_true", help="DEBUG-level logging.")
	verbosity.add_argument("--quiet", "-q", action="store_true", help="WARNING-level logging only.")
	return parser


def _configure_logging(args: argparse.Namespace) -> None:
	if args.verbose:
		level = logging.DEBUG
	elif args.quiet:
		level = logging.WARNING
	else:
		level = logging.INFO
	logging.basicConfig(level=level, format="%(levelname)s %(message)s", stream=sys.stderr, force=True)


def _exit_code_for_inputs(nvda_source: Path, vendor_reference: Path) -> int:
	if not vendor_reference.exists():
		print(f"error: vendor reference not found: {vendor_reference}", file=sys.stderr)
		return 2
	if not (nvda_source / "braille.py").exists():
		print(
			f"error: NVDA braille.py not found under {nvda_source}. Set --nvda-source or $NVDA_REPO_DIR.",
			file=sys.stderr,
		)
		return 2
	return 0


def main(argv: Sequence[str] | None = None, *, repo_root: Path | None = None) -> int:
	parser = _build_arg_parser()
	try:
		args = parser.parse_args(argv)
	except SystemExit as exc:
		# argparse exits 2 on bad args by default; remap to our 3.
		if isinstance(exc.code, int) and exc.code == 2:
			return 3
		raise
	_configure_logging(args)
	root = repo_root if repo_root is not None else Path(__file__).resolve().parent.parent
	nvda_source, vendor_reference, output_root = _resolve_paths(args, root)
	status = _exit_code_for_inputs(nvda_source, vendor_reference)
	if status != 0:
		return status
	log.info("Parsing vendor reference: %s", vendor_reference)
	log.info("Parsing NVDA braille.py: %s", nvda_source / "braille.py")
	try:
		results = generate_all(
			nvda_source=nvda_source,
			vendor_reference=vendor_reference,
			output_root=output_root,
			requested_locales=args.locales,
		)
	except RuntimeError as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 2
	for result in results:
		log.info(
			"Generated %s → %s (%d keys changed, %d preserved)",
			result.library_lcid,
			result.output_path,
			len(result.changed_keys),
			len(result.preserved_keys),
		)
	# Aggregate Unicode-braille suppression notice across locales.
	suppressed_seen: set[str] = set()
	for result in results:
		suppressed_seen.update(result.unicode_braille_suppressed_keys)
	if suppressed_seen:
		log.info(
			"Unicode-braille values suppressed for keys: %s. With "
			"LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI=True this only fires "
			"if the gate was manually flipped back to False.",
			", ".join(sorted(suppressed_seen)),
		)
	if args.locales is None:
		# Only enumerate "skipped" locales on a full run; --locale already says what's wanted.
		_log_unmapped_locales(nvda_source)
	if args.dry_run:
		would_change = print_dry_run_diff(results)
		log.info(
			"Dry run: %d locale(s) processed; %s",
			len(results),
			"changes would be written" if would_change else "no changes",
		)
		return 1 if would_change else 0
	try:
		write_results(results)
	except OSError as exc:
		print(f"error: failed to write output: {exc}", file=sys.stderr)
		return 4
	log.info("Done: %d locales generated.", len(results))
	return 0


if __name__ == "__main__":
	sys.exit(main())
