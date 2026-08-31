#!/usr/bin/env python
# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Download and organize vendored dependencies for all target platforms.

This script downloads platform-specific wheels for vendored dependencies
and extracts them into the appropriate addon/_vendor/{platform}/ directories.

Usage:
    uv run --group vendor --with pip python build_vendor.py

``pip`` is required because ``uv`` has no ``download`` subcommand and uv-managed
virtualenvs do not ship pip, hence the explicit ``--with pip``.

The list of packages to vendor is read from pyproject.toml's
[dependency-groups] vendor section.
"""

import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import TypedDict, cast

from addon.utils.vendor import VENDOR_TARGETS

VENDOR_DIR = Path("addon/_vendor")
TEMP_DIR = Path(".vendor_build")


class Target(TypedDict):
	python: str
	arch: str
	subdir: str


def getPackages() -> list[str]:
	"""Read vendored packages from pyproject.toml.

	Returns:
		List of requirement strings, version specifiers included. The specifiers
		are kept deliberately: stripping them made ``pip download`` fetch whatever
		version was newest on PyPI rather than the pinned one, so the vendored tree
		did not match ``[dependency-groups] vendor``.
	"""
	with open("pyproject.toml", "rb") as f:
		pyproject = tomllib.load(f)

	vendorDeps = cast("list[str]", pyproject.get("dependency-groups", {}).get("vendor", []))
	if not vendorDeps:
		print("Warning: No packages found in [dependency-groups] vendor")
		return []

	return [pkg.strip() for pkg in vendorDeps]


def downloadWheels(target: Target, outputDir: Path, packages: list[str]) -> None:
	"""Download wheels for a specific platform.

	Args:
		target: Target platform configuration (Target TypedDict) with keys:
			python (str), arch (str), subdir (str).
		outputDir: Directory to download wheels into.
		packages: List of package names to download.
	"""
	outputDir.mkdir(parents=True, exist_ok=True)

	# Use pip download (uv pip doesn't have download subcommand)
	cmd = [
		sys.executable,
		"-m",
		"pip",
		"download",
		*packages,
		"--python-version",
		target["python"],
		"--platform",
		target["arch"],
		"--only-binary",
		":all:",
		"-d",
		str(outputDir),
	]

	print(f"  Running: {' '.join(cmd)}")
	subprocess.run(cmd, check=True)


def extractWheels(wheelsDir: Path, targetDir: Path) -> None:
	"""Extract all wheels into the target directory.

	Args:
		wheelsDir: Directory containing .whl files.
		targetDir: Directory to extract packages into.
	"""
	targetDir.mkdir(parents=True, exist_ok=True)

	for wheel in wheelsDir.glob("*.whl"):
		print(f"  Extracting: {wheel.name}")
		with zipfile.ZipFile(wheel) as zf:
			zf.extractall(targetDir)


def cleanup(targetDir: Path) -> None:
	"""Remove unnecessary files to minimize add-on size.

	License texts are rescued before the ``*.dist-info`` directories carrying them
	are deleted. MIT, BSD and PSF all require the notice to travel with the
	redistributed code, so discarding it would leave the vendored copies
	non-compliant. Each package's notices land in ``_licenses/<package>/`` beside
	the vendored code, which is also what ``THIRD_PARTY_NOTICES.md`` points at.

	Args:
		targetDir: Directory to clean up.
	"""
	# str.startswith() takes a tuple, so this matches LICENSE, LICENSE.txt,
	# LICENSE-APACHE, COPYING.LESSER and friends in one test.
	licensePrefixes = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")
	licensesDir = targetDir / "_licenses"

	for distInfo in targetDir.rglob("*.dist-info"):
		if not distInfo.is_dir():
			continue
		# "bleak-3.0.2.dist-info" -> "bleak-3.0.2"
		packageDir = licensesDir / distInfo.name.removesuffix(".dist-info")
		for path in distInfo.rglob("*"):
			if not path.is_file() or not path.name.upper().startswith(licensePrefixes):
				continue
			packageDir.mkdir(parents=True, exist_ok=True)
			shutil.copy2(path, packageDir / path.name)
			print(f"  Kept license: {packageDir.name}/{path.name}")

	patternsToRemove = ["*.dist-info", "__pycache__"]

	for pattern in patternsToRemove:
		for path in targetDir.rglob(pattern):
			if path.is_dir():
				shutil.rmtree(path)
				print(f"  Removed: {path}")


def main() -> None:
	"""Main entry point for the build script."""
	packages = getPackages()
	if not packages:
		print(
			"No packages to vendor. Add packages to [project.optional-dependencies] vendor in pyproject.toml",
		)
		sys.exit(1)

	print(f"Vendoring packages: {', '.join(packages)}")
	print(f"Target platforms: {', '.join(t['subdir'] for t in VENDOR_TARGETS)}")
	print()

	# Clean existing vendor directory
	if VENDOR_DIR.exists():
		print(f"Removing existing {VENDOR_DIR}")
		shutil.rmtree(VENDOR_DIR)

	# Clean temp directory if it exists
	if TEMP_DIR.exists():
		shutil.rmtree(TEMP_DIR)

	for target in VENDOR_TARGETS:
		subdir = target["subdir"]
		print(f"Building for {subdir}...")

		wheelsDir = TEMP_DIR / subdir
		targetDir = VENDOR_DIR / subdir

		downloadWheels(target, wheelsDir, packages)
		extractWheels(wheelsDir, targetDir)
		cleanup(targetDir)
		print()

	# Clean up temp directory
	print("Cleaning up temporary files...")
	shutil.rmtree(TEMP_DIR)

	print("Done!")
	print(f"Vendor packages installed to: {VENDOR_DIR.absolute()}")


if __name__ == "__main__":
	main()
