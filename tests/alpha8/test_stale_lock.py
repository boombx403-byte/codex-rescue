"""Alpha8 stale-lock cleanup tests: dead-pid removal, live refusal."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from codex_rescue.stale_lock import fix_stale_writer_lock


def _make_rollout(root: Path) -> Path:
    p = root / "rollout-test.jsonl"
    p.write_text(json.dumps({"type": "session_meta"}) + "\n", encoding="utf-8")
    return p


class StaleLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.rollout = _make_rollout(self.root)

    def test_no_lock_is_noop(self) -> None:
        report = fix_stale_writer_lock(self.rollout, remove=True)
        self.assertEqual(report.action_taken, "nothing_stale")

    def test_dead_pid_lock_removed_with_backup(self) -> None:
        lock = self.rollout.with_suffix(".lock")
        lock.write_text("999999", encoding="utf-8")  # pid almost surely dead
        report = fix_stale_writer_lock(self.rollout, remove=True)
        if report.owner_alive is False:
            self.assertEqual(report.action_taken, "removed")
            self.assertFalse(lock.exists())
            backup = Path(report.backup_path)
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(), "999999")
        else:
            # CI host may actually run pid 999999; then removal must be refused.
            self.assertEqual(report.action_taken, "refused_live")

    def test_dry_run_does_not_remove(self) -> None:
        lock = self.rollout.with_suffix(".lock")
        lock.write_text("999999", encoding="utf-8")
        with mock.patch("codex_rescue.evidence.is_pid_alive", return_value=False):
            report = fix_stale_writer_lock(self.rollout, remove=False)
        self.assertEqual(report.action_taken, "none")
        self.assertTrue(lock.exists())
        self.assertIn("dry-run", " ".join(report.reasons))

    def test_live_pid_lock_refused(self) -> None:
        lock = self.rollout.with_suffix(".lock")
        lock.write_text(str(os.getpid()), encoding="utf-8")  # this test process
        report = fix_stale_writer_lock(self.rollout, remove=True)
        self.assertEqual(report.action_taken, "refused_live")
        self.assertTrue(lock.exists())

    def test_unparseable_young_lock_not_stale(self) -> None:
        lock = self.rollout.parent / f"{self.rollout.name}.lock"
        lock.write_text("not-a-pid", encoding="utf-8")
        report = fix_stale_writer_lock(self.rollout, remove=True)
        self.assertEqual(report.action_taken, "nothing_stale")

    def test_unparseable_old_lock_removed(self) -> None:
        lock = self.rollout.parent / f"{self.rollout.name}.lock"
        lock.write_text("garbage", encoding="utf-8")
        old = time.time() - 25 * 3600
        os.utime(lock, (old, old))
        report = fix_stale_writer_lock(self.rollout, remove=True)
        self.assertEqual(report.action_taken, "removed")
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
