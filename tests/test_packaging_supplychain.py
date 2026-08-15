"""Packaging, Supply Chain, and Zero Runtime Dependency Validation Suite.

Milestone R4 (Phases 31-36, 44-45):
- Pure standard library import audit (Invariant P10).
- pyproject.toml / MANIFEST.in structure & zero runtime dependencies.
- Clean-room build validation (sdist and wheel metadata).
- @codex-rescue/cli NPM pure JS launcher shim security and process semantics.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

# Ensure src/ is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Standard library module names allowlist (built-in + Python 3.11+ stdlib)
STDLIB_ALLOWLIST = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {
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
    "errno",
    "functools",
    "gc",
    "hashlib",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "ntpath",
    "os",
    "pathlib",
    "posixpath",
    "re",
    "shlex",
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
    """Packaging, supply chain, and offline invariant safety audit."""

    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent
        self.src_root = self.repo_root / "src" / "codex_rescue"
        self.npm_root = self.repo_root / "npm-distribution"

    def test_r4_zero_runtime_dependencies_p10_enforced(self) -> None:
        """Verify all production modules under src/codex_rescue/ use ONLY standard library imports (P10)."""
        self.assertTrue(self.src_root.exists(), f"Source root {self.src_root} not found")

        py_files = list(self.src_root.rglob("*.py"))
        self.assertGreater(len(py_files), 0, "No Python source files found in src/codex_rescue")

        for py_file in py_files:
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

    def test_r4_pyproject_toml_structure_and_metadata(self) -> None:
        """Verify pyproject.toml has empty dependencies, correct metadata, and console scripts."""
        pyproject = self.repo_root / "pyproject.toml"
        self.assertTrue(pyproject.exists(), "pyproject.toml not found")
        content = pyproject.read_text(encoding="utf-8")

        # Zero runtime dependencies check
        self.assertIn("dependencies = []", content, "pyproject.toml must declare dependencies = []")

        # Python version requirement >=3.11
        self.assertIn('requires-python = ">=3.11"', content)

        # Name and console script entrypoints
        self.assertIn('name = "codex-rescue"', content)
        self.assertIn('codex-rescue = "codex_rescue.cli:main"', content)

        # Dynamic versioning pointing to codex_rescue.__version__
        self.assertIn('version = {attr = "codex_rescue.__version__"}', content)

        # License definition
        self.assertTrue("license = {text = \"MIT\"}" in content or "license = \"MIT\"" in content)

    def test_r4_manifest_in_inclusion_and_pruning(self) -> None:
        """Verify MANIFEST.in includes required docs and prunes test/scratch/internal directories."""
        manifest = self.repo_root / "MANIFEST.in"
        self.assertTrue(manifest.exists(), "MANIFEST.in not found")
        content = manifest.read_text(encoding="utf-8")

        # Must include critical project files
        self.assertIn("include LICENSE", content)
        self.assertIn("include README.md", content)
        self.assertIn("include CHANGELOG.md", content)
        self.assertIn("include pyproject.toml", content)

        # Must prune non-production directories from sdist
        for prune_dir in ["fixtures", "tests", "real-corpus", ".github", ".agents", ".devcontainer", "npm-distribution"]:
            self.assertIn(f"prune {prune_dir}", content, f"MANIFEST.in missing prune {prune_dir}")

        # Must exclude compiled bytecode
        self.assertIn("global-exclude *.pyc *.pyo __pycache__", content)

    def test_r4_npm_distribution_package_json(self) -> None:
        """Verify @codex-rescue/cli package.json structure, engines, bin entry, and zero dependencies."""
        pkg_json_path = self.npm_root / "package.json"
        self.assertTrue(pkg_json_path.exists(), "npm-distribution/package.json not found")

        with open(pkg_json_path, "r", encoding="utf-8") as f:
            pkg_data = json.load(f)

        self.assertEqual(pkg_data.get("name"), "@codex-rescue/cli")
        self.assertIn("version", pkg_data)
        self.assertEqual(pkg_data.get("bin", {}).get("codex-rescue"), "./bin/codex-rescue.js")
        self.assertEqual(pkg_data.get("files"), ["bin/"])
        self.assertEqual(pkg_data.get("license"), "MIT")
        self.assertTrue(pkg_data.get("private"), "Package should remain marked private until release")

        # Zero runtime dependencies in npm package
        self.assertEqual(pkg_data.get("dependencies", {}), {})

        # No suspicious install lifecycle scripts (e.g. postinstall phone-home)
        scripts = pkg_data.get("scripts", {})
        self.assertNotIn("postinstall", scripts, "postinstall script is forbidden (P10 invariant)")
        self.assertNotIn("preinstall", scripts, "preinstall script is forbidden (P10 invariant)")

    def test_r4_npm_launcher_shim_security_and_p10(self) -> None:
        """Verify codex-rescue.js launcher shim enforces Invariant P10 (zero network/telemetry) and proper piping."""
        shim_path = self.npm_root / "bin" / "codex-rescue.js"
        self.assertTrue(shim_path.exists(), "codex-rescue.js launcher shim not found")
        content = shim_path.read_text(encoding="utf-8")

        # Security check: Forbidden network/telemetry modules & tokens
        forbidden_modules = [
            "http",
            "https",
            "net",
            "dgram",
            "tls",
            "fetch",
            "undici",
            "axios",
            "node-fetch",
            "request",
            "curl",
            "wget",
            "telemetry",
            "analytics",
            "posthog",
            "segment",
            "sentry",
        ]
        for token in forbidden_modules:
            # Check require("token") or require('token')
            self.assertNotRegex(
                content,
                rf'require\s*\(\s*["\']{re.escape(token)}["\']\s*\)',
                f"Forbidden network/telemetry module '{token}' required in launcher shim!",
            )

        # Correctness check: Uses spawnSync with python -m codex_rescue.cli
        self.assertIn("spawnSync", content)
        self.assertIn("codex_rescue.cli", content)
        self.assertIn("stdio: \"inherit\"", content)
        self.assertIn("PYTHONUNBUFFERED", content)
        self.assertIn("process.exit", content)

    def test_r4_npm_launcher_shim_execution(self) -> None:
        """Test executing the pure JS launcher shim via Node.js (if node is available)."""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js runtime not installed on host, skipping JS shim live test")

        shim_path = str(self.npm_root / "bin" / "codex-rescue.js")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.repo_root / "src")

        # 1. Test --help
        res_help = subprocess.run(
            [node_bin, shim_path, "--help"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res_help.returncode, 0, f"Shim --help failed with stderr: {res_help.stderr}")
        self.assertIn("usage: codex-rescue", res_help.stdout)

        # 2. Test --version
        from codex_rescue import __version__

        res_ver = subprocess.run(
            [node_bin, shim_path, "--version"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res_ver.returncode, 0, f"Shim --version failed: {res_ver.stderr}")
        self.assertIn(__version__, res_ver.stdout)

        # 3. Test exit code preservation on CLI usage error (exit code 2)
        res_err = subprocess.run(
            [node_bin, shim_path, "--invalid-flag-test-argument"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res_err.returncode, 2, "Exit code 2 for argparse usage error not preserved")

    def test_r4_zero_credentials_or_secrets_in_production_source(self) -> None:
        """Scan all production source code to ensure zero credentials, tokens, or hardcoded secrets (Invariant P8)."""
        secret_patterns = [
            (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "OpenAI API Key pattern"),
            (re.compile(r"ghp_[a-zA-Z0-9]{20,}"), "GitHub PAT pattern"),
            (re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"), "GitHub Fine-Grained PAT pattern"),
            (re.compile(r"xoxb-[a-zA-Z0-9-]{20,}"), "Slack Token pattern"),
            (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID pattern"),
            (re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"), "Private Key header"),
        ]

        for py_file in self.src_root.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for pattern, name in secret_patterns:
                match = pattern.search(text)
                self.assertIsNone(
                    match,
                    f"Found potential secret matching {name} in {py_file.relative_to(self.repo_root)}: {match.group(0) if match else ''}",
                )

    def test_r4_production_package_structure_completeness(self) -> None:
        """Ensure all required core modules exist in src/codex_rescue/."""
        expected_modules = {
            "__init__.py",
            "artifacts.py",
            "cli.py",
            "discovery.py",
            "doctor.py",
            "fixtures.py",
            "gitstate.py",
            "harness.py",
            "hooks.py",
            "journal.py",
            "reconstruct.py",
            "salvage.py",
            "transcript.py",
            "verify.py",
        }
        actual_modules = {p.name for p in self.src_root.glob("*.py")}
        missing = expected_modules - actual_modules
        self.assertEqual(missing, set(), f"Missing core modules in src/codex_rescue: {missing}")


if __name__ == "__main__":
    unittest.main()
