# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Proof-of-concept: Device handoff between NVDA and jdpGraphics.

This script must be run as an NVDA script (e.g., from a global plugin
command) since it needs access to braille.handler.

Sequence:
1. NVDA releases device via setDisplayByName("noBraille")
2. jdpGraphics connects and draws something
3. jdpGraphics disconnects
4. NVDA reconnects via setDisplayByName("dotPad")

Run from NVDA Python console or bind to a gesture in globalPlugins.
"""

from __future__ import annotations

import time


def handoff_poc() -> None:
	"""Execute the full device handoff proof of concept.

	Must be called from NVDA's main thread (e.g., script handler).
	"""
	import braille

	timings: dict[str, float] = {}

	# Step 1: Release device
	print("Step 1: Releasing device from NVDA...")
	t0 = time.perf_counter()
	braille.handler.setDisplayByName("noBraille", isFallback=True)
	timings["release"] = time.perf_counter() - t0
	print(f"  Released in {timings['release']:.3f}s")

	# Step 2: Connect jdpGraphics
	print("Step 2: Connecting jdpGraphics...")
	t0 = time.perf_counter()
	try:
		from addon.jdpGraphics.wrapper import DPConnectionPreference, JDPGraphics

		jdp = JDPGraphics()
		jdp._ensure_initialized()
		timings["com_init"] = time.perf_counter() - t0
		print(f"  COM init in {timings['com_init']:.3f}s")

		t0 = time.perf_counter()
		result = jdp.connect(DPConnectionPreference.AUTO)
		timings["connect"] = time.perf_counter() - t0

		if result != 0:
			print(f"  FAIL: Connect returned {result}")
			jdp.close()
			_restore_nvda(timings)
			return

		print(f"  Connected in {timings['connect']:.3f}s")

		# Step 3: Draw and show
		print("Step 3: Drawing test pattern...")
		t0 = time.perf_counter()
		width, height = jdp.get_dimensions()
		jdp.clear()
		jdp.draw_box(0, 0, width, height)
		jdp.draw_line(0, 0, width - 1, height - 1)
		jdp.draw_line(width - 1, 0, 0, height - 1)
		jdp.show()
		timings["draw_show"] = time.perf_counter() - t0
		print(f"  Drew and showed in {timings['draw_show']:.3f}s")

		# Wait for user to feel the display
		print("  (waiting 3s for tactile inspection)")
		time.sleep(3)

		# Step 4: Disconnect jdpGraphics
		print("Step 4: Disconnecting jdpGraphics...")
		t0 = time.perf_counter()
		jdp.disconnect()
		jdp.close()
		timings["disconnect"] = time.perf_counter() - t0
		print(f"  Disconnected in {timings['disconnect']:.3f}s")

	except Exception as e:
		print(f"  FAIL: {e}")
		timings["error"] = time.perf_counter() - t0

	# Step 5: Restore NVDA
	_restore_nvda(timings)

	# Summary
	print("\n=== Timing Summary ===")
	total = sum(v for k, v in timings.items() if k != "error")
	for name, duration in timings.items():
		print(f"  {name}: {duration:.3f}s")
	print(f"  TOTAL round-trip: {total:.3f}s")


def _restore_nvda(timings: dict[str, float]) -> None:
	"""Restore NVDA braille display."""
	import braille

	print("Step 5: Restoring NVDA braille...")
	t0 = time.perf_counter()
	braille.handler.setDisplayByName("dotPad", isFallback=False)
	timings["restore"] = time.perf_counter() - t0
	print(f"  Restored in {timings['restore']:.3f}s")
