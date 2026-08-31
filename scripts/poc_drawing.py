# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Proof-of-concept: jdpGraphics drawing primitives via registration-free COM.

This script validates that the COM object can be created and drawing
methods can be called. Uses direct vtable calls (early binding) on the
IJDPGraphics dual interface.

Run from the repository root:
    uv run python scripts/poc_drawing.py
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

# Add addon directory to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def main() -> None:
	# Initialize COM as STA (jdpGraphics uses Apartment threading)
	ctypes.windll.ole32.CoInitializeEx(None, 0x2)

	print("=== jdpGraphics Drawing Primitives PoC ===\n")

	# Step 1: Test COM object creation via direct vtable binding
	print("1. Creating COM object via registration-free COM (early binding)...")
	try:
		from addon.jdpGraphics.comLoader import create_jdp_graphics, release_com_object

		ptr, vtbl, dll = create_jdp_graphics()
		print(f"   OK: IJDPGraphics object created at 0x{ptr:016X}")
		print(f"   OK: DLL loaded from {dll._name}")
		release_com_object(ptr, vtbl)
	except FileNotFoundError as e:
		print(f"   FAIL: {e}")
		return
	except OSError as e:
		print(f"   FAIL: COM creation error: {e}")
		return

	# Step 2: Test typed wrapper with drawing primitives
	print("\n2. Testing typed wrapper with drawing primitives...")
	from addon.jdpGraphics.wrapper import DPFillKind, JDPGraphics

	try:
		jdp = JDPGraphics()
		jdp._ensure_initialized()
		print("   OK: Wrapper initialized")
	except Exception as e:
		print(f"   FAIL: Wrapper init: {e}")
		return

	drawing_tests: list[tuple[str, object]] = [
		("Clear()", lambda: jdp.clear()),
		("DrawLine(0, 0, 59, 39)", lambda: jdp.draw_line(0, 0, 59, 39)),
		("DrawBox(5, 5, 20, 15)", lambda: jdp.draw_box(5, 5, 20, 15)),
		("DrawCircle(30, 20, 10)", lambda: jdp.draw_circle(30, 20, 10)),
		("DrawPoly(30, 20, 8, 6, 0)", lambda: jdp.draw_poly(30, 20, 8, 6, 0)),
		("Fill(15, 10, SOLID)", lambda: jdp.fill(15, 10, DPFillKind.SOLID)),
		("InvertRect(0, 0, 10, 10)", lambda: jdp.invert_rect(0, 0, 10, 10)),
		("DrawBrailleLabel(0, 0, braille)", lambda: jdp.draw_braille_label(0, 0, "\u2801\u2803")),
		("DrawTextLabel(4, 4, 'Circle')", lambda: jdp.draw_text_label(4, 4, "Circle")),
		("ShowMultilineText('hello world')", lambda: jdp.show_multiline_text("hello world")),
		("GraphMathEquation('x^2')", lambda: jdp.graph_math_equation("x^2")),
		("UndoLastDraw()", lambda: jdp.undo_last_draw()),
	]

	passed = 0
	failed = 0
	for name, test_fn in drawing_tests:
		try:
			test_fn()  # type: ignore[operator]
			print(f"   OK: {name}")
			passed += 1
		except Exception as e:
			print(f"   FAIL: {name} -> {e}")
			failed += 1

	# Step 3: Test connection (only with physical device)
	print("\n3. Testing device connection (requires physical DotPad)...")
	from addon.jdpGraphics.wrapper import DPConnectionPreference

	try:
		result = jdp.connect(DPConnectionPreference.AUTO)
		if result == 0:
			print("   OK: Connected to DotPad")
			width, height = jdp.get_dimensions()
			print(f"   OK: Display dimensions = {width}x{height} dots")
			jdp.clear()
			jdp.draw_line(0, 0, width - 1, height - 1)
			jdp.draw_box(0, 0, width, height)
			jdp.show()
			print("   OK: Drew diagonal line + border on device")
			jdp.disconnect()
			print("   OK: Disconnected")
		else:
			print(f"   SKIP: Connect returned {result} (no device?)")
	except Exception as e:
		print(f"   SKIP: {e}")

	# Cleanup
	jdp.close()

	# Summary
	print(f"\n=== Results: {passed} passed, {failed} failed ===")
	if failed == 0:
		print("All drawing primitives work!")

	ctypes.windll.ole32.CoUninitialize()


if __name__ == "__main__":
	main()
