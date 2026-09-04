# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Unit tests for recovery when a display stops responding.

The packet sender waits for the display to report a line has rendered before sending
the next one. That wait is bounded by two separate budgets, and the distinction is the
whole point of these tests:

* the link is checked every ``CONNECTION_POLL_SECONDS``, so a disconnect is noticed
  quickly;
* the render budget comes from the device's own reported refresh time, and is much
  longer, because tactile actuation genuinely takes seconds.

The gate opens on ``NTF_DISPLAY_LINE`` (pins actually moved), not on the protocol
acknowledgement, so a budget derived from ``timeout`` -- NVDA's protocol-level figure --
would fire on healthy hardware and resend lines the display had already accepted.

The hardest case to catch, and the one issue #21 describes, is a device switched off
while its USB serial interface stays enumerated: writes keep succeeding and nothing
raises, so only the escalation counter notices.
"""

from __future__ import annotations

import inspect
import threading
import time
import unittest
from queue import PriorityQueue
from unittest.mock import MagicMock, patch

from addon.brailleDisplayDrivers.dotPad import driver as dotpad_driver

_DRIVER_MODULE = "addon.brailleDisplayDrivers.dotPad.driver"


def _makeDriver(*, connected: bool = True) -> dotpad_driver.BrailleDisplayDriver:
	"""A driver with just the send-gate state the wait touches."""
	driver = dotpad_driver.BrailleDisplayDriver.__new__(dotpad_driver.BrailleDisplayDriver)
	# Built the same way __init__ does, so this fixture cannot drift from production
	# and hide a field the sender thread needs.
	driver._initSendState()
	# _waitForSendSlot is only reached with a packet in flight, so model that: the gate
	# is cleared just before each write.
	driver._readyToSend.clear()
	driver._isTerminating = threading.Event()
	driver._boardInformation = None
	driver._dev = MagicMock()
	driver._dev.isConnected.return_value = connected
	# isConnected() only means anything on BLE, which is what the flag now selects.
	driver._isBleConnection = True
	return driver


def _boardInfo(textRefresh: int, graphicRefresh: int) -> MagicMock:
	info = MagicMock()
	info.text.refreshTime = textRefresh
	info.graphic.refreshTime = graphicRefresh
	return info


class TestRenderTimeout(unittest.TestCase):
	"""The budget comes from the device, not from NVDA's protocol timeout."""

	def test_derived_from_the_reported_refresh_time(self) -> None:
		driver = _makeDriver()
		# 100 ms units per the Dot protocol specification: 30 -> 3.0s.
		driver._boardInformation = _boardInfo(textRefresh=10, graphicRefresh=30)

		expected = 30 * dotpad_driver.REFRESH_TIME_UNIT_SECONDS * dotpad_driver.RENDER_TIMEOUT_FACTOR
		self.assertAlmostEqual(expected, driver._getRenderTimeout())

	def test_uses_the_slower_of_the_two_displays(self) -> None:
		driver = _makeDriver()
		driver._boardInformation = _boardInfo(textRefresh=50, graphicRefresh=20)

		expected = 50 * dotpad_driver.REFRESH_TIME_UNIT_SECONDS * dotpad_driver.RENDER_TIMEOUT_FACTOR
		self.assertAlmostEqual(expected, driver._getRenderTimeout())

	def test_falls_back_when_the_device_reports_nothing(self) -> None:
		driver = _makeDriver()
		self.assertEqual(dotpad_driver.DEFAULT_RENDER_TIMEOUT_SECONDS, driver._getRenderTimeout())

		driver._boardInformation = _boardInfo(textRefresh=0, graphicRefresh=0)
		self.assertEqual(dotpad_driver.DEFAULT_RENDER_TIMEOUT_SECONDS, driver._getRenderTimeout())

	def test_is_not_derived_from_the_protocol_timeout(self) -> None:
		"""Guards the regression this replaced: timeout*2 is far too short to render."""
		driver = _makeDriver()
		driver._boardInformation = _boardInfo(textRefresh=25, graphicRefresh=25)

		with patch.object(type(driver), "timeout", 0.15):
			self.assertGreater(driver._getRenderTimeout(), 0.15 * 2)


class TestWaitForSendSlot(unittest.TestCase):
	def test_returns_true_once_the_line_has_rendered(self) -> None:
		driver = _makeDriver()
		driver._readyToSend.set()

		with (
			patch.object(type(driver), "_getRenderTimeout", lambda _self: 0.05),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 0.01),
		):
			self.assertTrue(driver._waitForSendSlot())

	def test_wakes_on_the_notification_not_on_a_poll_tick(self) -> None:
		driver = _makeDriver()
		threading.Timer(0.01, driver._readyToSend.set).start()

		with (
			patch.object(type(driver), "_getRenderTimeout", lambda _self: 5),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 5),
		):
			start = time.monotonic()
			self.assertTrue(driver._waitForSendSlot())

		self.assertLess(time.monotonic() - start, 1)

	def test_tolerates_a_slow_render_while_the_link_is_up(self) -> None:
		"""Healthy but slow hardware must not be treated as a fault."""
		driver = _makeDriver(connected=True)
		driver._resendLastPacket = MagicMock()  # type: ignore[method-assign]
		threading.Timer(0.05, driver._readyToSend.set).start()

		with (
			patch.object(type(driver), "_getRenderTimeout", lambda _self: 5),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 0.01),
		):
			self.assertTrue(driver._waitForSendSlot())

		driver._resendLastPacket.assert_not_called()
		self.assertEqual(0, driver._consecutiveRenderTimeouts)

	def test_releases_the_display_when_the_link_drops(self) -> None:
		driver = _makeDriver(connected=False)

		with (
			patch.object(type(driver), "_getRenderTimeout", lambda _self: 30),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 0.01),
			patch(f"{_DRIVER_MODULE}.core") as core,
		):
			start = time.monotonic()
			self.assertFalse(driver._waitForSendSlot())

		# Noticed via the short liveness poll, not after the long render budget.
		self.assertLess(time.monotonic() - start, 1)
		core.callLater.assert_called_once()

	def test_retries_before_giving_up(self) -> None:
		driver = _makeDriver(connected=True)
		driver._resendLastPacket = MagicMock()  # type: ignore[method-assign]

		with (
			patch.object(type(driver), "_getRenderTimeout", lambda _self: 0.02),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 0.01),
			patch(f"{_DRIVER_MODULE}.core") as core,
		):
			self.assertFalse(driver._waitForSendSlot())

		self.assertEqual(
			dotpad_driver.MAX_CONSECUTIVE_RENDER_TIMEOUTS - 1,
			driver._resendLastPacket.call_count,
		)
		core.callLater.assert_called_once()

	def test_gives_up_on_a_powered_off_but_still_enumerated_device(self) -> None:
		"""Issue #21: the port stays open, writes succeed, and nothing ever raises.

		``isConnected()`` cannot help here -- serial has none, so it reports connected --
		which is why escalation has to be independent of it.
		"""
		driver = _makeDriver(connected=True)
		driver._isBleConnection = False  # Serial cannot report link state.
		driver._resendLastPacket = MagicMock()  # type: ignore[method-assign]

		with (
			patch.object(type(driver), "_getRenderTimeout", lambda _self: 0.02),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 0.01),
			patch(f"{_DRIVER_MODULE}.core") as core,
		):
			self.assertFalse(driver._waitForSendSlot())

		core.callLater.assert_called_once()

	def test_stops_when_terminating(self) -> None:
		"""terminate() joins this thread, so the wait must not outlive the signal."""
		driver = _makeDriver()
		driver._isTerminating.set()

		with (
			patch.object(type(driver), "_getRenderTimeout", lambda _self: 30),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 5),
		):
			self.assertFalse(driver._waitForSendSlot())


class TestEscalationCounterReset(unittest.TestCase):
	def test_any_packet_from_the_display_clears_the_counter(self) -> None:
		"""Liveness is proven by the device talking, not by the gate opening.

		_resendLastPacket's give-up branch also opens the gate, so resetting on a
		successful wait would mask a display that never actually responds.
		"""
		driver = _makeDriver()
		driver._consecutiveRenderTimeouts = 4
		packet = MagicMock()
		packet.packetType = None

		driver._handleResponse(packet)

		self.assertEqual(0, driver._consecutiveRenderTimeouts)


class TestIsDeviceConnected(unittest.TestCase):
	def test_reports_the_transport_state(self) -> None:
		self.assertTrue(_makeDriver(connected=True)._isDeviceConnected())
		self.assertFalse(_makeDriver(connected=False)._isDeviceConnected())

	def test_serial_is_assumed_connected(self) -> None:
		"""Serial cannot report link state -- a powered-off device stays enumerated --
		so recovery falls back to the escalation counter."""
		driver = _makeDriver(connected=False)
		driver._isBleConnection = False

		self.assertTrue(driver._isDeviceConnected())

	def test_treats_a_failing_query_as_disconnected(self) -> None:
		driver = _makeDriver()
		driver._dev.isConnected.side_effect = OSError("device gone")

		self.assertFalse(driver._isDeviceConnected())


class TestSendFailureReleasesDisplay(unittest.TestCase):
	"""A failing write means the display is unreachable, whatever the transport."""

	def _driverReadyToSend(self) -> dotpad_driver.BrailleDisplayDriver:
		driver = _makeDriver()
		driver._readyToSend.set()
		return driver

	def _packet(self) -> MagicMock:
		prioritized = MagicMock()
		prioritized.packet.packetType = None
		return prioritized

	def test_serial_style_oserror_releases_the_display(self) -> None:
		driver = self._driverReadyToSend()
		driver._dev.write.side_effect = OSError("device disconnected")

		with patch(f"{_DRIVER_MODULE}.core") as core:
			driver._sendQueuedPacket(self._packet())

		self.assertTrue(driver._displayGone)
		core.callLater.assert_called_once()

	def test_ble_style_runtimeerror_releases_the_display(self) -> None:
		driver = self._driverReadyToSend()
		driver._dev.write.side_effect = RuntimeError("Not connected to peripheral")

		with patch(f"{_DRIVER_MODULE}.core") as core:
			driver._sendQueuedPacket(self._packet())

		self.assertTrue(driver._displayGone)
		core.callLater.assert_called_once()

	def test_the_send_gate_is_not_left_clear_after_a_failed_write(self) -> None:
		"""Clearing it for a write that never happened would block the next packet."""
		driver = self._driverReadyToSend()
		driver._dev.write.side_effect = OSError("device disconnected")

		with patch(f"{_DRIVER_MODULE}.core"):
			driver._sendQueuedPacket(self._packet())

		self.assertTrue(driver._readyToSend.is_set())

	def test_the_gate_is_cleared_before_writing(self) -> None:
		"""A notification arriving mid-write must not be discarded by a later clear."""
		driver = self._driverReadyToSend()
		clearedDuringWrite: list[bool] = []
		driver._dev.write.side_effect = lambda _packet: clearedDuringWrite.append(
			not driver._readyToSend.is_set(),
		)

		driver._sendQueuedPacket(self._packet())

		self.assertEqual([True], clearedDuringWrite)


class TestReportDisplayUnavailable(unittest.TestCase):
	def test_does_nothing_if_another_display_took_over(self) -> None:
		"""Tearing down the display the user fell back to would leave them with none."""
		driver = _makeDriver()

		with (
			patch(f"{_DRIVER_MODULE}.core") as core,
			patch(f"{_DRIVER_MODULE}.braille") as braille,
		):
			driver._reportDisplayUnavailable()
			scheduled = core.callLater.call_args.args[1]
			# A different display is current by the time the callback runs.
			braille.handler.display = MagicMock()
			scheduled()

		braille.handler.handleDisplayUnavailable.assert_not_called()

	def test_releases_when_still_the_current_display(self) -> None:
		driver = _makeDriver()

		with (
			patch(f"{_DRIVER_MODULE}.core") as core,
			patch(f"{_DRIVER_MODULE}.braille") as braille,
		):
			driver._reportDisplayUnavailable()
			scheduled = core.callLater.call_args.args[1]
			braille.handler.display = driver
			scheduled()

		braille.handler.handleDisplayUnavailable.assert_called_once_with()

	def test_schedules_nothing_once_termination_has_started(self) -> None:
		"""NVDA is already tearing this driver down, so there is nothing to release.

		The check has to happen at scheduling time: NVDA re-initialises the *same*
		driver object when it reconnects a display of the same class, so by the time a
		callback ran ``handler.display is self`` could be true again -- of a display
		that had just come back, which would then be torn down.
		"""
		driver = _makeDriver()
		driver._terminationStarted.set()

		with (
			patch(f"{_DRIVER_MODULE}.core") as core,
			patch(f"{_DRIVER_MODULE}.braille"),
		):
			driver._reportDisplayUnavailable()

		core.callLater.assert_not_called()


class TestTerminationDoesNotBlock(unittest.TestCase):
	"""terminate() runs on the main thread when NVDA switches displays.

	NVDA's watchdog reports a freeze after 25s, and hardware logs showed exactly that:
	terminate() blocking on Queue.join() while the sender waited out the full render
	budget against a display that had stopped responding.
	"""

	def test_wait_gives_up_quickly_once_terminating(self) -> None:
		driver = _makeDriver(connected=True)
		driver._terminationStarted.set()
		driver._resendLastPacket = MagicMock()  # type: ignore[method-assign]

		with (
			patch.object(type(driver), "_getRenderTimeout", lambda _self: 30),
			patch(f"{_DRIVER_MODULE}.TERMINATE_ACK_TIMEOUT_SECONDS", 0.02),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 0.01),
			patch(f"{_DRIVER_MODULE}.core") as core,
		):
			start = time.monotonic()
			self.assertFalse(driver._waitForSendSlot())

		self.assertLess(time.monotonic() - start, 1, "must not wait out the render budget")
		# Clearing on the way out is best-effort: no retries, and no tearing down a
		# display NVDA is already switching away from.
		driver._resendLastPacket.assert_not_called()
		core.callLater.assert_not_called()

	def test_a_dead_link_is_not_reported_while_terminating(self) -> None:
		"""The display being switched off is the usual reason terminate() runs at all.

		The link poll fires before the terminate budget expires, so without the guard
		in _reportDisplayUnavailable() the way out still scheduled a teardown.
		"""
		driver = _makeDriver(connected=False)
		driver._terminationStarted.set()

		with (
			patch(f"{_DRIVER_MODULE}.TERMINATE_ACK_TIMEOUT_SECONDS", 0.05),
			patch(f"{_DRIVER_MODULE}.CONNECTION_POLL_SECONDS", 0.01),
			patch(f"{_DRIVER_MODULE}.core") as core,
			patch(f"{_DRIVER_MODULE}.braille"),
		):
			self.assertFalse(driver._waitForSendSlot())

		core.callLater.assert_not_called()

	def test_drain_returns_true_when_the_queue_empties(self) -> None:
		driver = _makeDriver()
		driver._queuedPackets = PriorityQueue()

		self.assertTrue(driver._waitForQueueDrain(0.5))

	def test_drain_gives_up_on_an_unconsumed_queue(self) -> None:
		"""The freeze itself: nothing is consuming, so join() would never return."""
		driver = _makeDriver()
		driver._queuedPackets = PriorityQueue()
		driver._queuedPackets.put(MagicMock())

		start = time.monotonic()
		self.assertFalse(driver._waitForQueueDrain(0.05))
		self.assertLess(time.monotonic() - start, 1)

	def test_drain_returns_once_the_sender_catches_up(self) -> None:
		driver = _makeDriver()
		driver._queuedPackets = PriorityQueue()
		driver._queuedPackets.put(MagicMock())

		def consume() -> None:
			driver._queuedPackets.get()
			driver._queuedPackets.task_done()

		threading.Timer(0.02, consume).start()

		self.assertTrue(driver._waitForQueueDrain(2))


class TestEscalationSpeed(unittest.TestCase):
	def test_gives_up_after_two_silent_budgets(self) -> None:
		"""Hardware logs showed six budgets costing ~43s before releasing."""
		self.assertEqual(2, dotpad_driver.MAX_CONSECUTIVE_RENDER_TIMEOUTS)


class TestSendStateIsComplete(unittest.TestCase):
	"""__init__ starts the sender thread, so every field it reads must exist by then.

	A missing one surfaces as an AttributeError inside the running thread rather than
	at construction -- which is exactly how `_terminationStarted` shipped: it was
	declared as a class annotation, never assigned, and the test fixture set it by
	hand so nothing caught it.
	"""

	def test_initSendState_is_called_before_the_sender_thread_starts(self) -> None:
		source = inspect.getsource(dotpad_driver.BrailleDisplayDriver.__init__)
		self.assertLess(
			source.index("_initSendState()"),
			source.index("_queuedPacketsSenderThread.start()"),
		)

	def test_every_field_the_sender_reads_is_initialised(self) -> None:
		driver = dotpad_driver.BrailleDisplayDriver.__new__(dotpad_driver.BrailleDisplayDriver)
		driver._initSendState()

		for name in (
			"_readyToSend",
			"_displayGone",
			"_consecutiveRenderTimeouts",
			"_terminationStarted",
			"_lastSentPacket",
			"_lastSentPacketNumTries",
			"_lastSentWasRefresh",
		):
			with self.subTest(field=name):
				self.assertTrue(hasattr(driver, name), f"{name} is not set by _initSendState()")

	def test_the_gate_starts_open(self) -> None:
		"""Nothing has been sent yet, so the first packet must not wait."""
		driver = dotpad_driver.BrailleDisplayDriver.__new__(dotpad_driver.BrailleDisplayDriver)
		driver._initSendState()

		self.assertTrue(driver._readyToSend.is_set())
		self.assertFalse(driver._terminationStarted.is_set())


class TestDisplayGoneIsNotLatchedWhileTerminating(unittest.TestCase):
	"""The termination budget says nothing about the display's health.

	While terminating, _waitForSendSlot uses TERMINATE_ACK_TIMEOUT_SECONDS (1.0s),
	which is shorter than a single normal full-area render (~3.6s on real hardware).
	Latching _displayGone when that expires discarded every clear packet still queued
	-- on perfectly healthy hardware, at every termination.

	_isTerminating alone could not guard this: terminate() only sets it at step 6,
	after the drain, so the entire drain window has it clear. _terminationStarted is
	set first thing instead.
	"""

	def _packet(self) -> MagicMock:
		prioritized = MagicMock()
		prioritized.packet.packetType = None
		return prioritized

	def _driverInDrainWindow(self) -> dotpad_driver.BrailleDisplayDriver:
		driver = _makeDriver()
		# Exactly the state terminate() is in while flushing clear packets.
		driver._terminationStarted.set()
		self.assertFalse(driver._isTerminating.is_set(), "drain runs before step 6")
		return driver

	def test_a_timeout_while_terminating_does_not_mark_the_display_gone(self) -> None:
		driver = self._driverInDrainWindow()

		with patch.object(type(driver), "_waitForSendSlot", return_value=False):
			driver._sendQueuedPacket(self._packet())

		self.assertFalse(driver._displayGone)

	def test_a_timeout_outside_termination_still_marks_the_display_gone(self) -> None:
		"""Guards the opposite error: never latching would pass the test above too."""
		driver = _makeDriver()

		with patch.object(type(driver), "_waitForSendSlot", return_value=False):
			driver._sendQueuedPacket(self._packet())

		self.assertTrue(driver._displayGone)

	def test_a_later_clear_packet_is_still_sent(self) -> None:
		"""The point of the fix: a slow text clear must not discard the graphic one.

		clearForTermination() queues one packet per external row, and _displayGone
		makes every remaining one a no-op -- so latching on the first timeout silently
		aborted clearing the rest, leaving stale content on the display.
		"""
		driver = self._driverInDrainWindow()

		with patch.object(type(driver), "_waitForSendSlot", side_effect=[False, True]):
			driver._sendQueuedPacket(self._packet())  # times out, sends nothing
			driver._sendQueuedPacket(self._packet())  # must still get its turn

		driver._dev.write.assert_called_once()


class TestTerminateDoesNotWaitForeverOnTheSender(unittest.TestCase):
	"""terminate() runs on the main thread, so no join in it may be unbounded.

	The sender normally notices _isTerminating within CONNECTION_POLL_SECONDS, but it
	can also be parked in self._dev.write(), which has no timeout of its own: on BLE
	that is a hand-off to the asyncio loop, and a peripheral that has gone away can
	stall it. #147 bounded the queue drain at step 5 and left this join unbounded, so
	the same freeze was still reachable one step later.
	"""

	def _driverStuckInSend(self, stuck: threading.Event) -> dotpad_driver.BrailleDisplayDriver:
		driver = _makeDriver()
		driver._blockNewWrites = threading.Event()
		driver._renderer = None
		driver._queuedPackets = PriorityQueue()
		driver.textDisplay = None
		driver.graphicDisplay = None
		# Stands in for a sender parked inside a write that never returns.
		driver._queuedPacketsSenderThread = threading.Thread(target=stuck.wait, daemon=True)
		driver._queuedPacketsSenderThread.start()
		return driver

	def test_returns_even_though_the_sender_never_exits(self) -> None:
		stuck = threading.Event()
		self.addCleanup(stuck.set)
		driver = self._driverStuckInSend(stuck)

		with (
			patch(f"{_DRIVER_MODULE}.TERMINATE_JOIN_TIMEOUT_SECONDS", 0.05),
			patch.object(type(driver), "_teardownLibrarySingleton"),
			patch.object(type(driver), "_waitForQueueDrain", return_value=True),
			patch(f"{_DRIVER_MODULE}.braille.BrailleDisplayDriver.terminate"),
		):
			# terminate() runs on a worker so an unbounded join fails this test rather
			# than wedging the whole suite -- which is what it did before the bound.
			finished = threading.Event()
			worker = threading.Thread(target=lambda: (driver.terminate(), finished.set()), daemon=True)
			worker.start()
			self.assertTrue(finished.wait(2), "terminate() must not block on a stuck sender")
		self.assertTrue(driver._queuedPacketsSenderThread.is_alive(), "thread outlived the join")

	def test_waits_for_a_sender_that_does_exit(self) -> None:
		"""The bound is a backstop, not a reason to stop waiting for the normal case."""
		stuck = threading.Event()
		driver = self._driverStuckInSend(stuck)
		stuck.set()

		with (
			patch(f"{_DRIVER_MODULE}.TERMINATE_JOIN_TIMEOUT_SECONDS", 5),
			patch.object(type(driver), "_teardownLibrarySingleton"),
			patch.object(type(driver), "_waitForQueueDrain", return_value=True),
			patch(f"{_DRIVER_MODULE}.braille.BrailleDisplayDriver.terminate"),
		):
			driver.terminate()

		self.assertFalse(driver._queuedPacketsSenderThread.is_alive())


class TestClearIsSkippedOverBle(unittest.TestCase):
	"""The display clears itself when it notices the link has gone.

	Over BLE the disconnect scheduled in close() causes exactly that, so clearing
	ourselves is one packet per external row for nothing -- and each is waited on, on
	NVDA's main thread. Over serial the device cannot tell the host closed the port
	while the cable is still in, so nothing else would clear it.
	"""

	def _driverForTerminate(self, *, ble: bool) -> dotpad_driver.BrailleDisplayDriver:
		driver = _makeDriver()
		driver._isBleConnection = ble
		driver._blockNewWrites = threading.Event()
		driver._renderer = None
		driver._queuedPackets = PriorityQueue()
		driver.textDisplay = MagicMock()
		driver.graphicDisplay = MagicMock()
		driver._queuedPacketsSenderThread = MagicMock()
		driver._queuedPacketsSenderThread.is_alive.return_value = False
		return driver

	def _terminate(self, driver) -> None:
		with (
			patch.object(type(driver), "_teardownLibrarySingleton"),
			patch.object(type(driver), "_waitForQueueDrain", return_value=True),
			patch(f"{_DRIVER_MODULE}.braille.BrailleDisplayDriver.terminate"),
		):
			driver.terminate()

	def test_no_clear_packets_are_queued_over_ble(self) -> None:
		driver = self._driverForTerminate(ble=True)
		# Captured first: terminate() drops these references at step 7.
		textDisplay, graphicDisplay = driver.textDisplay, driver.graphicDisplay

		self._terminate(driver)

		textDisplay.clearForTermination.assert_not_called()
		graphicDisplay.clearForTermination.assert_not_called()

	def test_serial_still_clears_both_displays(self) -> None:
		driver = self._driverForTerminate(ble=False)
		textDisplay, graphicDisplay = driver.textDisplay, driver.graphicDisplay

		self._terminate(driver)

		textDisplay.clearForTermination.assert_called_once_with()
		graphicDisplay.clearForTermination.assert_called_once_with()
