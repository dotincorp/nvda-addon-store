# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated, NV Access Limited

from __future__ import annotations

from typing import cast

import braille
import config
import louis
import louisHelper


def _getBrailleTableList(brailleTable: str | None) -> list[str]:
	"""Get the table list for louisHelper.translate().

	``braille.handler.table`` resolves 'auto' and addon-bundled tables, so only
	filenames are returned -- the custom resolver in louisHelper handles paths.

	:param brailleTable: Explicit table name, or None to use configured default.
	:returns: List of table specifiers for louisHelper.translate().
	"""
	if not brailleTable:
		# ``braille.handler`` is None before NVDA finishes initialising braille;
		# fall back to the configured table name, which the resolver also accepts.
		handler = braille.handler
		if handler is not None:
			brailleTable = handler.table.fileName
		else:
			brailleTable = cast(str, config.conf["braille"]["translationTable"])  # type: ignore[index]
	return [brailleTable, "braille-patterns.cti"]


def translateTextToBraille(text: str, brailleTable: str | None = None) -> list[int]:
	"""Translate text to braille cells.

	:param text: The text to translate.
	:param brailleTable: Braille table name. If None, uses configured default.
	:returns: List of braille cell values.
	"""
	return louisHelper.translate(
		_getBrailleTableList(brailleTable),
		text,
		mode=louis.dotsIO,
	)[0]


def translateTextWithCursor(
	text: str,
	cursorOffset: int | None = None,
	brailleTable: str | None = None,
) -> tuple[list[int], list[int], int | None]:
	"""Translate ``text`` to braille cells with cursor + position mapping.

	Same table-resolution path as :func:`translateTextToBraille` (so callers
	get ``braille.handler.table``'s smart resolution for free), and
	additionally returns:

	- the braille-to-raw position mapping (one entry per output cell,
	  mapping back to the input character index), and
	- the braille-space cursor position corresponding to ``cursorOffset``
	  in input space.

	The braille-to-raw map is what NVDA's own braille handler uses to
	apply selection markers (dots 7+8) post-translation
	(``source/braille.py:637``), and is also what the bundled
	TactileDisplayAPI library fills into the ``GetTranslation``
	``originalOffsets`` OUT array so it can apply selection / typeform
	markers based on its ``[BrailleMarking]`` ini configuration.

	:param text: The text to translate.
	:param cursorOffset: Cursor position in input-character-index space, or
		``None`` for "no cursor" (distinguished from ``0`` so callers can
		differentiate "cursor at start" from "no cursor at all").
	:param brailleTable: Explicit table name. If ``None``, uses NVDA's
		currently-configured output table.
	:returns: ``(cells, brailleToRawPos, brailleCursorPos)`` where
		``cells`` is a list of 8-bit braille-cell ints,
		``brailleToRawPos`` is a list of input-position-per-output-cell
		offsets (same length as ``cells``), and ``brailleCursorPos`` is
		the braille-space cursor position or ``None`` if ``cursorOffset``
		was ``None``.
	"""
	# Plain ``dotsIO``: liblouis emits its normal multi-cell ``\xNNNN`` fallback
	# for characters with no mapping in the active table, matching NVDA's own
	# braille output for unmapped content.
	cells, brailleToRawPos, _rawToBraillePos, brailleCursorPos = louisHelper.translate(
		_getBrailleTableList(brailleTable),
		text,
		cursorPos=cursorOffset,
		mode=louis.dotsIO,
	)
	return cells, brailleToRawPos, brailleCursorPos
