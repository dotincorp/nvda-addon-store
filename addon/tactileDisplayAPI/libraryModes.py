# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""What the tactile-display library reports it is drawing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryModes:
	"""The library's drawing mode, as one query found it.

	Graphics False means braille. With hybrid on, graphics True is print characters;
	with hybrid off, a tactile image.
	"""

	graphics: bool
	"""The pins show graphics: a tactile image, or print characters while hybrid is on."""
	hybrid: bool
	"""Hybrid print and braille is enabled. Stays True while braille is shown."""
	serial: int
	"""Counts completed queries, so a report made after an operation finished can be told apart."""
