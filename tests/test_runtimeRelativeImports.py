# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""The add-on is not one package at runtime, so parent-relative imports need a guard.

NVDA loads each add-on module on its own, as ``addons.dotpad.<module>``; the parent
package has no ``__path__`` covering the rest of the add-on. A module-level
``from ..other.thing import name`` therefore raises ``ModuleNotFoundError`` unless
something else happens to have loaded ``other`` first, which nothing guarantees. The
suite cannot catch that by importing the code, because it puts the repo root on
``sys.path``, where every relative path resolves.

Acceptable at module level: an import guarded by ``TYPE_CHECKING`` or
``IS_UNDER_UNITTEST``, or one wrapped in ``try`` / ``except ImportError``. Everything
else belongs in ``addonHandler.getCodeAddon().loadModule(...)``.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent.parent / "addon"

GUARD_NAMES = {"TYPE_CHECKING", "IS_UNDER_UNITTEST"}


def _isGuardTest(test: ast.expr) -> bool:
	"""Whether an ``if`` test names one of the guards that keep an import off NVDA."""
	return any(isinstance(node, ast.Name) and node.id in GUARD_NAMES for node in ast.walk(test))


def _catchesImportError(node: ast.Try) -> bool:
	"""Whether a ``try`` has a handler that would swallow a failed import."""
	for handler in node.handlers:
		if handler.type is None:
			return True
		names = {n.id for n in ast.walk(handler.type) if isinstance(n, ast.Name)}
		if names & {"ImportError", "ModuleNotFoundError", "Exception"}:
			return True
	return False


def _unguardedParentRelativeImports(source: str) -> list[int]:
	"""Line numbers of module-level parent-relative imports that reach NVDA unguarded."""
	found: list[int] = []
	stack: list[tuple[ast.AST, bool]] = [(ast.parse(source), False)]
	while stack:
		node, guarded = stack.pop()
		for child in ast.iter_child_nodes(node):
			childGuarded = guarded
			if isinstance(child, ast.If) and _isGuardTest(child.test):
				childGuarded = True
			elif isinstance(child, ast.Try) and _catchesImportError(child):
				childGuarded = True
			elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
				# Deferred to call time, by which point the loader has run.
				childGuarded = True
			if isinstance(child, ast.ImportFrom) and child.level >= 2 and not childGuarded:
				found.append(child.lineno)
			stack.append((child, childGuarded))
	return found


class TestNoUnguardedParentRelativeImports(unittest.TestCase):
	def test_addon_source_reaches_other_packages_through_the_loader(self) -> None:
		offenders: list[str] = []
		for path in sorted(ADDON_DIR.rglob("*.py")):
			if "_vendor" in path.parts:
				continue
			for line in _unguardedParentRelativeImports(path.read_text(encoding="utf-8")):
				offenders.append(f"{path.relative_to(ADDON_DIR)}:{line}")
		self.assertEqual(
			[],
			offenders,
			"use addonHandler.getCodeAddon().loadModule(...) for these, or guard them",
		)


class TestTheCheckItself(unittest.TestCase):
	"""The check is only worth having if it fails on the shape that broke at runtime."""

	def test_an_unguarded_import_is_reported(self) -> None:
		self.assertEqual([1], _unguardedParentRelativeImports("from ..compat.thing import name\n"))

	def test_a_sibling_import_is_not(self) -> None:
		self.assertEqual([], _unguardedParentRelativeImports("from .sibling import name\n"))

	def test_a_type_checking_import_is_not(self) -> None:
		source = "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n\tfrom ..compat.thing import name\n"
		self.assertEqual([], _unguardedParentRelativeImports(source))

	def test_an_import_error_fallback_is_not(self) -> None:
		source = "try:\n\tfrom ..utils.testing import IS_UNDER_UNITTEST\nexcept ImportError:\n\tIS_UNDER_UNITTEST = False\n"
		self.assertEqual([], _unguardedParentRelativeImports(source))

	def test_a_function_level_import_is_not(self) -> None:
		source = "def f():\n\tfrom ..compat.thing import name\n\treturn name\n"
		self.assertEqual([], _unguardedParentRelativeImports(source))


if __name__ == "__main__":
	unittest.main()
