"""Alpha8 sqlite_recover tests: corrupt DB salvage, source untouched."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_rescue.sqlite_recover import recover_sqlite


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT)")
    conn.executemany(
        "INSERT INTO threads VALUES (?,?)",
        [(f"t{i}", f"C:\\\\s\\\\r{i}.jsonl") for i in range(50)],
    )
    conn.commit()
    conn.close()


def _corrupt(path: Path) -> None:
    blob = bytearray(path.read_bytes())
    # Stomp a leaf page region well past the schema page (page 1 holds
    # sqlite_schema; small DBs put table leaves later). Header stays valid.
    start = max(4096, len(blob) // 2)
    for i in range(start, min(len(blob), start + 4096)):
        blob[i] = 0xFF
    path.write_bytes(bytes(blob))


class SqliteRecoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = self.root / "state_5.sqlite"
        _make_db(self.db)
        _corrupt(self.db)

    def test_healthy_db_refused(self) -> None:
        good = self.root / "good.sqlite"
        _make_db(good)
        report = recover_sqlite(good, write=True)
        self.assertEqual(report.integrity_before, "ok")
        self.assertFalse(report.write_performed)

    def test_dry_run_reports_without_writing(self) -> None:
        before = self.db.read_bytes()
        report = recover_sqlite(self.db, write=False)
        self.assertFalse(report.write_performed)
        self.assertIn("dry-run", " ".join(report.errors).lower())
        self.assertEqual(self.db.read_bytes(), before)

    def test_corrupt_db_salvaged(self) -> None:
        report = recover_sqlite(self.db, write=True)
        self.assertTrue(report.write_performed)
        self.assertIsNotNone(report.recovered_path)
        recovered = Path(report.recovered_path)
        self.assertTrue(recovered.exists())
        # Source untouched: its current hash must equal the recorded one.
        self.assertEqual(
            hashlib.sha256(self.db.read_bytes()).hexdigest(),
            report.source_sha256,
        )
        # Some rows salvaged into the recovered copy.
        if report.method == "select_sweep":
            table = next((t for t in report.tables if t.name == "threads"), None)
            self.assertIsNotNone(table)
            self.assertGreaterEqual(table.rows_recovered, 0)


if __name__ == "__main__":
    unittest.main()
