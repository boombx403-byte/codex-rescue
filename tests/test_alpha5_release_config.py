from __future__ import annotations

import json
import unittest
from pathlib import Path

from codex_rescue import __version__


ROOT = Path(__file__).resolve().parent.parent
NPM_VERSION = "0.1.0-alpha.5"
PYTHON_VERSION = "0.1.0a5"
TAG = "v0.1.0-alpha.5"
PLATFORM_PACKAGES = {
    "linux-x64": ("codex-rescue-linux-x64", "linux", "x64", "bin/codex-rescue"),
    "win32-x64": ("codex-rescue-win32-x64", "win32", "x64", "bin/codex-rescue.exe"),
    "darwin-arm64": ("codex-rescue-darwin-arm64", "darwin", "arm64", "bin/codex-rescue"),
    "darwin-x64": ("codex-rescue-darwin-x64", "darwin", "x64", "bin/codex-rescue"),
}


class Alpha5ReleaseConfigTests(unittest.TestCase):
    def test_version_and_npm_package_mapping_is_exact(self) -> None:
        self.assertEqual(__version__, PYTHON_VERSION)
        meta = json.loads((ROOT / "npm/codex-rescue/package.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "codex-rescue")
        self.assertEqual(meta["version"], NPM_VERSION)
        self.assertEqual(meta["files"], ["bin/codex-rescue.js", "README.md"])
        self.assertEqual(
            meta["optionalDependencies"],
            {name: NPM_VERSION for name, _, _, _ in PLATFORM_PACKAGES.values()},
        )

        seen: set[str] = set()
        for platform_id, (name, os_name, cpu, binary) in PLATFORM_PACKAGES.items():
            package = json.loads(
                (ROOT / f"npm/platforms/{platform_id}/package.json").read_text(encoding="utf-8")
            )
            seen.add(package["name"])
            self.assertEqual(package["name"], name)
            self.assertEqual(package["version"], NPM_VERSION)
            self.assertEqual(package["os"], [os_name])
            self.assertEqual(package["cpu"], [cpu])
            self.assertEqual(package["files"], [binary, "README.md"])
            self.assertNotIn("scripts", package)
        self.assertEqual(seen, {value[0] for value in PLATFORM_PACKAGES.values()})

    def test_alpha5_publish_workflow_is_manual_exact_and_least_privilege_by_default(self) -> None:
        text = (ROOT / ".github/workflows/alpha5-publish.yml").read_text(encoding="utf-8")
        trigger = text.split("permissions:", 1)[0]
        default_permissions = text.split("permissions:", 1)[1].split("env:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger)
        self.assertNotIn("\n  push:", trigger)
        self.assertNotIn("\n  pull_request:", trigger)
        self.assertIn("contents: read", default_permissions)
        self.assertNotIn("id-token: write", default_permissions)
        self.assertIn(f"EXPECTED_TAG: {TAG}", text)
        self.assertIn(f"EXPECTED_PYTHON_VERSION: {PYTHON_VERSION}", text)
        self.assertIn(f"EXPECTED_NPM_VERSION: {NPM_VERSION}", text)
        self.assertIn("candidate_run_id:", text)
        self.assertIn("candidate run head SHA mismatch", text)
        self.assertIn("GitHub asset digest mismatch", text)
        self.assertIn("STOP: PyPI codex-rescue 0.1.0a5 already exists", text)
        self.assertIn("npm whoami", text)
        self.assertIn("publish-npm-meta:", text)
        self.assertIn("needs: publish-npm-platforms", text)
        self.assertIn(
            "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
            text,
        )

    def test_release_candidate_is_manual_and_requires_exact_artifact_set(self) -> None:
        text = (ROOT / ".github/workflows/alpha5-release-candidate.yml").read_text(encoding="utf-8")
        trigger = text.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger)
        self.assertNotIn("\n  push:", trigger)
        self.assertNotIn("\n  pull_request:", trigger)
        self.assertIn(f"EXPECTED_TAG: {TAG}", text)
        self.assertIn("PYINSTALLER_VERSION: 6.22.1", text)
        self.assertIn("BUILD_VERSION: 1.5.0", text)
        self.assertIn("TWINE_VERSION: 7.0.0", text)
        self.assertIn("SETUPTOOLS_VERSION: 84.0.0", text)
        expected_files = {
            "codex_rescue-0.1.0a5-py3-none-any.whl",
            "codex_rescue-0.1.0a5.tar.gz",
            "codex-rescue-0.1.0-alpha.5.tgz",
            "codex-rescue-linux-x64-0.1.0-alpha.5.tgz",
            "codex-rescue-win32-x64-0.1.0-alpha.5.tgz",
            "codex-rescue-darwin-arm64-0.1.0-alpha.5.tgz",
            "codex-rescue-darwin-x64-0.1.0-alpha.5.tgz",
            "codex-rescue-linux-x64",
            "codex-rescue-win32-x64.exe",
            "codex-rescue-darwin-arm64",
            "codex-rescue-darwin-x64",
        }
        for filename in expected_files:
            self.assertIn(filename, text)
        self.assertIn("candidate file set mismatch", text)
        self.assertIn("release-manifest.json", text)
        self.assertIn("SHA256SUMS", text)

    def test_alpha4_release_workflow_remains_locked_to_alpha4(self) -> None:
        text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("v0.1.0-alpha.4", text)
        self.assertIn("0.1.0a4", text)
        self.assertIn("41d95ac0921a3a56dfb118eabcb6bf9d35e64b2f", text)
        self.assertNotIn("v0.1.0-alpha.5", text)


if __name__ == "__main__":
    unittest.main()
