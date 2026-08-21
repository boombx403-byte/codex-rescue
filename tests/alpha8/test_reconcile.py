"""Alpha8 reconcile tests: extended-path + WSL cwd repair with backups."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_rescue.reconcile import reconcile_codex_home


def _make_home(root: Path) -> Path:
    home = root / ".codex"
    home.mkdir(parents=True, exist_ok=True)
    db = home / "state_5.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            rollout_path TEXT,
            cwd TEXT,
            updated_at INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO threads (id, rollout_path, cwd, updated_at) VALUES (?,?,?,?)",
        (
            "thread-extended",
            r"\\?\C:\Users\me\.codex\sessions\rollout-a.jsonl",
            r"C:\work\project-a",
            1,
        ),
    )
    conn.execute(
        "INSERT INTO threads (id, rollout_path, cwd, updated_at) VALUES (?,?,?,?)",
        (
            "thread-wsl",
            r"C:\Users\me\.codex\sessions\rollout-b.jsonl",
            "/mnt/d/work/project-b",
            2,
        ),
    )
    conn.commit()
    conn.close()
    return home


class ReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = _make_home(Path(self._tmp.name))

    def test_dry_run_plans_without_mutating(self) -> None:
        report = reconcile_codex_home(self.home, write=False)
        self.assertFalse(report.write_performed)
        kinds = {c.kind for c in report.changes}
        self.assertIn("wsl_cwd", kinds)
        # Extended path: \\?\C:\... vs its normalized form must compare SAME.
        self.assertTrue(
            any(c.kind == "extended_path" for c in report.changes),
            "expected an extended-path plan entry",
        )
        db = self.home / "state_5.sqlite"
        conn = sqlite3.connect(str(db))
        rows = dict(conn.execute("SELECT id, rollout_path FROM threads"))
        conn.close()
        self.assertTrue(rows["thread-extended"].startswith("\\\\?\\"))

    def test_write_applies_and_backs_up(self) -> None:
        report = reconcile_codex_home(self.home, write=True)
        self.assertTrue(report.write_performed)
        self.assertEqual(len(report.backups), 1)
        backup = Path(report.backups[0]["backup"])
        self.assertTrue(backup.exists())

        conn = sqlite3.connect(str(self.home / "state_5.sqlite"))
        rows = {
            row[0]: (row[1], row[2])
            for row in conn.execute("SELECT id, rollout_path, cwd FROM threads")
        }
        conn.close()

        ext_path, ext_cwd = rows["thread-extended"]
        self.assertEqual(ext_cwd, r"C:\work\project-a")
        wsl_path, wsl_cwd = rows["thread-wsl"]
        self.assertEqual(wsl_cwd, r"D:\work\project-b")

    def test_json_output_shape(self) -> None:
        report = reconcile_codex_home(self.home, write=False)
        data = report.to_dict()
        json.dumps(data)
        self.assertIn("changes", data)
        self.assertIn("backups", data)


if __name__ == "__main__":
    unittest.main()
