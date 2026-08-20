# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for config-driven BrailleProvider source selection (feature 017).

After feature 017, ``BrailleProvider._doCreatePresentation`` reads
``getBrailleSource()`` from the config and returns ``BraillePresentation``
(for ``NVDA`` source) or ``LibraryBraillePresentation`` (for ``LIBRARY``
source). When ``LIBRARY`` is selected but the driver's library isn't
ready, the provider falls back to ``BraillePresentation`` and surfaces a
one-time ``ui.message`` per driver lifetime.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _makeProvider():
	"""Construct a fresh ``BrailleProvider`` instance."""
	from addon.presentations.braille import BrailleProvider

	return BrailleProvider()


def _makeDisplay():
	"""A mock ``Display`` good enough for presentation construction."""
	display = MagicMock(name="display")
	display.numCells = 40
	display.numRows = 1
	display.numCols = 40
	display.physicalNumCols = 30
	display.physicalNumRows = 10
	return display


def _makeReadyDriver():
	"""A mock driver with the library considered ready."""
	driver = MagicMock(name="driver")
	driver._libraryReady = True
	driver._libraryWorker = MagicMock(name="worker")
	driver._tda = MagicMock(name="tda")
	driver.graphicDisplay = MagicMock(name="graphicDisplay")
	driver._libraryFallbackAnnounced = False
	# Explicit: on a MagicMock any unset attribute is truthy, which would make the
	# provider treat every driver as still starting up and suppress the announcement.
	driver._librarySetupPending = False
	return driver


class TestProviderHonoursBrailleSourceConfig(unittest.TestCase):
	"""FR-005: ``BrailleProvider`` instantiates the correct subclass per config."""

	def test_provider_returns_braille_for_nvda_source(self) -> None:
		"""Config = ``NVDA`` returns the existing ``BraillePresentation``."""
		from addon.configuration import BrailleSource
		from addon.presentations.braille import BraillePresentation

		provider = _makeProvider()
		display = _makeDisplay()

		with patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.NVDA):
			result = provider._doCreatePresentation(MagicMock(name="obj"), display)

		self.assertIsInstance(result, BraillePresentation)

	def test_provider_returns_library_braille_for_library_source_when_ready(self) -> None:
		"""Config = ``LIBRARY`` + library ready returns ``LibraryBraillePresentation``."""
		from addon.configuration import BrailleSource
		from addon.presentations.braille import LibraryBraillePresentation

		provider = _makeProvider()
		display = _makeDisplay()
		driver = _makeReadyDriver()

		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
		):
			result = provider._doCreatePresentation(MagicMock(name="obj"), display)

		self.assertIsInstance(result, LibraryBraillePresentation)

	def test_provider_constructs_fresh_instance_each_call(self) -> None:
		"""No caching — two calls return two distinct instances (research §G)."""
		from addon.configuration import BrailleSource

		provider = _makeProvider()
		display = _makeDisplay()

		with patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.NVDA):
			first = provider._doCreatePresentation(MagicMock(name="obj"), display)
			second = provider._doCreatePresentation(MagicMock(name="obj"), display)

		self.assertIsNot(first, second)


class TestDefaultConfigReturnsLibrary(unittest.TestCase):
	"""During the prototype phase, ``LIBRARY`` is the default source so the
	addon exercises the new library-driven path out-of-the-box (the
	NVDA-driven path is still selectable for users who want review-mode
	exploration). When the library isn't ready, the provider falls back
	to ``BraillePresentation`` — covered in
	``TestProviderFallbackWhenLibraryNotReady``.
	"""

	def test_default_config_is_library(self) -> None:
		from addon.configuration import BrailleSource, getBrailleSource

		self.assertEqual(getBrailleSource(), BrailleSource.LIBRARY)

	def test_default_config_returns_library_braille_presentation_when_ready(self) -> None:
		from addon.presentations.braille import LibraryBraillePresentation

		provider = _makeProvider()
		display = _makeDisplay()
		driver = _makeReadyDriver()
		with patch(
			"addon.presentations.braille._getActiveDotPadDriver",
			return_value=driver,
		):
			result = provider._doCreatePresentation(MagicMock(name="obj"), display)

		self.assertIsInstance(result, LibraryBraillePresentation)


class TestProviderFallbackWhenLibraryNotReady(unittest.TestCase):
	"""FR-010 / US3: graceful fallback to NVDA mode when library can't deliver."""

	def test_provider_falls_back_to_braille_when_library_not_ready(self) -> None:
		"""``_libraryReady = False`` forces fallback to ``BraillePresentation``."""
		from addon.configuration import BrailleSource
		from addon.presentations.braille import BraillePresentation

		provider = _makeProvider()
		display = _makeDisplay()
		driver = _makeReadyDriver()
		driver._libraryReady = False

		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
			patch("wx.CallAfter"),
		):
			result = provider._doCreatePresentation(MagicMock(name="obj"), display)

		self.assertIsInstance(result, BraillePresentation)

	def test_provider_falls_back_when_no_active_driver(self) -> None:
		"""No driver attached → fallback to ``BraillePresentation`` (silent path).

		With no driver there's no per-driver state, so the one-time-per-driver
		announcement guarantee can't bind. We silently fall back; the
		next ``_doCreatePresentation`` call when a driver IS attached will
		announce if still unavailable.
		"""
		from addon.configuration import BrailleSource
		from addon.presentations.braille import BraillePresentation

		provider = _makeProvider()
		display = _makeDisplay()

		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=None),
		):
			result = provider._doCreatePresentation(MagicMock(name="obj"), display)

		self.assertIsInstance(result, BraillePresentation)

	def test_fallback_announces_once_per_driver_lifetime(self) -> None:
		"""First fallback dispatches ``ui.message`` once (via ``wx.CallAfter``);
		subsequent fallbacks do not."""
		from addon.configuration import BrailleSource

		provider = _makeProvider()
		display = _makeDisplay()
		driver = _makeReadyDriver()
		driver._libraryReady = False
		driver._libraryFallbackAnnounced = False

		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
			patch("wx.CallAfter") as mockCallAfter,
		):
			provider._doCreatePresentation(MagicMock(name="obj"), display)
			# Second call with the same driver state must NOT announce again.
			provider._doCreatePresentation(MagicMock(name="obj"), display)

		mockCallAfter.assert_called_once()
		# First positional arg is the callable (``ui.message``); second is the
		# message string.
		args, _kwargs = mockCallAfter.call_args
		self.assertEqual(len(args), 2)
		self.assertTrue(driver._libraryFallbackAnnounced)

	def test_fallback_flag_set_even_if_dispatch_raises(self) -> None:
		"""If ``wx.CallAfter`` raises, the flag is still set so the next
		fallback doesn't retry and spam the log."""
		from addon.configuration import BrailleSource

		provider = _makeProvider()
		display = _makeDisplay()
		driver = _makeReadyDriver()
		driver._libraryReady = False
		driver._libraryFallbackAnnounced = False

		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
			patch("wx.CallAfter", side_effect=RuntimeError("simulated dispatch failure")),
		):
			provider._doCreatePresentation(MagicMock(name="obj"), display)
		self.assertTrue(driver._libraryFallbackAnnounced)

	def test_fallback_announces_once_across_repeated_calls(self) -> None:
		"""The user is told once, not on every presentation. Regression guard
		for the flood observed on hardware before this fix landed.
		"""
		from addon.configuration import BrailleSource

		provider = _makeProvider()
		display = _makeDisplay()
		driver = _makeReadyDriver()
		driver._libraryReady = False
		driver._libraryFallbackAnnounced = False

		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
			patch("wx.CallAfter") as mockCallAfter,
		):
			provider._doCreatePresentation(MagicMock(name="obj"), display)
			provider._doCreatePresentation(MagicMock(name="obj"), display)
			provider._doCreatePresentation(MagicMock(name="obj"), display)

		# ui.message is dispatched exactly once across three fallback calls.
		self.assertEqual(mockCallAfter.call_count, 1)
		self.assertTrue(driver._libraryFallbackAnnounced)


class TestPresentationIsStillValidConfigAware(unittest.TestCase):
	"""``isStillValid`` invalidates on config switch so the manager re-picks
	on the next focus / review event without requiring a full NVDA restart
	(fixes the issue reported during hardware testing).
	"""

	def test_braille_presentation_valid_when_source_is_nvda(self) -> None:
		from addon.configuration import BrailleSource
		from addon.presentations.braille import BraillePresentation

		display = _makeDisplay()
		presentation = BraillePresentation(display)
		with patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.NVDA):
			self.assertTrue(presentation.isStillValid())

	def test_braille_presentation_invalid_when_source_switched_to_library(self) -> None:
		"""After the user switches to library mode, the existing
		``BraillePresentation`` reports invalid so the manager re-picks."""
		from addon.configuration import BrailleSource
		from addon.presentations.braille import BraillePresentation

		display = _makeDisplay()
		presentation = BraillePresentation(display)
		with patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY):
			self.assertFalse(presentation.isStillValid())

	def test_library_braille_presentation_valid_when_library_ready(self) -> None:
		from addon.configuration import BrailleSource
		from addon.presentations.braille import LibraryBraillePresentation

		display = _makeDisplay()
		driver = _makeReadyDriver()
		presentation = LibraryBraillePresentation(display)
		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
		):
			self.assertTrue(presentation.isStillValid())

	def test_library_braille_presentation_invalid_when_source_switched_to_nvda(self) -> None:
		from addon.configuration import BrailleSource
		from addon.presentations.braille import LibraryBraillePresentation

		display = _makeDisplay()
		presentation = LibraryBraillePresentation(display)
		with patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.NVDA):
			self.assertFalse(presentation.isStillValid())

	def test_library_braille_presentation_invalid_when_library_becomes_unhealthy(self) -> None:
		"""When ``_libraryReady`` flips False mid-session, the presentation
		invalidates so the manager re-picks (and the provider falls back
		to ``BraillePresentation``)."""
		from addon.configuration import BrailleSource
		from addon.presentations.braille import LibraryBraillePresentation

		display = _makeDisplay()
		driver = _makeReadyDriver()
		driver._libraryReady = False
		presentation = LibraryBraillePresentation(display)
		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
		):
			self.assertFalse(presentation.isStillValid())


if __name__ == "__main__":
	unittest.main()


class TestNoFallbackAnnouncementWhileStarting(unittest.TestCase):
	"""A library that has not finished starting is not a fallback worth announcing.

	The driver starts its reader threads before _setupLibrarySingleton() completes, so
	a render can arrive while the library is still coming up. That window is only
	observable when __init__ runs off the main thread -- i.e. on automatic detection --
	and it previously told the user the library was unavailable on every connection.
	"""

	def _create(self, driver):
		from addon.configuration import BrailleSource

		provider = _makeProvider()
		with (
			patch("addon.presentations.braille.getBrailleSource", return_value=BrailleSource.LIBRARY),
			patch("addon.presentations.braille._getActiveDotPadDriver", return_value=driver),
			patch.object(type(provider), "_announceFallbackOnce") as announce,
			patch("wx.CallAfter"),
		):
			result = provider._doCreatePresentation(MagicMock(name="obj"), _makeDisplay())
		return result, announce

	def test_says_nothing_while_the_library_is_still_starting(self) -> None:
		from addon.presentations.braille import BraillePresentation

		driver = _makeReadyDriver()
		driver._libraryReady = False
		driver._librarySetupPending = True

		result, announce = self._create(driver)

		self.assertIsInstance(result, BraillePresentation)
		announce.assert_not_called()

	def test_still_announces_a_genuine_failure(self) -> None:
		"""Setup finished but the library is not ready: that is worth telling the user."""
		driver = _makeReadyDriver()
		driver._libraryReady = False
		driver._librarySetupPending = False

		_result, announce = self._create(driver)

		announce.assert_called_once()

	def test_uses_the_library_once_it_is_ready(self) -> None:
		from addon.presentations.braille import LibraryBraillePresentation

		driver = _makeReadyDriver()

		result, announce = self._create(driver)

		self.assertIsInstance(result, LibraryBraillePresentation)
		announce.assert_not_called()
