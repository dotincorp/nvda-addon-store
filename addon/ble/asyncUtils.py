# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2024-2026 Dot Incorporated

"""Asynchronous utilities to interact with Bleak from NVDA's synchronous codebase.

Bleak is asynchronous, so every call into it has to be scheduled onto an asyncio
event loop running on a background thread. NVDA grew exactly such a loop in 2026.2
(``_asyncioEventLoop``, PR #19816), so this module only decides which one to use:

- **NVDA 2026.2+** -- use NVDA's loop. NVDA owns its lifecycle, so the addon calls
  neither ``initialize()`` nor ``terminate()``.
- **NVDA 2026.1** -- use the bundled backport in ``addon/compat/asyncioEventLoop``.
  The addon owns the lifecycle: it starts the loop and registers ``terminate`` with
  ``atexit``.

**Why resolution is deferred to first use.** Importability of ``_asyncioEventLoop``
is not enough -- NVDA loads addons before it calls ``_asyncioEventLoop.initialize()``,
so during addon import the module exists but its loop thread does not. Deciding at
import time would see a loop that is not running and permanently fall back to the
backport, running a second event loop for the rest of the process. Deciding on first
*use* means NVDA's loop is up by the time we look. Correspondingly, nothing in this
package may schedule coroutines at import time.

**There is deliberately no override to force the backport.** On a version that ships
``_asyncioEventLoop``, NVDA starts that loop unconditionally, so forcing the backport
would leave two loops running and contending over bleak's WinRT backend. That is not
what 2026.1 looks like -- it is a third state that exists nowhere in production, so it
would be a misleading test. The 2026.1 path has to be exercised on a real 2026.1.

Callers use ``runCoroutine`` / ``runCoroutineSync`` and never touch the loop object.
That is the same API NVDA 2026.3's ``hwIo.ble`` uses internally, which keeps the
eventual switch to core's BLE implementation a matter of imports.

When the minimum NVDA version reaches 2026.2, this module collapses to a re-export
of ``_asyncioEventLoop.utils`` and the ``addon/compat/asyncioEventLoop`` package can
be deleted.
"""

from __future__ import annotations

import atexit
import threading
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, Protocol

from logHandler import log

try:
	from ..utils.testing import IS_UNDER_UNITTEST
except ImportError:
	IS_UNDER_UNITTEST = False  # type: ignore


class _LoopUtils(Protocol):
	"""The subset of ``_asyncioEventLoop.utils`` this module dispatches to."""

	def runCoroutine(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

	def runCoroutineSync(self, coro: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any: ...


_utils: _LoopUtils | None = None
_resolverLock = threading.Lock()


def _tryCoreLoop() -> _LoopUtils | None:
	"""Return NVDA's loop utils if NVDA provides a loop and it is running.

	Returns ``None`` when ``_asyncioEventLoop`` is absent (NVDA 2026.1) or present
	but not yet initialised, in which case the caller falls back to the backport.
	"""
	try:
		from _asyncioEventLoop import _state as coreState
		from _asyncioEventLoop import utils as coreUtils
	except ImportError:
		return None
	# Declared but unassigned until initialize() runs, hence getattr rather than access.
	thread = getattr(coreState, "asyncioThread", None)
	if thread is None or not thread.is_alive():
		return None
	return coreUtils


def _startBackport() -> _LoopUtils:
	"""Start the bundled backport loop and register its teardown."""
	if TYPE_CHECKING or IS_UNDER_UNITTEST:
		from ..compat import asyncioEventLoop as backport
		from ..compat.asyncioEventLoop import utils as backportUtils
	else:
		import addonHandler

		addon = addonHandler.getCodeAddon()
		backport = addon.loadModule("compat.asyncioEventLoop")
		backportUtils = addon.loadModule("compat.asyncioEventLoop.utils")

	backport.initialize()
	atexit.register(backport.terminate)
	return backportUtils


def _resolve() -> _LoopUtils:
	"""Pick the loop implementation once, then reuse it.

	Double-checked locking so concurrent first calls converge on one decision; the
	lock is only contended on that first call.
	"""
	global _utils
	if _utils is not None:
		return _utils
	with _resolverLock:
		if _utils is not None:
			return _utils
		core = _tryCoreLoop()
		if core is not None:
			log.debug("asyncio: using NVDA's shared event loop")
			_utils = core
		else:
			log.debug("asyncio: NVDA has no running event loop; starting the bundled backport")
			_utils = _startBackport()
	return _utils


def runCoroutine(coro: Coroutine[Any, Any, Any]) -> Any:
	"""Schedule ``coro`` on the event loop and return its future."""
	return _resolve().runCoroutine(coro)


def runCoroutineSync(coro: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
	"""Schedule ``coro`` on the event loop, block for the result, and return it."""
	return _resolve().runCoroutineSync(coro, timeout)
