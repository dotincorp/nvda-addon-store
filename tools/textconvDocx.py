#!/usr/bin/env python
# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Git ``diff=docx`` textconv helper.

Renders a Word document as one line per paragraph so ``git diff`` can show
what changed in ``docs/wordSource/``. Registered via ``.gitattributes``:

    *.docx -text diff=docx

Each contributor enables it once per clone::

    git config diff.docx.textconv "python tools/textconvDocx.py"

Each line is the paragraph's style name, a tab, and its text::

    Heading2	Multi Key Commands
    ListParagraph	F2+F4: Braille mode.

Word rewrites revision ids, paragraph ids and zip member order on every save,
so the stored blob changes even when the prose does not. None of that reaches
this rendering, so a save that changed no text diffs clean. Note that git still
stores the whole new blob either way -- textconv changes the view, never the
storage, and it has no bearing on merges (a conflict here is still resolved by
picking a side).

What this cannot see, because it reads only paragraph text and style: character
formatting, comments, tracked changes, images, headers and footers, and the
numbering definitions that decide whether a list is bulleted or numbered.
"""

from __future__ import annotations

import sys
import zipfile
from xml.etree import ElementTree as ET

# The WordprocessingML and Office Math namespaces, as ElementTree spells them.
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def paragraphText(paragraph: ET.Element) -> str:
	"""Return the visible text of one ``w:p``.

	``w:t`` covers ordinary runs and ``m:t`` the runs inside an equation, which
	share no parent element -- iterating the paragraph in document order keeps
	an inline equation in its place in the sentence. Tabs and breaks become
	spaces so a tabbed table-of-contents entry does not run its heading into
	its page number.
	"""
	parts: list[str] = []
	for node in paragraph.iter():
		if node.tag in (W + "t", M + "t"):
			parts.append(node.text or "")
		elif node.tag in (W + "tab", W + "br"):
			parts.append(" ")
	return "".join(parts).strip()


def paragraphStyle(paragraph: ET.Element) -> str:
	"""Return a ``w:p``'s style id, or ``Normal`` when it carries none.

	Emitting the style is what makes a structural edit -- a paragraph promoted
	to a heading, a sentence turned into a list item -- visible as a diff
	rather than as an unchanged line.
	"""
	properties = paragraph.find(W + "pPr")
	if properties is None:
		return "Normal"
	style = properties.find(W + "pStyle")
	if style is None:
		return "Normal"
	return style.get(W + "val") or "Normal"


def renderTable(table: ET.Element) -> list[str]:
	"""Render one ``w:tbl`` as a header line, a row per ``w:tr`` and a footer."""
	lines = ["Table\t=== table ==="]
	for row in table.findall(W + "tr"):
		cells = [" ".join(paragraphText(p) for p in cell.findall(W + "p")) for cell in row.findall(W + "tc")]
		lines.append("Table\t" + " | ".join(cells))
	lines.append("Table\t=== end table ===")
	return lines


def renderBody(element: ET.Element) -> list[str]:
	"""Walk a body (or a nested container) and render its block children."""
	lines: list[str] = []
	for child in element:
		if child.tag == W + "p":
			lines.append(f"{paragraphStyle(child)}\t{paragraphText(child)}")
		elif child.tag == W + "tbl":
			lines.extend(renderTable(child))
		elif child.tag == W + "sdt":
			# A structured document tag wraps its block children in sdtContent.
			# The table of contents is one, so skipping these would drop it.
			content = child.find(W + "sdtContent")
			if content is not None:
				lines.extend(renderBody(content))
	return lines


def render(path: str) -> str:
	with zipfile.ZipFile(path) as archive:
		document = ET.fromstring(archive.read("word/document.xml"))
	body = document.find(W + "body")
	if body is None:
		return ""
	return "\n".join(renderBody(body)) + "\n"


def main() -> int:
	if len(sys.argv) != 2:
		print("usage: textconvDocx.py <path>", file=sys.stderr)
		return 2
	try:
		text = render(sys.argv[1])
	except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
		# KeyError means no word/document.xml: not a Word document, or one of
		# the older binary .doc files, which this cannot read.
		print(f"textconvDocx.py: {exc}", file=sys.stderr)
		return 1
	# Write UTF-8 bytes straight to the buffer so the output does not depend on
	# the console code page (Windows defaults to cp1252, which mangles the
	# curly quotes and dashes Word litters through a document).
	sys.stdout.buffer.write(text.encode("utf-8"))
	return 0


if __name__ == "__main__":
	sys.exit(main())
