# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for feature 020: Unified addon keymap."""

import unittest
from unittest.mock import MagicMock, patch

from addon.brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver
from addon.presentations.graphic import GraphicPresentation


def _gestureIdentifiersFor(scriptCallable: object) -> list[str]:
	"""Return the list of gesture identifiers NVDA's @script decorator stored on a callable.

	NVDA stores defaults on ``__func__.gestures`` (NVDA convention). When no
	``gesture=`` was passed to the decorator, the attribute is an empty list.
	"""
	# Callables produced by @script carry a `gestures` attribute holding the
	# list of default gesture identifiers. Access via the underlying function
	# if bound; otherwise access directly.
	target = getattr(scriptCallable, "__func__", scriptCallable)
	return list(getattr(target, "gestures", []))


class TestGraphicPresentationGestures(unittest.TestCase):
	"""GraphicPresentation @script bindings: 4 single-key short (page-step),
	4 single-key long (edge jumps), 3 carry-forward (zoom in/out, recenter)."""

	def _makePresentation(self) -> GraphicPresentation:
		"""Construct a GraphicPresentation with a mocked NVDAObject + Display.

		``GraphicPresentation.__init__`` takes ``(obj, display)`` since feature 016.
		"""
		mockObj = MagicMock()
		mockDisplay = MagicMock()
		return GraphicPresentation(mockObj, mockDisplay)

	def test_singleKey_shortPress_bindings(self):
		"""f1/f2/f3/f4 short = LEFT/UP/DOWN/RIGHT page-step."""
		presentation = self._makePresentation()
		expected = {
			"br(dotPad):f1": "script_panViewportLeft",
			"br(dotPad):f2": "script_panViewportUp",
			"br(dotPad):f3": "script_panViewportDown",
			"br(dotPad):f4": "script_panViewportRight",
		}
		for gesture, expectedName in expected.items():
			scriptObj = presentation.getScript(_MockGesture(gesture))
			self.assertIsNotNone(scriptObj, f"no handler for {gesture}")
			self.assertEqual(
				getattr(scriptObj, "__name__", ""),
				expectedName,
				f"{gesture} bound to wrong handler",
			)

	def test_singleKey_longPress_bindings(self):
		"""longPress(f1)/(f2)/(f3)/(f4) = HOME/TOP/BOTTOM/END edge jumps."""
		presentation = self._makePresentation()
		expected = {
			"br(dotPad):longPress(f1)": "script_panViewportHome",
			"br(dotPad):longPress(f2)": "script_panViewportTop",
			"br(dotPad):longPress(f3)": "script_panViewportBottom",
			"br(dotPad):longPress(f4)": "script_panViewportEnd",
		}
		for gesture, expectedName in expected.items():
			scriptObj = presentation.getScript(_MockGesture(gesture))
			self.assertIsNotNone(scriptObj, f"no handler for {gesture}")
			self.assertEqual(
				getattr(scriptObj, "__name__", ""),
				expectedName,
				f"{gesture} bound to wrong handler",
			)

	def test_carryForward_chord_bindings(self):
		"""Recenter, zoom in/out unchanged from feature 016."""
		presentation = self._makePresentation()
		expected = {
			"br(dotPad):panLeft+panRight": "script_panViewportCenter",
			"br(dotPad):f1+f4": "script_zoomViewportOut",
			"br(dotPad):f2+f3": "script_zoomViewportIn",
		}
		for gesture, expectedName in expected.items():
			scriptObj = presentation.getScript(_MockGesture(gesture))
			self.assertIsNotNone(scriptObj, f"no handler for {gesture}")
			self.assertEqual(
				getattr(scriptObj, "__name__", ""),
				expectedName,
				f"{gesture} bound to wrong handler",
			)

	def test_removed_chord_bindings_return_none(self):
		"""The four chord bindings removed in feature 020 must return None."""
		presentation = self._makePresentation()
		removed = [
			"br(dotPad):f1+f2",  # was script_panViewportLeft on chord
			"br(dotPad):f3+f4",  # was script_panViewportRight on chord
			"br(dotPad):f1+f3",  # was script_panViewportTop on chord (now driver-level)
			"br(dotPad):f2+f4",  # was script_panViewportBottom on chord (now driver-level)
		]
		for gesture in removed:
			scriptObj = presentation.getScript(_MockGesture(gesture))
			self.assertIsNone(
				scriptObj,
				f"{gesture} should be unbound after feature 020 but returned {scriptObj!r}",
			)


class TestDriverScriptGestures(unittest.TestCase):
	"""Driver @script gesture-string changes (US3 mode-switch moves, US2 new script,
	US4 refresh decorator strip)."""

	def test_toggleScreenCapture_moved_to_longPress(self):
		gestures = _gestureIdentifiersFor(BrailleDisplayDriver.script_toggleScreenCapture)
		self.assertIn("br(dotPad):longPress(f1+f3)", gestures)
		self.assertNotIn("br(dotPad):f1+f3", gestures)

	def test_forceTableMode_moved_to_longPress(self):
		gestures = _gestureIdentifiersFor(BrailleDisplayDriver.script_forceTableMode)
		self.assertIn("br(dotPad):longPress(f2+f3)", gestures)
		self.assertNotIn("br(dotPad):f2+f3", gestures)

	def test_graphicDisplay_stays_on_short_chord(self):
		gestures = _gestureIdentifiersFor(BrailleDisplayDriver.script_graphicDisplay)
		self.assertIn("br(dotPad):f2+f4", gestures)

	def test_brailleDisplay_bound_to_f1_plus_f3(self):
		gestures = _gestureIdentifiersFor(BrailleDisplayDriver.script_brailleDisplay)
		self.assertIn("br(dotPad):f1+f3", gestures)

	def test_refresh_has_no_default_binding(self):
		"""script_refresh keeps its @script registration but loses its default gesture."""
		gestures = _gestureIdentifiersFor(BrailleDisplayDriver.script_refresh)
		self.assertEqual(
			gestures,
			[],
			f"script_refresh should have no default gestures but has {gestures!r}",
		)


def _flattenedGlobalCommandsMap() -> dict[str, str]:
	"""Build a ``{scriptName: gestureId}`` view of the driver's gestureMap
	for ``globalCommands.GlobalCommands``.

	NVDA's ``GlobalGestureMap._map`` is keyed by gesture identifier; each
	value is a list of ``(module, className, script)`` tuples. We flatten
	the entries that target ``globalCommands.GlobalCommands`` so the test
	can express its assertions in terms of script-name → gesture (the
	shape feature 020's design captured).
	"""
	flat: dict[str, str] = {}
	for gestureId, entries in BrailleDisplayDriver.gestureMap._map.items():  # type: ignore[attr-defined]
		for module, className, script in entries:
			if module == "globalCommands" and className == "GlobalCommands" and script is not None:
				flat[script] = gestureId
	return flat


class TestDriverGestureMap(unittest.TestCase):
	"""Driver gestureMap shrinks from 10 to 3 entries after feature 020."""

	def test_gestureMap_has_only_three_entries(self):
		entries = _flattenedGlobalCommandsMap()
		self.assertEqual(
			set(entries.keys()),
			{"braille_scrollBack", "braille_scrollForward", "review_activate"},
		)

	def test_dropped_kb_emulation_entries_absent(self):
		"""The seven ``kb:*`` keyboard-emulation entries dropped by feature 020
		must NOT appear in the gestureMap. Check by walking ``_map`` and
		looking for any entry whose script field is one of the dropped names."""
		droppedScripts = {
			"kb:backspace",
			"kb:alt+leftArrow",
			"kb:alt+rightArrow",
			"kb:control+home",
			"kb:control+end",
			"kb:upArrow",
			"kb:downArrow",
		}
		for gestureId, entries in BrailleDisplayDriver.gestureMap._map.items():  # type: ignore[attr-defined]
			for module, className, script in entries:
				if module == "globalCommands" and className == "GlobalCommands":
					self.assertNotIn(
						script,
						droppedScripts,
						f"dropped kb script {script!r} (gesture {gestureId!r}) still in gestureMap",
					)


class TestScriptBrailleDisplay(unittest.TestCase):
	"""US2: script_brailleDisplay forces 'braille' presentation via the manager."""

	def test_forces_braille_presentation(self):
		driver = MagicMock(spec=BrailleDisplayDriver)
		driver._renderer = MagicMock()
		driver._renderer.presentationManager = MagicMock()
		fakeNavObj = MagicMock()
		with patch("api.getNavigatorObject", return_value=fakeNavObj):
			BrailleDisplayDriver.script_brailleDisplay(driver, MagicMock())
		driver._renderer.presentationManager.forcePresentation.assert_called_once_with(
			"braille",
			fakeNavObj,
		)
		self.assertTrue(driver._renderer._needsRender)

	def test_no_op_when_renderer_is_none(self):
		"""Defensive: if the renderer isn't attached yet (early startup), no-op."""
		driver = MagicMock(spec=BrailleDisplayDriver)
		driver._renderer = None
		with patch("api.getNavigatorObject", return_value=MagicMock()):
			# Should not raise; should not touch presentationManager.
			BrailleDisplayDriver.script_brailleDisplay(driver, MagicMock())


class _MockGesture:
	"""Minimal stand-in for an InputGesture with just an ``id`` attribute.

	``getScript`` consults ``gesture.normalizedIdentifiers`` (with optional
	``gesture.id``) to look up the bound script handler. Identifiers are
	normalized by NVDA's ``inputCore.normalizeGestureIdentifier`` (mostly
	lowercases the gesture and stabilises chord-component ordering); the
	@script-decorated handlers register their gestures under the
	normalized form, so the mock must match. Tests can pass natural casing
	(e.g. ``br(dotPad):longPress(f1)``); the mock normalizes it here so
	lookups succeed.
	"""

	def __init__(self, identifier: str) -> None:
		from inputCore import normalizeGestureIdentifier

		normalized = normalizeGestureIdentifier(identifier)
		self.id = normalized
		self.normalizedIdentifiers = [normalized]


if __name__ == "__main__":
	unittest.main()
