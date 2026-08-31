# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Proof-of-concept: Image display via jdpGraphics.

Requires a physical DotPad device connected and a sample image file.

Run from the repository root:
    uv run python scripts/poc_image.py [image_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def main() -> None:
	print("=== jdpGraphics Image Display PoC ===\n")

	# Check for image argument
	if len(sys.argv) > 1:
		image_path = sys.argv[1]
	else:
		# Use the sample image from the jdpGraphics distribution
		import os

		temp_image = os.path.join(
			os.environ.get("TEMP", "/tmp"),
			"jdpGraphics",
			"jdpGraphics 1.05",
			"joeDotpadSample.jpg",
		)
		if Path(temp_image).exists():
			image_path = temp_image
		else:
			print("Usage: python scripts/poc_image.py <image_path>")
			print("No image provided and sample not found at expected location.")
			return

	print(f"Image: {image_path}")

	from addon.jdpGraphics.wrapper import DPConnectionPreference, JDPGraphics

	with JDPGraphics() as jdp:
		print("Connecting to DotPad...")
		result = jdp.connect(DPConnectionPreference.AUTO)
		if result != 0:
			print(f"FAIL: Connect returned {result} (no device?)")
			return

		width, height = jdp.get_dimensions()
		print(f"Connected: {width}x{height} dots")

		# Test different magnification levels
		magnifications = [1.0, 2.0, 0.5]
		for mag in magnifications:
			print(f"\nDisplaying image at {mag}x magnification...")
			try:
				jdp.clear()
				jdp.draw_image(image_path, "", mag)
				jdp.show()
				print("  OK: Displayed on device")
				input("  Press Enter to continue...")
			except Exception as e:
				print(f"  FAIL: {e}")

		jdp.disconnect()
		print("\nDone.")


if __name__ == "__main__":
	main()
