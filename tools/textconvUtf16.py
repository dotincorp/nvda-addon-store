#!/usr/bin/env python
# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Git ``diff=utf16`` textconv helper (feature 025 / FR-013).

Decodes a UTF-16LE (with BOM) file from the filesystem and writes its
UTF-8 representation to stdout. Registered via ``.gitattributes``:

    addon/tactileDisplayAPI/*/TactileDisplayAPI.ini diff=utf16

Each contributor enables it once per clone::

    git config diff.utf16.textconv "python tools/textconvUtf16.py"

After that, ``git diff`` / ``git log -p`` / ``git show`` render the
otherwise-binary INI files as readable text. Storage is unchanged
(the files stay binary in git's index); only the diff view changes.
"""

from __future__ import annotations

import io
import sys


def main() -> int:
	if len(sys.argv) != 2:
		print("usage: textconvUtf16.py <path>", file=sys.stderr)
		return 2
	try:
		# ``io.open(..., encoding="utf-16")`` auto-detects the BOM and selects
		# UTF-16LE or UTF-16BE accordingly. Reads the entire file into memory
		# (per-locale INIs are <100 KB; size is not a concern).
		with io.open(sys.argv[1], encoding="utf-16") as f:
			text = f.read()
		# Write UTF-8 bytes directly to stdout's buffer so the output is
		# encoding-stable regardless of the console's default code page
		# (Windows defaults to cp1252 which mangles non-ASCII content).
		sys.stdout.buffer.write(text.encode("utf-8"))
	except (OSError, UnicodeDecodeError) as exc:
		print(f"textconvUtf16.py: {exc}", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
