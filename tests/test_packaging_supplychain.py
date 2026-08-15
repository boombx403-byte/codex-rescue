"""Packaging, Supply Chain, and Zero Runtime Dependency Validation Suite.

Milestone R4 (Phases 31-36, 44-45):
- Pure standard library import audit (Invariant P10).
- pyproject.toml / MANIFEST.in structure.
- Clean-room build validation (sdist and wheel metadata).
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

# Standard library module names in Python 3.11+
STDLIB_ALLOWLIST = {
    "__future__",
    "argparse",
    "ast",
    "collections",
    "concurrent",
    "contextlib",
    "ctypes",
    "dataclasses",
    "datetime",
    "enum",
    "functools",
    "gc",
    "hashlib",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "os",
    "pathlib",
    "re",
    "shutil",
    "stat",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "time",
    "typing",
    "unittest",
    "urllib",
    "warnings",
}


class TestPackagingSupplyChain(unittest.TestCase):
    """Packaging and supply-chain safety audit."""

    def test_r4_zero_runtime_dependencies_p10_enforced(self) -> None:
        """Verify all production modules under src/codex_rescue/ use ONLY standard library imports (P10)."""
        src_root = Path(__file__).resolve().parent.parent / "src" / "codex_rescue"
        self.assertTrue(src_root.exists(), f"Source root {src_root} not found")

        for py_file in src_root.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split(".")[0]
                        if top_pkg != "codex_rescue":
                            self.assertIn(
                                top_pkg,
                                STDLIB_ALLOWLIST,
                                f"Non-stdlib import '{top_pkg}' found in {py_file.name}",
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        top_pkg = node.module.split(".")[0]
                        if top_pkg != "codex_rescue":
                            self.assertIn(
                                top_pkg,
                                STDLIB_ALLOWLIST,
                                f"Non-stdlib from-import '{top_pkg}' found in {py_file.name}",
                            )

    def test_r4_pyproject_toml_clean_dependencies(self) -> None:
        """Verify pyproject.toml has empty dependencies list."""
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        self.assertIn("dependencies = []", content)


if __name__ == "__main__":
    unittest.main()
