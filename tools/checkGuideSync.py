#!/usr/bin/env python
# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Report where ``docs/wordSource/*.docx`` has drifted from ``docs/userGuide.md``.

The Markdown is canonical: it is what the build ships and what Crowdin translates.
The Word document is the copy that circulates by email with Dot for review, and
nothing in the build keeps the two in step, so they drift silently -- which is how
a key binding ended up documented two different ways.

This is a report, not a gate. The Word copy legitimately lags between review
rounds; run this before mailing it out, and after porting a review back::

    python tools/checkGuideSync.py

Exits 1 if any paragraph differs, 0 if the only differences are the expected ones
described in ``EXPECTED`` below. Pass ``--quiet`` for just the counts.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parent.parent
MARKDOWN = REPO / "docs" / "userGuide.md"
WORD = REPO / "docs" / "wordSource" / "NVDA Dot Pad Add-on Guide.docx"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"

EXPECTED = """Word-only content that is not drift:
  * the table of contents (a TOC field; the Markdown has no equivalent)
  * the six math examples, which are real equation objects in Word where the
    Markdown has plain-text expressions
  * blank paragraphs, which Word uses for spacing
  * the closing "--End of document." marker
"""

KEEP_AS_IS = ("--End of document.",)


def q(tag: str) -> str:
	return f"{{{W}}}{tag}"


def paragraph_text(p: ET.Element) -> str:
	return "".join(t.text or "" for t in p.iter(q("t")))


def paragraph_style(p: ET.Element) -> str:
	pPr = p.find(q("pPr"))
	if pPr is None:
		return "Normal"
	style = pPr.find(q("pStyle"))
	if style is None:
		return "Normal"
	return style.get(q("val")) or "Normal"


def word_paragraphs(path: Path) -> tuple[list[str], list[str]]:
	"""The Word document's prose, with the expected Word-only content removed.

	Returns the prose and the labels of the equation paragraphs, so their plain-text
	counterparts can be dropped from the Markdown side too.
	"""
	with zipfile.ZipFile(path) as archive:
		root = ET.fromstring(archive.read("word/document.xml").decode("utf-8"))
	body = root.find(q("body"))
	if body is None:
		raise SystemExit(f"{path} has no document body")
	out: list[str] = []
	equations: list[str] = []
	for p in body.iter(q("p")):
		if paragraph_style(p).startswith("TOC"):
			continue
		text = paragraph_text(p).strip()
		if list(p.iter(f"{{{M}}}oMath")):
			equations.append(label_of(text))
			continue
		if not text or text in KEEP_AS_IS:
			continue
		out.append(text)
	return out, equations


def label_of(text: str) -> str:
	"""The part of an example line before the expression, lowercased."""
	return re.sub(r"[^a-z0-9]+", " ", text.split(":")[0].lower()).strip()


def markdown_blocks(path: Path) -> list[str]:
	"""The Markdown's prose, flattened to one line per heading, paragraph or item."""
	out: list[str] = []
	for line in path.read_text(encoding="utf-8").splitlines():
		text = line.strip()
		if not text:
			continue
		text = re.sub(r"^#+\s*", "", text)
		text = re.sub(r"^[-*]\s+", "", text)
		text = re.sub(r"^\d+\.\s+", "", text)
		text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
		text = re.sub(r"`([^`]+)`", r"\1", text)
		out.append(text.replace("**", "").strip())
	return out


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--quiet", action="store_true", help="print only the summary")
	args = parser.parse_args()

	md = markdown_blocks(MARKDOWN)
	docx, equations = word_paragraphs(WORD)
	md = [block for block in md if label_of(block) not in equations]
	diff = [
		line
		for line in difflib.unified_diff(md, docx, "userGuide.md", WORD.name, lineterm="", n=0)
		if not line.startswith(("---", "+++", "@@"))
	]

	if not diff:
		print(f"In step: {len(md)} paragraphs match.")
		return 0

	if not args.quiet:
		for line in diff:
			where = "markdown only" if line.startswith("-") else "word only    "
			print(f"  {where}: {line[1:][:120]}")
		print()
	print(f"{len(diff)} paragraphs differ ({len(md)} in the Markdown, {len(docx)} in the Word copy).")
	print()
	print(EXPECTED)
	print("Anything else is drift. The Markdown is canonical, so port it into the Word")
	print("copy rather than the other way round.")
	return 1


if __name__ == "__main__":
	sys.exit(main())
