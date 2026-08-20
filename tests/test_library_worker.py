# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for the LibraryWorker daemon thread.

Covers:
- Lifecycle: start succeeds; stop returns immediately; thread is daemon and
  has the distinct name DotPadLibraryWorker.
- Future propagation: submit returns a Future that resolves with the
  callable's return value; exceptions raised by the callable are re-raised
  via future.result().
- Bounded waits: submitAndAwait raises TimeoutError when the callable
  doesn't complete within the budget; the worker remains alive afterward.
- FIFO order: callables run in submission order.
- Hang scenario (FR-010, US5): a callable that blocks on a never-set Event
  causes submitAndAwait to time out within the budget; stop is non-blocking
  and the worker thread is leaked as a daemon (timeout-leak contract).
- Start failure: when TactileDisplayAPI._ensureInitialized raises, the
  exception propagates through start() to the caller.

The COM init / wrapper construction inside _run is stubbed via patching:
- ctypes.windll.ole32.CoInitializeEx → no-op
- ctypes.windll.ole32.CoUninitialize → no-op
- TactileDisplayAPI → MagicMock(spec=TactileDisplayAPI) so _ensureInitialized
  is a no-op MagicMock.
"""

from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch


@contextmanager
def _stubbedComEnvironment() -> Iterator[MagicMock]:
	"""Patch CoInitializeEx + CoUninitialize + TactileDisplayAPI for the
	worker's _run() method.

	Yields the MagicMock TactileDisplayAPI class so tests can configure its
	_ensureInitialized side effect.
	"""
	from addon.tactileDisplayAPI import wrapper as wrapperModule

	mockOle32 = MagicMock()
	mockOle32.CoInitializeEx = MagicMock(return_value=0)
	mockOle32.CoUninitialize = MagicMock(return_value=0)

	# user32.PeekMessageW returns 0 ("no messages") so the STA message-pump loop
	# exits immediately instead of spinning on auto-created truthy child mocks.
	mockUser32 = MagicMock()
	mockUser32.PeekMessageW = MagicMock(return_value=0)
	mockUser32.TranslateMessage = MagicMock(return_value=0)
	mockUser32.DispatchMessageW = MagicMock(return_value=0)

	mockTdaClass = MagicMock(spec=wrapperModule.TactileDisplayAPI)
	# An instance returned from calling the class: configure _ensureInitialized
	# (and disconnect/close, used in best-effort teardown) as no-op MagicMocks.
	mockTdaInstance = MagicMock()
	mockTdaInstance._ensureInitialized = MagicMock(return_value=None)
	mockTdaInstance.disconnect = MagicMock(return_value=None)
	mockTdaInstance.close = MagicMock(return_value=None)
	mockTdaClass.return_value = mockTdaInstance

	with (
		patch("addon.tactileDisplayAPI.libraryWorker.ctypes") as mockCtypes,
		patch("addon.tactileDisplayAPI.libraryWorker.TactileDisplayAPI", mockTdaClass),
	):
		mockCtypes.windll.ole32 = mockOle32
		mockCtypes.windll.user32 = mockUser32
		try:
			yield mockTdaClass
		finally:
			# Join any DotPadLibraryWorker threads the test started before we
			# restore the real ``ctypes`` module. Most tests call ``worker.stop()``
			# (non-blocking by contract) in their ``finally`` blocks but do not
			# join the thread; if we exit the patch context while a worker is
			# still draining, it continues running against a stale mock ``ctypes``
			# reference. Joining each worker here ensures the next test starts
			# with no leaked threads.
			for t in threading.enumerate():
				if t.name == "DotPadLibraryWorker" and t.is_alive():
					t.join(timeout=2.0)


class TestStartStopLifecycle(unittest.TestCase):
	"""start() spawns the worker, stops cleanly via stop()."""

	def test_start_then_stop_thread_exits(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			self.assertIsNotNone(worker._thread)
			assert worker._thread is not None
			self.assertTrue(worker._thread.is_alive())
			worker.stop()
			worker._thread.join(timeout=2.0)
			self.assertFalse(worker._thread.is_alive())


class TestThreadIsDaemon(unittest.TestCase):
	"""The worker thread MUST be daemon — dies with the process if leaked."""

	def test_thread_is_daemon(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				assert worker._thread is not None
				self.assertTrue(worker._thread.daemon)
			finally:
				worker.stop()


class TestThreadHasDistinctName(unittest.TestCase):
	"""The worker thread is named DotPadLibraryWorker for diagnostics."""

	def test_thread_name(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				assert worker._thread is not None
				self.assertEqual(worker._thread.name, "DotPadLibraryWorker")
			finally:
				worker.stop()


class TestSubmitReturnsValueViaFuture(unittest.TestCase):
	"""submit() returns a Future that resolves with the callable's value."""

	def test_submit_resolves_future(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				future = worker.submit(lambda: 42)
				self.assertEqual(future.result(timeout=2.0), 42)
			finally:
				worker.stop()


class TestSubmitPropagatesException(unittest.TestCase):
	"""Exceptions raised by the callable propagate via future.result()."""

	def test_exception_propagates(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		def boom() -> None:
			raise ValueError("test failure")

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				future = worker.submit(boom)
				with self.assertRaises(ValueError) as ctx:
					future.result(timeout=2.0)
				self.assertEqual(str(ctx.exception), "test failure")
			finally:
				worker.stop()


class TestSubmitAndAwaitTimeout(unittest.TestCase):
	"""submitAndAwait raises TimeoutError when the callable doesn't complete."""

	def test_timeout_raised_within_budget(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		releaseEvent = threading.Event()  # never set — callable blocks forever

		def block() -> None:
			releaseEvent.wait()

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				start = time.perf_counter()
				with self.assertRaises(FutureTimeoutError):
					worker.submitAndAwait(block, timeout=0.1)
				elapsed = time.perf_counter() - start
				# Should fire within the budget plus scheduling jitter; allow
				# a generous 0.5 s ceiling.
				self.assertLess(elapsed, 0.5)
			finally:
				releaseEvent.set()  # let the worker callable finish
				worker.stop()


class TestFifoOrder(unittest.TestCase):
	"""Submitted callables run in FIFO order on the single worker thread."""

	def test_fifo(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		log_: list[int] = []

		def append(n: int) -> int:
			log_.append(n)
			return n

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				f1 = worker.submit(append, 1)
				f2 = worker.submit(append, 2)
				f3 = worker.submit(append, 3)
				f1.result(timeout=2.0)
				f2.result(timeout=2.0)
				f3.result(timeout=2.0)
			finally:
				worker.stop()
		self.assertEqual(log_, [1, 2, 3])


class TestHangScenarioTimesOut(unittest.TestCase):
	"""US5: a callable that blocks on a never-set Event causes submitAndAwait
	to time out. The worker thread is left alive (timeout-leak contract).
	"""

	def test_hung_callable_times_out_worker_leaked(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		hangEvent = threading.Event()  # never set

		def hang() -> None:
			hangEvent.wait()

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				with self.assertRaises(FutureTimeoutError):
					worker.submitAndAwait(hang, timeout=0.1)
				# The worker thread is still running the hung callable. stop()
				# is non-blocking and the daemon is leaked — that's the
				# documented contract.
				assert worker._thread is not None
				self.assertTrue(worker._thread.is_alive())
				worker.stop()
				# stop() does NOT join. The thread remains alive.
				self.assertTrue(worker._thread.is_alive())
			finally:
				# Release the hung callable so the daemon can exit cleanly,
				# avoiding a leaked thread interfering with subsequent tests.
				hangEvent.set()


class TestStopAfterHangIsNonBlocking(unittest.TestCase):
	"""US5: stop() is non-blocking even when the worker is wedged on a callable."""

	def test_stop_returns_quickly_under_hang(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		hangEvent = threading.Event()

		def hang() -> None:
			hangEvent.wait()

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				worker.submit(hang)  # consumed by worker; will block forever
				time.sleep(0.05)  # give the worker a moment to start the call
				start = time.perf_counter()
				worker.stop()
				elapsed = time.perf_counter() - start
				self.assertLess(elapsed, 0.05)
			finally:
				hangEvent.set()


class TestStartFailurePropagates(unittest.TestCase):
	"""When _ensureInitialized raises during _run startup, start() re-raises
	on the calling thread.
	"""

	def test_init_failure_raises_on_start(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		with _stubbedComEnvironment() as mockTdaClass:
			# Configure the wrapper instance's _ensureInitialized to raise.
			mockTdaInstance = mockTdaClass.return_value
			mockTdaInstance._ensureInitialized.side_effect = RuntimeError("DLL load failed")

			worker = LibraryWorker()
			with self.assertRaises(RuntimeError) as ctx:
				worker.start(startTimeoutS=2.0)
			self.assertEqual(str(ctx.exception), "DLL load failed")
			# The thread exits cleanly after setting the start error.
			assert worker._thread is not None
			worker._thread.join(timeout=2.0)
			self.assertFalse(worker._thread.is_alive())


class TestSubmitAndReportSuccess(unittest.TestCase):
	"""submitAndReport: callable returns successfully → onSuccess invoked, onFailure not."""

	def test_success_path(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		successResults: list[int] = []
		failureResults: list[BaseException] = []
		done = threading.Event()

		def onSuccess(result: int) -> None:
			successResults.append(result)
			done.set()

		def onFailure(exc: BaseException) -> None:
			failureResults.append(exc)
			done.set()

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				worker.submitAndReport(
					lambda: 42,
					timeout=2.0,
					onSuccess=onSuccess,
					onFailure=onFailure,
				)
				self.assertTrue(done.wait(timeout=2.0))
			finally:
				worker.stop()

		self.assertEqual(successResults, [42])
		self.assertEqual(failureResults, [])


class TestSubmitAndReportTimeout(unittest.TestCase):
	"""submitAndReport: callable hangs → onFailure invoked with TimeoutError;
	onSuccess never invoked."""

	def test_timeout_path(self) -> None:
		from concurrent.futures import TimeoutError as FutureTimeoutError

		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		successResults: list[object] = []
		failureResults: list[BaseException] = []
		done = threading.Event()
		hang = threading.Event()

		def onSuccess(result: object) -> None:
			successResults.append(result)
			done.set()

		def onFailure(exc: BaseException) -> None:
			failureResults.append(exc)
			done.set()

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				worker.submitAndReport(
					lambda: hang.wait(),
					timeout=0.1,
					onSuccess=onSuccess,
					onFailure=onFailure,
				)
				self.assertTrue(done.wait(timeout=1.0))
			finally:
				hang.set()  # let the daemon callable finish so the worker can exit
				worker.stop()

		self.assertEqual(successResults, [])
		self.assertEqual(len(failureResults), 1)
		self.assertIsInstance(failureResults[0], FutureTimeoutError)


class TestSubmitAndReportException(unittest.TestCase):
	"""submitAndReport: callable raises → onFailure invoked with the exception."""

	def test_exception_path(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		failureResults: list[BaseException] = []
		done = threading.Event()

		def onFailure(exc: BaseException) -> None:
			failureResults.append(exc)
			done.set()

		def boom() -> None:
			raise ValueError("test failure")

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				worker.submitAndReport(
					boom,
					timeout=2.0,
					onSuccess=lambda _: None,
					onFailure=onFailure,
				)
				self.assertTrue(done.wait(timeout=2.0))
			finally:
				worker.stop()

		self.assertEqual(len(failureResults), 1)
		self.assertIsInstance(failureResults[0], ValueError)


class TestWorkerInitialisesSta(unittest.TestCase):
	"""The worker initialises COM as STA (COINIT_APARTMENTTHREADED = 0x2).

	The library is a UIA client whose event callbacks are delivered via the
	thread message pump, so the worker must be a pumping STA. (An MTA worker
	receives no events and library-driven braille goes dark.)
	"""

	def test_coinitialize_called_apartmentthreaded(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		with _stubbedComEnvironment():
			import addon.tactileDisplayAPI.libraryWorker as lw

			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				lw.ctypes.windll.ole32.CoInitializeEx.assert_called_once_with(None, 0x2)
			finally:
				worker.stop()


class TestMessagePumpRunsOnIdle(unittest.TestCase):
	"""The STA worker drains Win32 messages between queue items via PeekMessageW.

	Required so UIA event callbacks (and hardware events) are delivered into the
	worker's apartment; without pumping the library's queue grows unbounded.
	"""

	def test_peekMessageW_called_during_idle(self) -> None:
		import time as _time

		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		with _stubbedComEnvironment():
			import addon.tactileDisplayAPI.libraryWorker as lw

			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				_time.sleep(0.2)  # ~4 pump intervals (50 ms each) while idle
				peekCalls = lw.ctypes.windll.user32.PeekMessageW.call_count
				self.assertGreater(peekCalls, 0, f"Expected PeekMessageW during idle, got {peekCalls}")
			finally:
				worker.stop()


class TestSubmitAndReportMutuallyExclusive(unittest.TestCase):
	"""submitAndReport: a slow successful completion that finishes shortly
	after the timeout fires must NOT invoke both callbacks. The timeout
	wins; the late completion is a no-op."""

	def test_timeout_wins_against_late_completion(self) -> None:
		import time as _time

		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		callbackCount: list[int] = []
		done = threading.Event()

		def onCallback(arg: object) -> None:
			callbackCount.append(1)
			done.set()

		def slowSuccess() -> int:
			# Sleep just longer than the timeout so timeout fires first; then
			# return successfully.
			_time.sleep(0.15)
			return 7

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				worker.submitAndReport(
					slowSuccess,
					timeout=0.05,
					onSuccess=onCallback,
					onFailure=onCallback,
				)
				# Wait long enough for both the timeout AND the late success.
				done.wait(timeout=1.0)
				_time.sleep(0.2)  # let any late-fired callback execute
			finally:
				worker.stop()

		# Exactly one callback fired (the timeout), not two.
		self.assertEqual(len(callbackCount), 1)


def _waitForCurrentOp(worker: object, timeout: float = 2.0) -> str | None:
	"""Poll until the worker thread has picked up an operation, or timeout."""
	deadline = time.perf_counter() + timeout
	while time.perf_counter() < deadline:
		with worker._stateLock:  # type: ignore[attr-defined]
			op = worker._currentOp  # type: ignore[attr-defined]
		if op is not None:
			return op
		time.sleep(0.005)
	return None


class TestCaptureDiagnosticsReportsCurrentOp(unittest.TestCase):
	"""captureDiagnostics() reports the in-flight op, queue depth, and the
	worker thread's live Python stack — the conclusive wedge evidence."""

	def test_diagnostics_include_op_and_stack(self) -> None:
		from addon.tactileDisplayAPI.libraryWorker import LibraryWorker

		hang = threading.Event()

		def wedgingOperation() -> None:
			hang.wait()

		with _stubbedComEnvironment():
			worker = LibraryWorker()
			worker.start(startTimeoutS=2.0)
			try:
				worker.submit(wedgingOperation)
				op = _waitForCurrentOp(worker)
				self.assertEqual(op, "wedgingOperation")
				diag = worker.captureDiagnostics()
				self.assertIn("wedgingOperation", diag)
				self.assertIn("queueDepth=", diag)
				self.assertIn("completedOps=", diag)
				# The live worker stack should name the blocked frame.
				self.assertIn("worker thread stack", diag)
				self.assertIn("wedgingOperation", diag.split("stack", 1)[1])
			finally:
				hang.set()
				worker.stop()


if __name__ == "__main__":
	unittest.main()
