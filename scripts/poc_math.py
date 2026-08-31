# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Proof-of-concept: Math equation rendering via jdpGraphics.

Requires a physical DotPad device connected.

Run from the repository root:
    uv run python scripts/poc_math.py
"""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def main() -> None:
	print("=== jdpGraphics Math Equation PoC ===\n")

	from addon.jdpGraphics.wrapper import DPConnectionPreference, JDPGraphics

	with JDPGraphics() as jdp:
		print("Connecting to DotPad...")
		result = jdp.connect(DPConnectionPreference.AUTO)
		if result != 0:
			print(f"FAIL: Connect returned {result} (no device?)")
			return

		width, height = jdp.get_dimensions()
		print(f"Connected: {width}x{height} dots")

		# Test equations
		equations = [
			("x^2", -10, 10, 5, True),
			("sin(x)", -6.28, 6.28, 5, True),
			("x^3 - 3*x", -5, 5, 5, True),
		]

		for expr, x_min, x_max, dots_per_tick, show_label in equations:
			print(f"\nGraphing: {expr} [{x_min}, {x_max}]")
			try:
				jdp.clear()
				jdp.graph_math_equation(expr, x_min, x_max, dots_per_tick, show_label)
				jdp.show()
				print("  OK: Displayed on device")
				input("  Press Enter to continue to next equation...")
			except Exception as e:
				print(f"  FAIL: {e}")

		jdp.disconnect()
		print("\nDone.")


if __name__ == "__main__":
	main()
