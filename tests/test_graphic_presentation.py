# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for ``GraphicPresentation`` lifecycle and render-path routing."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from addon.extension_points.review_tracking import TriggerReason


def _makeRenderableLocation(left=0, top=0, width=100, height=50):
	location = MagicMock(name="location")
	location.left = left
	location.top = top
	location.width = width
	location.height = height
	return location


def _makeDriverMock(libraryReady: bool = True):
	driver = MagicMock(name="driver")
	driver._libraryReady = libraryReady
	driver._libraryWorker = MagicMock(name="worker") if libraryReady else None
	driver._tda = MagicMock(name="tda") if libraryReady else None
	return driver


def _makePresentation(obj=None, driver=None):
	"""Build a GraphicPresentation with a mocked _getActiveDriver."""
	from addon.presentations.graphic import GraphicPresentation

	if obj is None:
		obj = MagicMock(name="navObj")
		obj.location = _makeRenderableLocation()
	display = MagicMock(name="display")
	presentation = GraphicPresentation(obj=obj, display=display)
	if driver is not None:
		presentation._getActiveDriver = MagicMock(return_value=driver)
	return presentation


class TestIsStillValid(unittest.TestCase):
	"""``isStillValid()`` mirrors NVDA navigator-object identity."""

	def test_returnsTrueWhenNavObjUnchanged(self) -> None:
		obj = MagicMock(name="navObj")
		presentation = _makePresentation(obj=obj)
		with (
			patch("api.getNavigatorObject", return_value=obj, create=True),
			patch("api.getFocusObject", return_value=MagicMock(name="focus"), create=True),
		):
			self.assertTrue(presentation.isStillValid())

	def test_returnsFalseWhenNavObjChanged(self) -> None:
		original = MagicMock(name="navObj-original")
		different = MagicMock(name="navObj-different")
		presentation = _makePresentation(obj=original)
		with (
			patch("api.getNavigatorObject", return_value=different, create=True),
			patch("api.getFocusObject", return_value=MagicMock(name="focus"), create=True),
		):
			self.assertFalse(presentation.isStillValid())

	def test_returnsFalseOnException(self) -> None:
		obj = MagicMock(name="navObj")
		presentation = _makePresentation(obj=obj)
		with patch("api.getNavigatorObject", side_effect=RuntimeError("synthetic"), create=True):
			self.assertFalse(presentation.isStillValid())

	def test_returnsFalseOnCaretMoveWhenLibraryDriven(self) -> None:
		"""Library-driven path (nav is focus): caretMove invalidates the presentation."""
		obj = MagicMock(name="navObj")
		presentation = _makePresentation(obj=obj)
		with (
			patch("api.getNavigatorObject", return_value=obj, create=True),
			patch("api.getFocusObject", return_value=obj, create=True),
		):
			self.assertFalse(presentation.isStillValid(triggerReason=TriggerReason.CARET_MOVE))

	def test_returnsTrueOnCaretMoveWhenNvdaDriven(self) -> None:
		"""NVDA-driven path (nav is not focus): caretMove does not force invalidation."""
		obj = MagicMock(name="navObj")
		focus = MagicMock(name="focus")
		presentation = _makePresentation(obj=obj)
		with (
			patch("api.getNavigatorObject", return_value=obj, create=True),
			patch("api.getFocusObject", return_value=focus, create=True),
		):
			self.assertTrue(presentation.isStillValid(triggerReason=TriggerReason.CARET_MOVE))

	def test_returnsTrueOnOtherTriggerReasonWhenLibraryDriven(self) -> None:
		"""Non-caretMove triggers do not force invalidation even in library-driven path."""
		obj = MagicMock(name="navObj")
		presentation = _makePresentation(obj=obj)
		with (
			patch("api.getNavigatorObject", return_value=obj, create=True),
			patch("api.getFocusObject", return_value=obj, create=True),
		):
			self.assertTrue(presentation.isStillValid(triggerReason=TriggerReason.REVIEW_MOVE))


class TestUseNvdaDrivenRender(unittest.TestCase):
	"""``_useNvdaDrivenRender()`` routing predicate."""

	def test_returnsFalseWhenNavigatorIsFocus(self) -> None:
		obj = MagicMock(name="obj")
		presentation = _makePresentation(obj=obj)
		with (
			patch("api.getNavigatorObject", return_value=obj, create=True),
			patch("api.getFocusObject", return_value=obj, create=True),
		):
			self.assertFalse(presentation._useNvdaDrivenRender())

	def test_returnsTrueWhenNavigatorDiffersFromFocus(self) -> None:
		nav = MagicMock(name="nav")
		focus = MagicMock(name="focus")
		presentation = _makePresentation(obj=nav)
		with (
			patch("api.getNavigatorObject", return_value=nav, create=True),
			patch("api.getFocusObject", return_value=focus, create=True),
		):
			self.assertTrue(presentation._useNvdaDrivenRender())

	def test_returnsTrueOnException(self) -> None:
		presentation = _makePresentation()
		with patch("api.getNavigatorObject", side_effect=RuntimeError("synthetic"), create=True):
			self.assertTrue(presentation._useNvdaDrivenRender())


class TestRenderNvdaDriven(unittest.TestCase):
	"""``render()`` NVDA-driven path: drawScreenRegion + show."""

	def _makeNvdaDrivenPresentation(self, obj=None, driver=None):
		"""Presentation with _useNvdaDrivenRender forced True."""
		p = _makePresentation(obj=obj, driver=driver)
		p._useNvdaDrivenRender = MagicMock(return_value=True)
		return p

	def test_submitsDrawAndShowOnActiveDriver(self) -> None:
		driver = _makeDriverMock(libraryReady=True)
		obj = MagicMock(name="navObj")
		obj.location = _makeRenderableLocation(left=10, top=20, width=300, height=40)
		presentation = self._makeNvdaDrivenPresentation(obj=obj, driver=driver)

		result = presentation.render(MagicMock())

		self.assertIsNone(result)
		driver._libraryWorker.submitAndReport.assert_called_once()
		callArgs = driver._libraryWorker.submitAndReport.call_args
		self.assertIs(callArgs.args[0], driver._tda.drawScreenRegion)
		self.assertEqual(callArgs.args[1:5], (10, 20, 300, 40))

	def test_executeOperationNotCalledOnNvdaDrivenPath(self) -> None:
		driver = _makeDriverMock(libraryReady=True)
		obj = MagicMock(name="navObj")
		obj.location = _makeRenderableLocation()
		presentation = self._makeNvdaDrivenPresentation(obj=obj, driver=driver)

		presentation.render(MagicMock())

		callArgs = driver._libraryWorker.submitAndReport.call_args
		self.assertIs(callArgs.args[0], driver._tda.drawScreenRegion)
		self.assertIsNot(callArgs.args[0], driver._tda.executeOperation)

	def test_noOpWhenLocationInvalid(self) -> None:
		driver = _makeDriverMock(libraryReady=True)
		obj = MagicMock(name="navObj")
		obj.location = _makeRenderableLocation(width=0, height=10)
		presentation = self._makeNvdaDrivenPresentation(obj=obj, driver=driver)

		result = presentation.render(MagicMock())

		self.assertIsNone(result)
		driver._libraryWorker.submitAndReport.assert_not_called()

	def test_noOpWhenLibraryNotReady(self) -> None:
		driver = _makeDriverMock(libraryReady=False)
		presentation = self._makeNvdaDrivenPresentation(driver=driver)

		result = presentation.render(MagicMock())

		self.assertIsNone(result)
		self.assertIsNone(driver._libraryWorker)

	def test_noOpWhenNoDriverAttached(self) -> None:
		presentation = self._makeNvdaDrivenPresentation(driver=None)
		presentation._getActiveDriver = MagicMock(return_value=None)

		result = presentation.render(MagicMock())

		self.assertIsNone(result)


class TestRenderLibraryDriven(unittest.TestCase):
	"""``render()`` library-driven path: executeOperation(SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE)."""

	def _makeLibraryDrivenPresentation(self, obj=None, driver=None):
		"""Presentation with _useNvdaDrivenRender forced False."""
		p = _makePresentation(obj=obj, driver=driver)
		p._useNvdaDrivenRender = MagicMock(return_value=False)
		return p

	def test_submitsExecuteOperationShowTactileImage(self) -> None:
		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		driver = _makeDriverMock(libraryReady=True)
		presentation = self._makeLibraryDrivenPresentation(driver=driver)

		result = presentation.render(MagicMock())

		self.assertIsNone(result)
		driver._libraryWorker.submitAndReport.assert_called_once()
		callArgs = driver._libraryWorker.submitAndReport.call_args
		self.assertIs(callArgs.args[0], driver._tda.executeOperation)
		self.assertEqual(callArgs.args[1], BrailleInputOperation.SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE)

	def test_drawScreenRegionNotCalledOnLibraryDrivenPath(self) -> None:
		driver = _makeDriverMock(libraryReady=True)
		presentation = self._makeLibraryDrivenPresentation(driver=driver)

		presentation.render(MagicMock())

		callArgs = driver._libraryWorker.submitAndReport.call_args
		self.assertIsNot(callArgs.args[0], driver._tda.drawScreenRegion)

	def test_noLocationGuardOnLibraryDrivenPath(self) -> None:
		"""Library-driven path proceeds even when the object has no location."""
		from addon.tactileDisplayAPI.comInterface import BrailleInputOperation

		driver = _makeDriverMock(libraryReady=True)
		obj = MagicMock(name="navObj")
		obj.location = None
		presentation = self._makeLibraryDrivenPresentation(obj=obj, driver=driver)

		presentation.render(MagicMock())

		driver._libraryWorker.submitAndReport.assert_called_once()
		callArgs = driver._libraryWorker.submitAndReport.call_args
		self.assertIs(callArgs.args[0], driver._tda.executeOperation)
		self.assertEqual(callArgs.args[1], BrailleInputOperation.SHOW_OBJECT_AT_CURSOR_AS_TACTILE_IMAGE)

	def test_noOpWhenLibraryNotReady(self) -> None:
		driver = _makeDriverMock(libraryReady=False)
		presentation = self._makeLibraryDrivenPresentation(driver=driver)

		result = presentation.render(MagicMock())

		self.assertIsNone(result)
		self.assertIsNone(driver._libraryWorker)

	def test_noOpWhenNoDriverAttached(self) -> None:
		presentation = self._makeLibraryDrivenPresentation(driver=None)
		presentation._getActiveDriver = MagicMock(return_value=None)

		result = presentation.render(MagicMock())

		self.assertIsNone(result)


class TestTerminate(unittest.TestCase):
	"""``terminate()`` submits Clear() regardless of render path."""

	def test_submitsClear(self) -> None:
		driver = _makeDriverMock(libraryReady=True)
		presentation = _makePresentation(driver=driver)

		presentation.terminate()

		driver._libraryWorker.submit.assert_called_once_with(driver._tda.clear)

	def test_noOpWhenLibraryNotReady(self) -> None:
		driver = _makeDriverMock(libraryReady=False)
		presentation = _makePresentation(driver=driver)

		presentation.terminate()


if __name__ == "__main__":
	unittest.main()
