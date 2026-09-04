# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for the per-presentation gesture-binding architecture (feature 016).

After feature 016, ``addon.presentations.base.Presentation`` inherits from
``baseObject.ScriptableObject`` so subclasses can declare ``@script``
handlers. ``BrailleDisplayDriver.getScript`` delegates to the active
presentation first, then falls through to its own bindings.

The ``(ScriptableObject, ABC)`` MRO and the ``getScript`` delegation surface
are documented in ``addon/presentations/base.py``.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock


class TestPresentationIsScriptableObject(unittest.TestCase):
	"""FR-001: ``Presentation`` inherits from ``ScriptableObject``.

	Research §A: ``ScriptableType`` ⊆ ``AutoPropertyType`` ⊆ ``ABCMeta``,
	so Python auto-picks the most-derived metaclass and the multiple
	inheritance resolves without conflict.
	"""

	def test_presentation_is_scriptableobject(self) -> None:
		"""``Presentation`` is a subclass of ``baseObject.ScriptableObject``."""
		from baseObject import ScriptableObject

		from addon.presentations.base import Presentation

		self.assertTrue(
			issubclass(Presentation, ScriptableObject),
			"Presentation must inherit from baseObject.ScriptableObject so "
			"@script-decorated methods on subclasses are bound at instance "
			"construction time.",
		)


class TestConcreteInitCallsSuper(unittest.TestCase):
	"""FR-001: every concrete subclass populates ``_gestureMap`` at init.

	If a subclass forgets ``super().__init__()``, ``ScriptableObject.__init__``
	never runs and ``self._gestureMap`` stays unset — any ``@script`` handler
	on that class would then be unreachable.
	"""

	def test_graphic_presentation_init_populates_gestureMap(self) -> None:
		from addon.presentations.graphic import GraphicPresentation

		obj = MagicMock(name="navObj")
		display = MagicMock(name="display")
		presentation = GraphicPresentation(obj, display)
		self.assertTrue(
			hasattr(presentation, "_gestureMap"),
			"GraphicPresentation.__init__ must call super().__init__() so "
			"ScriptableObject populates _gestureMap.",
		)
		self.assertIsInstance(presentation._gestureMap, dict)

	def test_braille_presentation_init_populates_gestureMap(self) -> None:
		from addon.presentations.braille import BraillePresentation

		display = MagicMock(name="display")
		display.numCells = 40
		display.numRows = 1
		display.numCols = 40
		presentation = BraillePresentation(display)
		self.assertTrue(hasattr(presentation, "_gestureMap"))
		self.assertIsInstance(presentation._gestureMap, dict)

	def test_screen_capture_presentation_init_populates_gestureMap(self) -> None:
		from addon.presentations.screenCapture import ScreenCapturePresentation

		display = MagicMock(name="display")
		presentation = ScreenCapturePresentation(display)
		self.assertTrue(hasattr(presentation, "_gestureMap"))
		self.assertIsInstance(presentation._gestureMap, dict)


def _makeDriver():
	"""Build a ``BrailleDisplayDriver`` with the fields ``getScript`` reads.

	Bypasses ``__init__`` (which does device I/O) and populates just
	``_renderer`` and the inherited ``_gestureMap``. Pattern matches
	``tests/test_renderer_autoTrigger.py::_makeRenderer`` and
	``tests/test_driver_librarySingleton.py``.
	"""
	from addon.brailleDisplayDrivers.dotPad.driver import BrailleDisplayDriver

	driver = BrailleDisplayDriver.__new__(BrailleDisplayDriver)
	# ScriptableObject.__init__ populates self._gestureMap from the class's
	# decorated scripts. Run it explicitly because we skipped __init__.
	from baseObject import ScriptableObject

	ScriptableObject.__init__(driver)
	driver._renderer = MagicMock(name="renderer")
	return driver


class TestDriverGetScriptDelegates(unittest.TestCase):
	"""FR-002: ``BrailleDisplayDriver.getScript`` asks the active presentation first."""

	def test_driver_getScript_returns_presentation_binding_when_present(self) -> None:
		"""When the active presentation has a script for the gesture, the
		driver returns it (presentation-wins).
		"""
		driver = _makeDriver()
		sentinel = MagicMock(name="presentationScript")
		activePresentation = MagicMock(name="graphicPresentation")
		activePresentation.getScript.return_value = sentinel
		driver._renderer.presentationManager.activePresentation = activePresentation

		gesture = MagicMock(name="gesture")
		gesture.normalizedIdentifiers = ["br(dotpad):f4"]

		result = driver.getScript(gesture)

		self.assertIs(result, sentinel)
		activePresentation.getScript.assert_called_once_with(gesture)

	def test_driver_getScript_falls_through_when_presentation_returns_none(self) -> None:
		"""When the active presentation returns ``None``, the driver falls
		through to its own ``ScriptableObject.getScript`` lookup. We use a
		gesture identifier the driver itself binds (``br(dotpad):f2+f4``
		→ ``script_brailleDisplay``) so we can verify
		the fallthrough yielded a real driver script — not just ``None``.
		"""
		driver = _makeDriver()
		activePresentation = MagicMock(name="presentation")
		activePresentation.getScript.return_value = None
		driver._renderer.presentationManager.activePresentation = activePresentation

		gesture = MagicMock(name="gesture")
		gesture.normalizedIdentifiers = ["br(dotpad):f2+f4"]

		result = driver.getScript(gesture)

		activePresentation.getScript.assert_called_once_with(gesture)
		self.assertIsNotNone(
			result,
			"Driver's own script_brailleDisplay is bound to f2+f4; fallthrough must surface it.",
		)
		# The returned object is a bound method whose underlying function
		# is script_brailleDisplay.
		self.assertEqual(getattr(result, "__name__", None), "script_brailleDisplay")

	def test_driver_getScript_handles_no_active_presentation(self) -> None:
		"""When ``activePresentation`` is ``None``, the override skips
		delegation and goes straight to ``super().getScript``.
		"""
		driver = _makeDriver()
		driver._renderer.presentationManager.activePresentation = None

		gesture = MagicMock(name="gesture")
		gesture.normalizedIdentifiers = ["br(dotpad):f2+f4"]

		result = driver.getScript(gesture)

		self.assertIsNotNone(result)
		self.assertEqual(getattr(result, "__name__", None), "script_brailleDisplay")

	def test_driver_getScript_handles_missing_renderer(self) -> None:
		"""During very early driver init ``_renderer`` may be ``None``. The
		override must not raise; it must fall through to ``super().getScript``.
		"""
		driver = _makeDriver()
		driver._renderer = None

		gesture = MagicMock(name="gesture")
		gesture.normalizedIdentifiers = ["br(dotpad):f1+f3"]

		# Should not raise.
		result = driver.getScript(gesture)
		# We don't assert what super returns here — just that the call
		# completed without referencing the absent renderer.
		self.assertTrue(result is None or callable(result))


if __name__ == "__main__":
	unittest.main()
