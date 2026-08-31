# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for the asyncio event loop selector in ``addon.ble.asyncUtils``.

The selector picks between NVDA's shared loop and the bundled backport on first
use, so the cases that matter are:

- NVDA's loop is importable *and running* (NVDA 2026.2+): core's utils are used,
  the backport is never started, and no ``atexit`` handler is registered -- NVDA
  owns the lifecycle.
- ``_asyncioEventLoop`` is missing (NVDA 2026.1): the backport is started once and
  its ``terminate`` is registered with ``atexit``.
- ``_asyncioEventLoop`` is importable but *not yet initialised*: this is what the
  addon sees during NVDA startup, since addons load before
  ``_asyncioEventLoop.initialize()`` runs. It must not be mistaken for a usable
  loop.

Resolution is cached, so each test resets the module-level cache first.

A functional test additionally drives a real coroutine through the backport, so a
backport that imports but cannot run anything would still fail.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types
import unittest
from unittest.mock import MagicMock, patch

from addon.ble import asyncUtils


def _makeCoreModules(*, threadAlive: bool | None) -> dict[str, types.ModuleType]:
	"""Build stub ``_asyncioEventLoop`` modules.

	``threadAlive=None`` models the pre-``initialize()`` state, where ``_state``
	carries only an annotation for ``asyncioThread`` and no actual attribute.
	"""
	state = types.ModuleType("_asyncioEventLoop._state")
	if threadAlive is not None:
		thread = MagicMock(spec=threading.Thread)
		thread.is_alive.return_value = threadAlive
		state.asyncioThread = thread  # type: ignore[attr-defined]
	utils = types.ModuleType("_asyncioEventLoop.utils")
	utils.runCoroutine = MagicMock(name="core.runCoroutine")  # type: ignore[attr-defined]
	utils.runCoroutineSync = MagicMock(name="core.runCoroutineSync")  # type: ignore[attr-defined]
	pkg = types.ModuleType("_asyncioEventLoop")
	pkg._state = state  # type: ignore[attr-defined]
	pkg.utils = utils  # type: ignore[attr-defined]
	return {
		"_asyncioEventLoop": pkg,
		"_asyncioEventLoop._state": state,
		"_asyncioEventLoop.utils": utils,
	}


class SelectorTestCase(unittest.TestCase):
	"""Reset the cached resolution so each test exercises the decision itself."""

	def setUp(self) -> None:
		asyncUtils._utils = None
		self.addCleanup(setattr, asyncUtils, "_utils", None)


class TestSelectorUsesCoreLoop(SelectorTestCase):
	"""NVDA 2026.2+ provides a running loop, so the addon must defer to it."""

	def test_running_core_loop_is_used_and_backport_untouched(self) -> None:
		modules = _makeCoreModules(threadAlive=True)
		with (
			patch.dict(sys.modules, modules),
			patch("addon.compat.asyncioEventLoop.initialize") as backportInit,
			patch("atexit.register") as atexitRegister,
		):
			resolved = asyncUtils._resolve()

			self.assertIs(resolved, modules["_asyncioEventLoop.utils"])
			backportInit.assert_not_called()
			atexitRegister.assert_not_called()

	def test_runCoroutine_dispatches_to_core(self) -> None:
		modules = _makeCoreModules(threadAlive=True)
		coreUtils = modules["_asyncioEventLoop.utils"]
		coro = MagicMock(name="coro")
		with patch.dict(sys.modules, modules):
			asyncUtils.runCoroutine(coro)
			asyncUtils.runCoroutineSync(coro, timeout=3)

		coreUtils.runCoroutine.assert_called_once_with(coro)  # type: ignore[attr-defined]
		coreUtils.runCoroutineSync.assert_called_once_with(coro, 3)  # type: ignore[attr-defined]


class TestSelectorFallsBackToBackport(SelectorTestCase):
	"""Without a usable NVDA loop the addon starts and owns the backport."""

	def _assertBackportSelected(self, modules: dict[str, object]) -> None:
		with (
			patch.dict(sys.modules, modules),
			patch("addon.compat.asyncioEventLoop.initialize") as backportInit,
			patch("atexit.register") as atexitRegister,
		):
			asyncUtils._resolve()

			backportInit.assert_called_once_with()
			atexitRegister.assert_called_once()
			from addon.compat.asyncioEventLoop import terminate

			self.assertIs(atexitRegister.call_args.args[0], terminate)

	def test_missing_core_module_selects_backport(self) -> None:
		# Mapping a name to None makes `import name` raise ImportError, which is the
		# condition on NVDA 2026.1.
		self._assertBackportSelected({"_asyncioEventLoop": None})

	def test_uninitialised_core_loop_selects_backport(self) -> None:
		"""Importable but not started -- what addon load time looks like on 2026.2+."""
		self._assertBackportSelected(_makeCoreModules(threadAlive=None))

	def test_dead_core_loop_thread_selects_backport(self) -> None:
		self._assertBackportSelected(_makeCoreModules(threadAlive=False))

	def test_backport_runs_a_coroutine(self) -> None:
		"""The backport must actually work, not merely import."""
		from addon.compat import asyncioEventLoop

		asyncioEventLoop.initialize()
		try:
			from addon.compat.asyncioEventLoop.utils import runCoroutine, runCoroutineSync

			async def answer() -> int:
				await asyncio.sleep(0)
				return 42

			self.assertEqual(42, runCoroutineSync(answer(), timeout=5))
			self.assertEqual(42, runCoroutine(answer()).result(5))
		finally:
			asyncioEventLoop.terminate()


class TestResolutionIsCached(SelectorTestCase):
	"""The decision is made once; later calls must not re-probe."""

	def test_second_resolve_reuses_first_result(self) -> None:
		modules = _makeCoreModules(threadAlive=True)
		with patch.dict(sys.modules, modules):
			first = asyncUtils._resolve()
		# With the stubs gone, a re-probe would fall through to the backport.
		with patch("addon.compat.asyncioEventLoop.initialize") as backportInit:
			second = asyncUtils._resolve()

		self.assertIs(first, second)
		backportInit.assert_not_called()
