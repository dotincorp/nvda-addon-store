# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Per-session daemon worker that owns the TactileDisplayAPI wrapper.

All wrapper calls (``connect``, ``drawScreenRegion``, ``show``, ``disconnect``,
``close``) MUST execute on this thread, never on the main thread. This isolates
NVDA's wx event loop from any blocking library behaviour — the library can hang
for arbitrarily long without tripping NVDA's freeze watchdog.

Threading-ownership model:

- The worker thread initialises COM apartment-threaded (**STA**) at start, owns
  the wrapper instance, processes a FIFO queue of work items interleaved with a
  Win32 message pump, and releases COM at clean shutdown.

  Why STA + pump (not MTA): the library is its own UI Automation *client* —
  ``RegisterEvents(True)`` makes it subscribe to UIA events and render braille
  autonomously via the ``TactileDisplayUpdated`` callback. UIA delivers those
  event callbacks into the registering apartment through the **message pump**, so
  an MTA worker (no pump) receives no events and library-driven braille goes
  dark. STA + pump is therefore required for the autonomous-braille feature.

  The hazard STA + pump created historically: a long *synchronous* library call
  (``ExecuteOperation``) blocks the thread, so the pump stops; if UIA events are
  live at that moment they pile up unserviced and the library's internal
  queue/heap state corrupts — a ``STATUS_HEAP_CORRUPTION`` fail-fast was observed
  in a crash dump. The mitigation lives in the *caller*: events are enabled only
  for library-driven-braille steady state and are turned OFF around the blocking
  bootstrap and around graphics/explicit ``ExecuteOperation`` calls, so a blocking
  call never runs while events compete for the starved pump. (An MTA experiment
  confirmed the crash is the events-while-blocking collision: with events not
  delivered, ``ExecuteOperation`` ran fine — but MTA is not a usable fix, since
  no events means no autonomous braille. Splitting the library across two
  instances — one events-only, one calls-only — was also tried and reproduces
  the same crash: both instances share the library's internal state.) See the
  driver's ``enableLibraryUiaEvents`` / ``disableLibraryUiaEvents`` and
  ``presentations.braille``.

- The main thread submits work items via ``submit`` (returns a Future),
  ``submitAndAwait`` (synchronous helper for non-main-thread callers — blocks
  the calling thread on ``Future.result``), or ``submitAndReport`` (the
  main-thread-friendly variant that returns immediately and dispatches the
  outcome to the wx main loop via ``wx.CallAfter``). After ``start()``
  succeeds, the main thread MUST NOT touch ``self.tda`` directly — that would
  call into the wrapper from the wrong COM apartment.
- The worker thread is daemon — on a hard process exit it dies with NVDA.
- On clean stop, ``stop()`` enqueues a sentinel and returns immediately. It
  does NOT join the thread; callers that need to know "the worker is done"
  must observe via the readiness signals on submitted futures.
- The queue is the only shared mutable state; ``queue.Queue`` provides its own
  internal locking. ``threading.Event`` (``_readyEvent``) is similarly
  thread-safe for the start/ready handshake. Lightweight diagnostics state
  (the in-flight operation + completed-op count) is guarded by ``_stateLock``.

Why ``submitAndReport`` exists: NVDA's main thread runs the wx event loop and
its freeze-watchdog measures whether main-loop iterations complete within
~500 ms. ``submitAndAwait`` blocks the calling thread on ``Future.result``,
which freezes wx if called from main. ``submitAndReport`` schedules the result
delivery via ``wx.CallAfter`` so the gesture handler returns immediately and
the main loop continues servicing speech / navigation / watchdog heartbeats
while the worker runs the library call.

Diagnostics: the worker records which operation it is currently running and how
long it has been running, plus a completed-op counter. On a per-call timeout the
caller logs (via :meth:`LibraryWorker._logTimeout`) whether the worker is still
stuck on that exact operation (a likely hang) or has moved on (transient
slowness). :meth:`LibraryWorker.captureDiagnostics` dumps the worker thread's
live Python stack so a hang is diagnosable from the NVDA log alone.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import traceback
from concurrent.futures import Future
from queue import Empty as QueueEmpty
from queue import Queue
from typing import Any, Callable, TypeVar

from logHandler import log

from .wrapper import TactileDisplayAPI

T = TypeVar("T")

# Queue item shape: either a sentinel (None) requesting shutdown, or a
# (callable, args, kwargs, future) tuple to be invoked on the worker thread.
_QueueItem = tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any], "Future[Any]"] | None

# COINIT_APARTMENTTHREADED — STA. The library is a UIA client whose event
# callbacks are delivered via the thread message pump, so the worker must be an
# STA that pumps. See the module docstring.
_COINIT_APARTMENTTHREADED: int = 0x2

# Worker idle-pump cadence. While the queue is empty, the worker drains the
# Win32 message queue every PUMP_INTERVAL_S seconds. Smaller = snappier
# delivery of library-fired events (UIA events, button presses, device-removal
# notifications); larger = lower CPU. 50 ms is well below human-perceptible
# input latency for braille hardware.
_PUMP_INTERVAL_S: float = 0.05

# Defensive cap on per-call message drains. A real Win32 message queue holds
# at most a few thousand pending messages even under heavy load; capping
# orders of magnitude above that catches a stuck pump (e.g. a misconfigured
# mock returning truthy in tests) without affecting realistic production traffic.
_PUMP_MAX_ITERATIONS_PER_CALL: int = 100_000

# PeekMessage flag: remove the message from the queue (rather than just
# inspecting it).
_PM_REMOVE: int = 0x0001


class _Win32Msg(ctypes.Structure):
	"""ctypes layout for the Win32 MSG struct used by PeekMessage / DispatchMessage."""

	_fields_ = (
		("hWnd", ctypes.c_void_p),
		("message", ctypes.c_uint),
		("wParam", ctypes.c_void_p),
		("lParam", ctypes.c_void_p),
		("time", ctypes.c_uint),
		("pt_x", ctypes.c_long),
		("pt_y", ctypes.c_long),
	)


#: Flag for SetThreadPreferredUILanguages: use BCP-47 locale names ("nl-NL").
_MUI_LANGUAGE_NAME: int = 0x8


def _setWorkerThreadLocale() -> None:
	"""Match the worker thread's locale to NVDA's currently-configured language.

	Why this exists: Windows threads do NOT inherit the parent thread's
	locale — new threads start with the user-default locale from the registry.
	NVDA's main thread calls ``SetThreadLocale`` (via ``languageHandler``)
	at startup, but that's per-thread; our worker is a separate thread.

	The TactileDisplayAPI library reads its locale at ``CoCreateInstance``
	time and uses it to pick the ``<libLcid>/TactileDisplayAPI.ini`` file.
	Without this call, the library always lands on ``enu/`` regardless of
	NVDA's UI language.

	Best-effort: any failure here downgrades to a debug log; the library
	still works, just falls back to the user-default locale's ini.
	"""
	try:
		import languageHandler  # type: ignore[reportMissingImports]
	except ImportError:
		log.debug("languageHandler unavailable; worker thread keeps user-default locale")
		return
	lang = languageHandler.getLanguage()
	if not lang or lang == "Windows":
		# NVDA itself is using the Windows default — leave the thread alone.
		return
	lcid = languageHandler.localeNameToWindowsLCID(lang)
	if lcid == 0:
		log.debugWarning(
			"NVDA language %r has no Windows LCID; worker thread keeps user-default locale",
			lang,
		)
		return
	kernel32 = ctypes.windll.kernel32
	if kernel32.SetThreadLocale(lcid) == 0:
		log.debugWarning("SetThreadLocale(%s) failed on worker thread", lcid)
	else:
		log.debug("Worker thread Win32 locale set to %r (LCID=%s)", lang, lcid)
	# Some libraries query GetThreadUILanguage / GetThreadPreferredUILanguages
	# rather than GetThreadLocale; set both for the widest compatibility.
	bcp47 = lang.replace("_", "-")
	# Buffer must be a double-null-terminated wide string ("nl-NL\0\0" — the
	# unicode_buffer constructor appends one null, we add a second explicitly).
	buf = ctypes.create_unicode_buffer(bcp47 + "\0")
	count = ctypes.c_ulong(0)
	if kernel32.SetThreadPreferredUILanguages(_MUI_LANGUAGE_NAME, buf, ctypes.byref(count)) == 0:
		log.debug("SetThreadPreferredUILanguages(%r) failed on worker thread", bcp47)
	else:
		log.debug("Worker thread preferred UI language set to %r", bcp47)


def _pumpThreadMessages() -> None:
	"""Drain pending Win32 messages on the calling thread's message queue.

	STA COM apartments rely on the message pump to deliver cross-apartment
	callbacks — including the library's UIA event callbacks — and to drain any
	hidden window the library uses for hardware-event notifications (button
	presses, device-removal, etc.). Without this, those messages queue
	indefinitely and the library's internal state can corrupt.

	Non-blocking: PeekMessage with PM_REMOVE returns immediately if the queue
	is empty.
	"""
	user32 = ctypes.windll.user32
	msg = _Win32Msg()
	# Drain everything pending in one go. Loop returns False when empty. The
	# iteration cap bounds the worst case if a test leaks a mock that returns
	# truthy for every PeekMessage.
	for _ in range(_PUMP_MAX_ITERATIONS_PER_CALL):
		if not user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, _PM_REMOVE):
			return
		user32.TranslateMessage(ctypes.byref(msg))
		user32.DispatchMessageW(ctypes.byref(msg))
	log.debugWarning(
		"_pumpThreadMessages: drained %s messages without hitting an empty queue; aborting this pump iteration",
		_PUMP_MAX_ITERATIONS_PER_CALL,
	)


def _dispatchToMain(fn: Callable[..., None], *args: Any) -> None:
	"""Post a callable to the wx main loop; fall back to direct invocation.

	Used by ``LibraryWorker.submitAndReport`` to hand a future's outcome back
	to the main thread without blocking. In NVDA at runtime, ``wx.CallAfter``
	queues the call onto the wx event loop. In unit tests there is no wx
	app, so we invoke the callable directly on the calling thread (worker /
	timer); test code is structured to handle that.
	"""
	try:
		import wx

		# wx.CallAfter raises if there is no live wx.App (e.g. in tests).
		# Catching that and falling through to direct invocation lets the
		# helper double as a unit-test entry point.
		wx.CallAfter(fn, *args)
		return
	except Exception:
		pass
	fn(*args)


class LibraryWorker:
	"""Daemon worker owning the TactileDisplayAPI wrapper.

	Lifecycle::

	    worker = LibraryWorker()
	    worker.start()                                    # blocks until ready
	    result = worker.submitAndAwait(worker.tda.connect, 1, timeout=2.0)
	    # ... more submits ...
	    worker.stop()                                     # non-blocking
	"""

	def __init__(self) -> None:
		self._queue: Queue[_QueueItem] = Queue()
		self._readyEvent: threading.Event = threading.Event()
		self._startError: BaseException | None = None
		self._thread: threading.Thread | None = None
		# The wrapper instance — set inside ``_run`` after CoInitializeEx +
		# TactileDisplayAPI()._ensureInitialized() succeed. Read by callers
		# ONLY after ``start()`` returns successfully; all subsequent access
		# goes through ``submit`` so the call runs on the worker's STA
		# apartment.
		self.tda: TactileDisplayAPI | None = None

		# --- Diagnostics (all guarded by _stateLock) ---
		self._stateLock = threading.Lock()
		# Name of the operation the worker thread is currently executing, and
		# the monotonic timestamp it started. Set just before the call, cleared
		# just after. While the worker is stuck inside a call the ``finally``
		# never runs, so these stay pinned — that is exactly the signal the
		# timeout diagnostics read.
		self._currentOp: str | None = None
		self._currentOpStartMonotonic: float | None = None
		# Monotonically increasing count of completed (returned or raised)
		# operations. Lets a caller tell "the worker is draining other work"
		# from "the worker has not made any progress since I submitted".
		self._completedOpCount: int = 0
		# Whether the library's autonomous UIA/MSAA subscription is currently
		# on (``RegisterEvents(True/False)``). Surfaced in diagnostics because
		# a blocking call while this is on is the heap-corruption hazard.
		self._uiaEventsEnabled: bool = False

	def start(self, *, startTimeoutS: float = 5.0) -> None:
		"""Spawn the worker thread; block until the wrapper is ready or init fails.

		On success, ``self.tda`` is the live wrapper instance and subsequent
		``submit``/``submitAndAwait`` calls run on the worker thread.

		Failure modes (all raise on the calling thread):

		- ``OSError`` / ``WindowsError``: ``CoInitializeEx`` returned a failure HRESULT.
		- ``RuntimeError`` (or whatever ``createTactileDisplayApi`` raises): the COM
		  object couldn't be created (DLL load failed, IID not exposed, etc.).
		- ``TimeoutError``: ``startTimeoutS`` elapsed without success or failure —
		  likely means COM init itself is hung. The worker thread is left to
		  eventually die with the process.
		- Any other exception raised inside ``_run`` before readiness is propagated.
		"""
		self._thread = threading.Thread(
			target=self._run,
			name="DotPadLibraryWorker",
			daemon=True,
		)
		self._thread.start()
		if not self._readyEvent.wait(timeout=startTimeoutS):
			raise TimeoutError(
				f"LibraryWorker did not become ready within {startTimeoutS:.1f}s; "
				"likely a hung COM init. Daemon thread leaked.",
			)
		if self._startError is not None:
			raise self._startError
		log.debug("Library worker started (thread=%s)", self._thread.name)

	def submit(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> "Future[T]":
		"""Enqueue a callable; return its Future immediately.

		The callable runs on the worker thread in FIFO submission order. Its
		return value populates ``future.set_result(...)``; any raised
		exception populates ``future.set_exception(...)``.

		Pre-condition: ``start()`` succeeded. (We do not guard against submits
		before start or after stop — callers are expected to follow the lifecycle.)
		"""
		future: "Future[T]" = Future()
		self._queue.put((fn, args, kwargs, future))
		return future

	def submitAndAwait(
		self,
		fn: Callable[..., T],
		*args: Any,
		timeout: float,
		**kwargs: Any,
	) -> T:
		"""Submit + await with bounded timeout.

		Raises ``concurrent.futures.TimeoutError`` if the worker doesn't
		complete the call within ``timeout`` seconds — caller should treat
		this as a library hang and fall through to recovery. The worker thread
		is NOT cancelled; it keeps running the callable until it finishes (or
		the daemon is reaped on process exit).

		Re-raises any exception the callable raised.
		"""
		future = self.submit(fn, *args, **kwargs)
		try:
			return future.result(timeout=timeout)
		except TimeoutError:
			# Both ``concurrent.futures.TimeoutError`` and the builtin
			# ``TimeoutError`` are aliased to the same class on Python 3.11+;
			# log (with worker context) + re-raise.
			self._logTimeout(getattr(fn, "__name__", repr(fn)), timeout)
			raise

	def submitAndReport(
		self,
		fn: Callable[..., T],
		*args: Any,
		timeout: float,
		onSuccess: Callable[[T], None],
		onFailure: Callable[[BaseException], None],
		**kwargs: Any,
	) -> None:
		"""Submit + race against a per-call timeout; dispatch the outcome to
		the main thread asynchronously.

		Returns immediately. Exactly one of ``onSuccess(result)`` or
		``onFailure(exception)`` will be invoked — on the main thread when wx
		is available (production), or directly when wx is not (tests). Mutual
		exclusion between completion and timeout uses a single lock + flag:
		whichever fires first wins; the loser is a no-op. The worker thread
		is NOT cancelled on timeout — it keeps running the callable until it
		finishes (or the daemon is reaped on process exit).

		``onFailure`` receives ``concurrent.futures.TimeoutError`` on timeout
		and whatever exception the callable raised otherwise.

		Pre-condition: ``start()`` succeeded. Same fire-and-forget contract
		as ``submit``; we don't guard against post-stop submissions.
		"""
		methodName = getattr(fn, "__name__", repr(fn))
		settledLock = threading.Lock()
		# Single-element list so the closures below can mutate without
		# triggering UnboundLocalError on a plain assignment.
		settled: list[bool] = [False]

		def _trySettle() -> bool:
			with settledLock:
				if settled[0]:
					return False
				settled[0] = True
				return True

		future = self.submit(fn, *args, **kwargs)

		def _onDone(f: "Future[T]") -> None:
			if not _trySettle():
				return
			try:
				result = f.result()
			except BaseException as e:
				_dispatchToMain(onFailure, e)
				return
			_dispatchToMain(onSuccess, result)

		def _onTimeout() -> None:
			if not _trySettle():
				return
			from concurrent.futures import TimeoutError as FutureTimeoutError

			self._logTimeout(methodName, timeout)
			_dispatchToMain(onFailure, FutureTimeoutError(f"{methodName} timeout"))

		future.add_done_callback(_onDone)
		timer = threading.Timer(timeout, _onTimeout)
		timer.daemon = True
		timer.start()

	def noteUiaEventsEnabled(self) -> None:
		"""Record that the library's autonomous UIA subscription is now on.

		Called by the driver after ``RegisterEvents(True)`` returns. Surfaced
		in :meth:`captureDiagnostics`; a blocking call while this is on is the
		heap-corruption hazard the caller is responsible for avoiding.
		"""
		with self._stateLock:
			self._uiaEventsEnabled = True

	def noteUiaEventsDisabled(self) -> None:
		"""Record that the library's autonomous UIA subscription is now off.

		Called by the driver after ``RegisterEvents(False)`` returns.
		"""
		with self._stateLock:
			self._uiaEventsEnabled = False

	def captureDiagnostics(self) -> str:
		"""Build a one-shot snapshot of the worker's state for the log.

		Reports the current operation and how long it has run, the completed-op
		count, the queue depth, whether the library's UIA subscription is on,
		and — crucially — the worker thread's live Python stack. The stack is
		what makes a hang conclusive from the NVDA log alone: it shows
		``_run -> <op> -> ...`` (e.g. ``executeOperation`` calling into the
		library) without needing py-spy or a minidump.
		"""
		with self._stateLock:
			op = self._currentOp
			started = self._currentOpStartMonotonic
			completed = self._completedOpCount
			uiaEnabled = self._uiaEventsEnabled
		elapsed = f"{time.monotonic() - started:.1f}s" if started is not None else "n/a"
		lines = [
			f"DotPad worker diagnostics: currentOp={op!r} elapsed={elapsed} "
			f"completedOps={completed} queueDepth={self._queue.qsize()} "
			f"uiaEventsEnabled={uiaEnabled}",
		]
		thread = self._thread
		# sys._current_frames() is the documented way to grab another thread's
		# live frame; the leading underscore is historical, not "don't touch".
		currentFrames = sys._current_frames()  # pyright: ignore[reportPrivateUsage]
		frame = currentFrames.get(thread.ident) if thread is not None and thread.ident else None
		if frame is not None:
			lines.append("DotPad worker thread stack (innermost last):")
			lines.append("".join(traceback.format_stack(frame)).rstrip())
		else:
			lines.append("DotPad worker thread stack unavailable (thread not running?)")
		return "\n".join(lines)

	def _logTimeout(self, methodName: str, timeout: float) -> None:
		"""Log a per-call soft timeout with worker context, split by severity.

		Distinguishes "this op is still the current one and has overrun"
		(stuck — the likely-hang signal, the thing that preceded the crash) from
		"the worker has moved on / is draining a backlog" (transient slowness):

		- Stuck → ``WARNING`` (visible at NVDA's default log level so it is
		  captured even right before a crash), plus the worker-thread stack at
		  ``DEBUG`` (so raising NVDA's log level to debug yields the full stack —
		  no bespoke flag needed).
		- Progressing → ``debugWarning`` (expected, recovered slowness; demoted
		  off the default log level so it stops being noise).
		"""
		with self._stateLock:
			currentOp = self._currentOp
			started = self._currentOpStartMonotonic
		stuckOnThisOp = currentOp == methodName and started is not None
		if stuckOnThisOp:
			elapsed = time.monotonic() - started  # type: ignore[operator]
			log.warning(
				"Library %s timed out after %.0fms and is STILL the worker's current "
				"operation (%.1fs and counting) — treating as failure.",
				methodName,
				timeout * 1000,
				elapsed,
			)
			log.debug(self.captureDiagnostics())
		else:
			log.debugWarning(
				"Library %s timed out after %.0fms; treating as failure (worker is progressing: currentOp=%r)",
				methodName,
				timeout * 1000,
				currentOp,
			)

	def stop(self) -> None:
		"""Enqueue the sentinel; return immediately.

		Does NOT join the thread. The worker drains any remaining queued
		callables in FIFO order before observing the sentinel, performs a
		best-effort wrapper teardown, calls ``CoUninitialize``, and exits.

		Idempotent — calling ``stop()`` twice is harmless; the second sentinel
		is enqueued but never observed.
		"""
		log.debug("Library worker stop requested")
		self._queue.put(None)

	def _run(self) -> None:
		"""Worker thread main loop. STA COM init → wrapper construction →
		message-pumped queue drain → best-effort teardown → CoUninitialize →
		exit.

		The queue drain interleaves Win32 message pumping. STA COM apartments
		require a pump to deliver cross-apartment callbacks — including the
		library's UIA event callbacks — and to drain the library's internal
		hidden-window message queue.
		"""
		# 1. Initialise COM (STA), match NVDA's UI language on this thread, and
		# construct the wrapper. The locale call must precede wrapper
		# construction because the library reads its locale-specific ini at
		# CoCreateInstance (inside _ensureInitialized). Note: TactileDisplayAPI
		# v1.16 uses registry-backed Win32 calls (GetUserDefaultUILanguage)
		# for locale detection and does NOT honour the thread-level setting we
		# install here. The SetThreadLocale call is kept on the assumption that
		# a future library version will respect it; today, non-English users
		# only get NVDA-translated abbreviations when their Windows display
		# language matches one of our generated locale directories.
		try:
			ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
			_setWorkerThreadLocale()
			self.tda = TactileDisplayAPI()
			self.tda._ensureInitialized()  # pyright: ignore[reportPrivateUsage]
		except BaseException as e:
			self._startError = e
			self._readyEvent.set()
			# CoUninitialize defensively — CoInitializeEx may have succeeded
			# before _ensureInitialized failed. Best-effort; ignore errors.
			try:
				ctypes.windll.ole32.CoUninitialize()
			except Exception:
				pass
			return
		# 2. Signal readiness.
		self._readyEvent.set()
		# 3. Drain the queue, pumping Win32 messages between iterations.
		while True:
			try:
				item = self._queue.get(timeout=_PUMP_INTERVAL_S)
			except QueueEmpty:
				# Idle: pump the message queue so library-fired events (UIA
				# callbacks, hardware events) are dispatched to their handlers.
				_pumpThreadMessages()
				continue
			if item is None:
				break
			fn, args, kwargs, future = item
			opName = getattr(fn, "__name__", repr(fn))
			# Record the in-flight operation so the timeout diagnostics can see
			# what we're stuck on. If the call hangs, the ``finally`` never runs
			# and these stay pinned — that's the signal captureDiagnostics reads.
			with self._stateLock:
				self._currentOp = opName
				self._currentOpStartMonotonic = time.monotonic()
			try:
				result = fn(*args, **kwargs)
				future.set_result(result)
			except BaseException as e:
				future.set_exception(e)
			finally:
				with self._stateLock:
					self._currentOp = None
					self._currentOpStartMonotonic = None
					self._completedOpCount += 1
			# After every call, drain any messages the library posted while we
			# were busy (UIA events / button events fired during the call).
			_pumpThreadMessages()
		# 4. Best-effort wrapper teardown. By this point the init succeeded
		# (otherwise we'd have returned early via the except branch above), so
		# self.tda is non-None.
		tda = self.tda
		try:
			tda.disconnect()
		except Exception:
			pass
		try:
			tda.close()
		except Exception:
			pass
		# Final pump in case disconnect/close emitted device-removal events.
		_pumpThreadMessages()
		self.tda = None
		# 5. Release the COM apartment.
		try:
			ctypes.windll.ole32.CoUninitialize()
		except Exception:
			pass
