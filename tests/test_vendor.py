# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for vendor path utilities."""

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestGetVendorSubdir(unittest.TestCase):
	"""Tests for getVendorSubdir function."""

	def test_returns_string_with_python_version_and_arch(self) -> None:
		"""Should return format like cp311_win32 or cp313_win_amd64."""
		from addon.utils.vendor import getVendorSubdir

		result = getVendorSubdir()

		self.assertIsInstance(result, str)
		self.assertRegex(result, r"^cp\d+_win(32|_amd64)$")

	def test_includes_current_python_version(self) -> None:
		"""Should include current Python major.minor version."""
		from addon.utils.vendor import getVendorSubdir

		result = getVendorSubdir()
		expectedVersion = f"cp{sys.version_info.major}{sys.version_info.minor}"

		self.assertTrue(result.startswith(expectedVersion))

	def test_includes_current_architecture(self) -> None:
		"""Should include current architecture (win32 or win_amd64)."""
		from addon.utils.vendor import getVendorSubdir

		result = getVendorSubdir()
		bits = struct.calcsize("P") * 8
		expectedArch = "win32" if bits == 32 else "win_amd64"

		self.assertTrue(result.endswith(expectedArch))


class TestVendorTargets(unittest.TestCase):
	"""Tests for VENDOR_TARGETS configuration."""

	def test_vendor_targets_is_tuple(self) -> None:
		"""VENDOR_TARGETS should be an immutable tuple."""
		from addon.utils.vendor import VENDOR_TARGETS

		self.assertIsInstance(VENDOR_TARGETS, tuple)

	def test_vendor_targets_contains_required_platforms(self) -> None:
		"""Only 64-bit Python 3.13 is vendored: every supported NVDA (2026.1+) uses it."""
		from addon.utils.vendor import VENDOR_TARGETS

		subdirs = [t["subdir"] for t in VENDOR_TARGETS]

		self.assertEqual(["cp313_win_amd64"], subdirs)

	def test_each_target_has_required_keys(self) -> None:
		"""Each target should have python, arch, and subdir keys."""
		from addon.utils.vendor import VENDOR_TARGETS

		for target in VENDOR_TARGETS:
			self.assertIn("python", target)
			self.assertIn("arch", target)
			self.assertIn("subdir", target)


class TestSupportedPlatforms(unittest.TestCase):
	"""Tests for SUPPORTED_PLATFORMS constant."""

	def test_supported_platforms_is_tuple(self) -> None:
		"""SUPPORTED_PLATFORMS should be an immutable tuple."""
		from addon.utils.vendor import SUPPORTED_PLATFORMS

		self.assertIsInstance(SUPPORTED_PLATFORMS, tuple)

	def test_supported_platforms_derived_from_vendor_targets(self) -> None:
		"""SUPPORTED_PLATFORMS should match subdirs from VENDOR_TARGETS."""
		from addon.utils.vendor import SUPPORTED_PLATFORMS, VENDOR_TARGETS

		expectedPlatforms = tuple(t["subdir"] for t in VENDOR_TARGETS)

		self.assertEqual(SUPPORTED_PLATFORMS, expectedPlatforms)


class TestEnsureVendorPath(unittest.TestCase):
	"""Tests for ensureVendorPath function."""

	def setUp(self) -> None:
		"""Reset vendor path initialization state before each test."""
		import addon.utils.vendor as vendorModule

		vendorModule._vendorPathInitialized = False

	def tearDown(self) -> None:
		"""Clean up sys.path after each test."""
		import addon.utils.vendor as vendorModule

		vendorModule._vendorPathInitialized = False

	def test_adds_vendor_path_to_sys_path(self) -> None:
		"""Should add the platform-specific vendor directory to sys.path."""
		from addon.utils.vendor import ensureVendorPath, getVendorSubdir

		with tempfile.TemporaryDirectory() as tmpdir:
			# Create mock addon structure
			vendorSubdir = getVendorSubdir()
			vendorPath = Path(tmpdir) / "_vendor" / vendorSubdir
			vendorPath.mkdir(parents=True)

			mockAddon = MagicMock()
			mockAddon.path = tmpdir

			with patch("addonHandler.getCodeAddon", return_value=mockAddon):
				with patch.object(sys, "path", sys.path.copy()):
					ensureVendorPath()

					self.assertIn(str(vendorPath), sys.path)

	def test_is_idempotent(self) -> None:
		"""Should only add path once even if called multiple times."""
		from addon.utils.vendor import ensureVendorPath, getVendorSubdir

		with tempfile.TemporaryDirectory() as tmpdir:
			vendorSubdir = getVendorSubdir()
			vendorPath = Path(tmpdir) / "_vendor" / vendorSubdir
			vendorPath.mkdir(parents=True)

			mockAddon = MagicMock()
			mockAddon.path = tmpdir

			with patch("addonHandler.getCodeAddon", return_value=mockAddon):
				testPath: list[str] = []
				with patch.object(sys, "path", testPath):
					ensureVendorPath()
					ensureVendorPath()
					ensureVendorPath()

					pathCount = testPath.count(str(vendorPath))
					self.assertEqual(pathCount, 1)

	def test_raises_error_for_unsupported_platform(self) -> None:
		"""Should raise RuntimeError for unsupported platforms."""
		from addon.utils.vendor import ensureVendorPath

		mockAddon = MagicMock()
		mockAddon.path = "/fake/path"

		with patch("addonHandler.getCodeAddon", return_value=mockAddon):
			with patch("addon.utils.vendor.getVendorSubdir", return_value="cp399_win128"):
				with self.assertRaises(RuntimeError) as context:
					ensureVendorPath()

				self.assertIn("cp399_win128", str(context.exception))
				self.assertIn("does not support", str(context.exception))

	def test_raises_error_if_vendor_directory_missing(self) -> None:
		"""Should raise RuntimeError if vendor directory doesn't exist."""
		from addon.utils.vendor import ensureVendorPath

		with tempfile.TemporaryDirectory() as tmpdir:
			# Don't create the vendor directory
			mockAddon = MagicMock()
			mockAddon.path = tmpdir

			with patch("addonHandler.getCodeAddon", return_value=mockAddon):
				with self.assertRaises(RuntimeError) as context:
					ensureVendorPath()

				self.assertIn("not found", str(context.exception))


if __name__ == "__main__":
	unittest.main()
