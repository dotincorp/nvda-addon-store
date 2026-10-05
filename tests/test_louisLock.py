# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""liblouis translations are serialised once the lock is installed."""

from __future__ import annotations

import os
import threading
import time
import unittest
from typing import Any

import louis

from addon.utils import louisLock


class _LouisPatchTestCase(unittest.TestCase):
	def setUp(self) -> None:
		originals = {name: getattr(louis, name) for name in louisLock._PATCHED_FUNCTIONS}

		def restore() -> None:
			for name, fn in originals.items():
				setattr(louis, name, fn)

		self.addCleanup(restore)


class TestInstall(_LouisPatchTestCase):
	def test_wrapsTranslateAndBackTranslate(self) -> None:
		louisLock.install()
		for name in louisLock._PATCHED_FUNCTIONS:
			self.assertTrue(getattr(getattr(louis, name), louisLock._SERIALIZED_MARKER, False), name)

	def test_secondInstallDoesNotWrapAgain(self) -> None:
		louisLock.install()
		first = louis.translate
		louisLock.install()
		self.assertIs(louis.translate, first)

	def test_serialisesConcurrentCalls(self) -> None:
		inFlight = 0
		maxInFlight = 0
		counterLock = threading.Lock()

		def fakeTranslate(*args: Any, **kwargs: Any) -> None:
			nonlocal inFlight, maxInFlight
			with counterLock:
				inFlight += 1
				maxInFlight = max(maxInFlight, inFlight)
			time.sleep(0.005)
			with counterLock:
				inFlight -= 1

		louis.translate = fakeTranslate
		louisLock.install()
		threads = [threading.Thread(target=lambda: [louis.translate() for _ in range(20)]) for _ in range(4)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()
		self.assertEqual(maxInFlight, 1)


class TestRealLiblouis(_LouisPatchTestCase):
	"""Unlocked, this loop takes the process down with an access violation within seconds."""

	def test_concurrentTranslationsMatchSingleThreadedOutput(self) -> None:
		tablesDir = os.path.join(os.path.dirname(louis.__file__), "tables")
		tables = [os.path.join(tablesDir, "en-ueb-g2.ctb"), os.path.join(tablesDir, "braille-patterns.cti")]
		# Varied lengths, because liblouis re-allocates its shared buffers by size.
		inputs = [
			"portable - File Explorer",
			"Windows PowerShell terminal",
			"The quick brown fox jumps over the lazy dog. " * 40,
		]
		expected = {text: louis.translate(tables, text, mode=louis.dotsIO) for text in inputs}
		louisLock.install()
		mismatches: list[str] = []
		deadline = time.monotonic() + 1.0

		def translateUntilDeadline(offset: int) -> None:
			i = offset
			while time.monotonic() < deadline:
				text = inputs[i % len(inputs)]
				if louis.translate(tables, text, mode=louis.dotsIO) != expected[text]:
					mismatches.append(text)
				i += 1

		threads = [threading.Thread(target=translateUntilDeadline, args=(n,)) for n in range(2)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()
		self.assertEqual(mismatches, [])
