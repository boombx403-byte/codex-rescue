from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from codex_rescue.fixtures import _hash_tree_files, materialize_fixture_git_repo

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures"


class FixturePortabilityTests(unittest.TestCase):
    def test_all_fixtures_have_plain_snapshots(self) -> None:
        fixture_dirs = [p for p in FIXTURES_ROOT.iterdir() if p.is_dir()]
        self.assertGreaterEqual(len(fixture_dirs), 5)
        for fix in fixture_dirs:
            repo_before = fix / "repo_before"
            repo_actual = fix / "repo_actual"
            self.assertTrue(repo_before.exists(), f"repo_before missing in {fix.name}")
            self.assertTrue(repo_actual.exists(), f"repo_actual missing in {fix.name}")
            self.assertFalse((repo_before / ".git").exists(), f"repo_before contains .git in {fix.name}")
            self.assertFalse((repo_actual / ".git").exists(), f"repo_actual contains .git in {fix.name}")

    def test_materialize_fixture_git_repo_lifecycle(self) -> None:
        fix = FIXTURES_ROOT / "kill_apply_patch"
        repo_actual = fix / "repo_actual"
        hashes_before = _hash_tree_files(repo_actual)

        with materialize_fixture_git_repo(fix):
            git_dir = repo_actual / ".git"
            self.assertTrue(git_dir.exists(), ".git missing during materialization context")
            self.assertTrue(git_dir.is_dir(), ".git is not a directory")

        self.assertFalse((repo_actual / ".git").exists(), ".git was not cleaned up after context exit")
        hashes_after = _hash_tree_files(repo_actual)
        self.assertEqual(hashes_before, hashes_after, "Snapshot file hashes changed after materialization")


if __name__ == "__main__":
    unittest.main()
