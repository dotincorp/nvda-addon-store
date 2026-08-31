# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for ``GraphicPresentation``'s ``@script`` handlers (feature 016).

After feature 016, ``GraphicPresentation`` declares ``@script``-decorated
handler methods for the F-key pan/zoom grid and the ``panLeft+panRight``
chord. Each handler submits ``ExecuteOperation(operation, VARIANT())`` on
the driver's library worker. ``panLeft`` / ``panRight`` are NOT bound
individually — they remain reserved for the always-on 20-cell text
braille scroll.

The binding map below is the authoritative gesture → operation table.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock


# Authoritative FR-003 binding map: gesture-id-normalised → BrailleInputOperation member name.
# Gesture ids are lowercase per NVDA's ``inputCore.normalizeGestureIdentifier``.
#
# Updated for feature 020's keymap rework: single-key short-press drives
# viewport pan in four directions (hardware layout: f1=LEFT, f2=UP, f3=DOWN,
# f4=RIGHT), long-press of the same key jumps to the corresponding edge.
# Zoom in/out and recenter chords are unchanged. The pre-020 chord bindings
# (f1+f2, f3+f4, f1+f3, f2+f4) were replaced by the single-key + long-press
# scheme — see ``docs/keymap.md`` for the rationale.
_EXPECTED_BINDINGS: tuple[tuple[str, str], ...] = (
	# Single-key short-press: page-step viewport pan in 4 directions.
	("br(dotpad):f1", "PAN_VIEWPORT_LEFT"),
	("br(dotpad):f2", "PAN_VIEWPORT_UP"),
	("br(dotpad):f3", "PAN_VIEWPORT_DOWN"),
	("br(dotpad):f4", "PAN_VIEWPORT_RIGHT"),
	# Single-key long-press: edge jumps in the same direction.
	("br(dotpad):longpress(f1)", "PAN_VIEWPORT_HOME"),
	("br(dotpad):longpress(f2)", "PAN_VIEWPORT_TOP"),
	("br(dotpad):longpress(f3)", "PAN_VIEWPORT_BOTTOM"),
	("br(dotpad):longpress(f4)", "PAN_VIEWPORT_END"),
	# Chords: recenter, zoom in / out (unchanged from feature 016).
	("br(dotpad):panleft+panright", "PAN_VIEWPORT_CENTER"),
	("br(dotpad):f2+f3", "ZOOM_VIEWPORT_IN"),
	("br(dotpad):f1+f4", "ZOOM_VIEWPORT_OUT"),
	# Four-key chord: invert last tactile image (feature 037, v1.23 operation 20).
	("br(dotpad):f1+f2+f3+f4", "INVERT_LAST_TACTILE_IMAGE"),
)


def _makePresentation():
	"""Construct a ``GraphicPresentation`` with mocked NVDAObject + display."""
	from addon.presentations.graphic import GraphicPresentation

	obj = MagicMock(name="navObj")
	display = MagicMock(name="display")
	return GraphicPresentation(obj, display)


class TestGraphicPresentationBindings(unittest.TestCase):
	"""FR-003: ``GraphicPresentation`` binds every gesture in the binding map."""

	def test_all_FR003_gestures_bind(self) -> None:
		"""Every gesture in ``_EXPECTED_BINDINGS`` maps to a script in
		``presentation._gestureMap``.
		"""
		presentation = _makePresentation()
		for gestureId, _opName in _EXPECTED_BINDINGS:
			self.assertIn(
				gestureId,
				presentation._gestureMap,
				f"GraphicPresentation must bind {gestureId} per FR-003.",
			)

	def test_panLeft_panRight_not_bound_individually(self) -> None:
		"""FR-005 scope constraint: ``panLeft`` / ``panRight`` alone stay
		reserved for the driver's ``braille_scrollBack``/``braille_scrollForward``
		gestureMap entries (20-cell text braille scroll).
		"""
		presentation = _makePresentation()
		self.assertNotIn(
			"br(dotpad):panleft",
			presentation._gestureMap,
			"GraphicPresentation must NOT bind panLeft individually — it "
			"belongs to the 20-cell text braille scroll.",
		)
		self.assertNotIn(
			"br(dotpad):panright",
			presentation._gestureMap,
			"GraphicPresentation must NOT bind panRight individually.",
		)


class TestOperationCodesMatchTypelib(unittest.TestCase):
	"""FR-010 (d): the operation codes fed to ``ExecuteOperation`` come
	from the v1.16 typelib enum.

	The enum mirror lives in ``addon.tactileDisplayAPI.comInterface``.
	This test guards against silent typo drift — a renamed enum member
	would surface here as soon as a stale name is referenced.
	"""

	def test_all_FR003_operation_names_exist_in_enum(self) -> None:
		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		for _gestureId, opName in _EXPECTED_BINDINGS:
			self.assertTrue(
				hasattr(BrailleInputOperation, opName),
				f"BrailleInputOperation.{opName} must be defined (FR-003 binding).",
			)


class TestSubmitNoopWhenLibraryNotReady(unittest.TestCase):
	"""FR-004 defensive guards: scripts no-op silently when the library
	isn't ready, the worker is absent, or the wrapper is absent.

	Pattern mirrors ``GraphicPresentation.render``'s guards (feature 015).
	"""

	def _callScript(self, presentation, scriptName: str) -> None:
		"""Invoke a script handler on the presentation as if dispatched."""
		gesture = MagicMock(name="gesture")
		bound = getattr(presentation, scriptName)
		bound(gesture)

	def test_noop_when_driver_unavailable(self) -> None:
		"""When ``_getActiveDriver`` returns ``None``, no worker submission."""
		from unittest.mock import patch

		presentation = _makePresentation()
		with patch.object(presentation, "_getActiveDriver", return_value=None):
			# Should not raise; the driver-mock would have been called if the
			# guard were missing.
			self._callScript(presentation, "script_panViewportDown")

	def test_noop_when_libraryReady_false(self) -> None:
		"""When ``driver._libraryReady`` is ``False``, no worker submission."""
		from unittest.mock import patch

		presentation = _makePresentation()
		driver = MagicMock(name="driver")
		driver._libraryReady = False
		# Worker / tda are present but should NEVER be touched once the
		# readiness gate fails.
		driver._libraryWorker = MagicMock(name="worker")
		driver._tda = MagicMock(name="tda")
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			self._callScript(presentation, "script_panViewportDown")
		driver._libraryWorker.submitAndReport.assert_not_called()

	def test_noop_when_worker_is_none(self) -> None:
		"""When the driver has no worker, no submission."""
		from unittest.mock import patch

		presentation = _makePresentation()
		driver = MagicMock(name="driver")
		driver._libraryReady = True
		driver._libraryWorker = None
		driver._tda = MagicMock(name="tda")
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			# Must not raise.
			self._callScript(presentation, "script_panViewportDown")

	def test_noop_when_tda_is_none(self) -> None:
		"""When the driver has no wrapper, no submission."""
		from unittest.mock import patch

		presentation = _makePresentation()
		driver = MagicMock(name="driver")
		driver._libraryReady = True
		worker = MagicMock(name="worker")
		driver._libraryWorker = worker
		driver._tda = None
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			self._callScript(presentation, "script_panViewportDown")
		worker.submitAndReport.assert_not_called()

	def test_submits_executeOperation_when_ready(self) -> None:
		"""When the library is ready, the script submits ``executeOperation``
		on the worker with the right operation code.
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		presentation = _makePresentation()
		driver = MagicMock(name="driver")
		driver._libraryReady = True
		worker = MagicMock(name="worker")
		tda = MagicMock(name="tda")
		driver._libraryWorker = worker
		driver._tda = tda
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			self._callScript(presentation, "script_panViewportDown")

		# Worker received the executeOperation submission with the right enum.
		worker.submitAndReport.assert_called_once()
		args, kwargs = worker.submitAndReport.call_args
		self.assertIs(args[0], tda.executeOperation)
		self.assertEqual(args[1], BrailleInputOperation.PAN_VIEWPORT_DOWN)

	def test_submits_invertLastTactileImage_when_ready(self) -> None:
		"""``script_invertLastTactileImage`` submits ``INVERT_LAST_TACTILE_IMAGE``
		(operation code 20) when the library is ready (feature 037).
		"""
		from unittest.mock import patch

		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		presentation = _makePresentation()
		driver = MagicMock(name="driver")
		driver._libraryReady = True
		worker = MagicMock(name="worker")
		tda = MagicMock(name="tda")
		driver._libraryWorker = worker
		driver._tda = tda
		with patch.object(presentation, "_getActiveDriver", return_value=driver):
			self._callScript(presentation, "script_invertLastTactileImage")

		worker.submitAndReport.assert_called_once()
		args, _kwargs = worker.submitAndReport.call_args
		self.assertIs(args[0], tda.executeOperation)
		self.assertEqual(args[1], BrailleInputOperation.INVERT_LAST_TACTILE_IMAGE)


if __name__ == "__main__":
	unittest.main()
