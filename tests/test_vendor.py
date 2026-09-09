# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Tests for vendor path utilities."""

import importlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
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


class TestAppendPackagePath(unittest.TestCase):
	"""Tests for appendPackagePath, the graft mechanism."""

	def test_reveals_a_submodule_that_lives_in_another_tree(self) -> None:
		"""A submodule under the appended directory becomes importable."""
		from addon.utils.vendor import appendPackagePath

		with tempfile.TemporaryDirectory() as tmpdir:
			root = Path(tmpdir)
			(root / "frozen" / "dotpadFakePkg").mkdir(parents=True)
			(root / "frozen" / "dotpadFakePkg" / "__init__.py").write_text("")
			(root / "extra" / "dotpadFakePkg" / "sub").mkdir(parents=True)
			(root / "extra" / "dotpadFakePkg" / "sub" / "__init__.py").write_text("VALUE = 42")

			with patch.object(sys, "path", [str(root / "frozen"), *sys.path]):
				importlib.invalidate_caches()
				importlib.import_module("dotpadFakePkg")
				try:
					with self.assertRaises(ImportError):
						importlib.import_module("dotpadFakePkg.sub")

					appendPackagePath("dotpadFakePkg", root / "extra" / "dotpadFakePkg")
					importlib.invalidate_caches()

					self.assertEqual(42, importlib.import_module("dotpadFakePkg.sub").VALUE)
				finally:
					for name in [n for n in sys.modules if n.startswith("dotpadFakePkg")]:
						del sys.modules[name]

	def test_is_idempotent(self) -> None:
		"""Appending the same directory twice leaves one entry."""
		from addon.utils.vendor import appendPackagePath

		fake = ModuleType("dotpadFakeIdempotent")
		fake.__path__ = ["/original"]

		with patch.dict(sys.modules, {"dotpadFakeIdempotent": fake}):
			appendPackagePath("dotpadFakeIdempotent", Path("/extra"))
			appendPackagePath("dotpadFakeIdempotent", Path("/extra"))

		self.assertEqual(["/original", str(Path("/extra"))], fake.__path__)

	def test_raises_for_a_module_that_is_not_a_package(self) -> None:
		"""A module without __path__ cannot be grafted onto."""
		from addon.utils.vendor import appendPackagePath

		with patch.dict(sys.modules, {"dotpadFakePlain": ModuleType("dotpadFakePlain")}):
			with self.assertRaises(RuntimeError):
				appendPackagePath("dotpadFakePlain", Path("/extra"))


class TestVendoredWinrtVersion(unittest.TestCase):
	"""Tests that the declared winrt version tracks what is actually vendored."""

	def test_matches_the_locked_winrt_runtime(self) -> None:
		"""A bleak bump that pulls a new winrt must not leave the version gate lying."""
		import tomllib

		from addon.utils.vendor import VENDORED_WINRT_VERSION

		repoRoot = Path(__file__).resolve().parent.parent
		lock = tomllib.loads((repoRoot / "uv.lock").read_text(encoding="utf-8"))
		locked = [p for p in lock["package"] if p["name"] == "winrt-runtime"]

		self.assertEqual(1, len(locked), "winrt-runtime is not in uv.lock")
		self.assertEqual(locked[0]["version"], VENDORED_WINRT_VERSION)


class TestEnsureWinrtCollections(unittest.TestCase):
	"""Tests for completing NVDA's winrt projections."""

	def setUp(self) -> None:
		import addon.utils.vendor as vendorModule

		vendorModule._winrtCollectionsGrafted = False

	def tearDown(self) -> None:
		import addon.utils.vendor as vendorModule

		vendorModule._winrtCollectionsGrafted = False

	def _fakeWinrtModules(self) -> dict[str, ModuleType]:
		"""Return stand-ins for the packages NVDA's frozen build does ship."""
		winrt = ModuleType("winrt")
		winrt.__path__ = ["/frozen/winrt"]
		foundation = ModuleType("winrt.windows.foundation")
		foundation.__path__ = ["/frozen/winrt/windows/foundation"]
		return {"winrt": winrt, "winrt.windows.foundation": foundation}

	def test_does_nothing_when_the_module_is_already_there(self) -> None:
		"""A build that ships the module is left untouched."""
		import addon.utils.vendor as vendorModule

		with patch.object(vendorModule, "getVendorPath") as getVendorPath:
			with patch.object(vendorModule.importlib, "import_module") as importModule:
				vendorModule.ensureWinrtCollections()

		importModule.assert_called_once_with("winrt.windows.foundation.collections")
		getVendorPath.assert_not_called()
		self.assertFalse(vendorModule._winrtCollectionsGrafted)

	def test_grafts_the_vendored_copy_when_it_is_missing(self) -> None:
		"""Both package paths gain the vendored tree, then the import is retried."""
		import addon.utils.vendor as vendorModule

		modules = self._fakeWinrtModules()
		imports: list[str] = []

		def importModule(name: str) -> ModuleType:
			imports.append(name)
			if len(imports) == 1:
				raise ModuleNotFoundError(f"No module named {name!r}")
			return ModuleType(name)

		with tempfile.TemporaryDirectory() as tmpdir:
			with patch.dict(sys.modules, modules):
				with patch.object(vendorModule, "getVendorPath", return_value=Path(tmpdir)):
					with patch.object(
						vendorModule,
						"_getWinrtRuntimeVersion",
						return_value=vendorModule.VENDORED_WINRT_VERSION,
					):
						with patch.object(vendorModule.importlib, "import_module", importModule):
							vendorModule.ensureWinrtCollections()

			winrtDir = Path(tmpdir) / "winrt"
			self.assertEqual(["/frozen/winrt", str(winrtDir)], modules["winrt"].__path__)
			self.assertEqual(
				["/frozen/winrt/windows/foundation", str(winrtDir / "windows" / "foundation")],
				modules["winrt.windows.foundation"].__path__,
			)

		self.assertEqual(["winrt.windows.foundation.collections"] * 2, imports)
		self.assertTrue(vendorModule._winrtCollectionsGrafted)

	def test_refuses_to_graft_onto_a_different_winrt_runtime(self) -> None:
		"""Mismatched projections would crash the process, so nothing is touched."""
		import addon.utils.vendor as vendorModule

		modules = self._fakeWinrtModules()

		def importModule(name: str) -> ModuleType:
			raise ModuleNotFoundError(f"No module named {name!r}")

		with patch.dict(sys.modules, modules):
			with patch.object(vendorModule, "getVendorPath") as getVendorPath:
				with patch.object(vendorModule, "_getWinrtRuntimeVersion", return_value="9.9.9"):
					with patch.object(vendorModule.importlib, "import_module", importModule):
						vendorModule.ensureWinrtCollections()

		getVendorPath.assert_not_called()
		self.assertEqual(["/frozen/winrt"], modules["winrt"].__path__)
		self.assertFalse(vendorModule._winrtCollectionsGrafted)

	def test_does_nothing_without_a_frozen_winrt_to_complete(self) -> None:
		"""No winrt at all is not something this graft can repair."""
		import addon.utils.vendor as vendorModule

		def importModule(name: str) -> ModuleType:
			raise ModuleNotFoundError(f"No module named {name!r}")

		with patch.dict(sys.modules):
			for name in [n for n in sys.modules if n == "winrt" or n.startswith("winrt.")]:
				del sys.modules[name]
			with patch.object(vendorModule, "getVendorPath") as getVendorPath:
				with patch.object(vendorModule.importlib, "import_module", importModule):
					vendorModule.ensureWinrtCollections()

		getVendorPath.assert_not_called()
		self.assertFalse(vendorModule._winrtCollectionsGrafted)


if __name__ == "__main__":
	unittest.main()
