from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_rescue.doctor import doctor_session
from codex_rescue.projection import inspect_projection_parity


def meta_record(session_id: str = "t-1") -> dict:
    return {
        "timestamp": "2026-08-16T00:00:00Z",
        "type": "session_meta",
        "payload": {"session_id": session_id, "id": session_id},
    }


def item_record(ordinal: int, message: str = "hello") -> dict:
    return {
        "timestamp": "2026-08-16T00:00:01Z",
        "type": "event_msg",
        "ordinal": ordinal,
        "payload": {"type": "user_message", "message": message},
    }


def build_rollout(root: Path, records: list[dict]) -> tuple[Path, list[int], int]:
    lines = [(json.dumps(record) + "\n").encode("utf-8") for record in records]
    path = root / "rollout-test.jsonl"
    path.write_bytes(b"".join(lines))
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    return path, offsets, position


def build_projection_db(home: Path, rows: list[tuple], threads_rows: list[tuple] | None = None) -> Path:
    db = home / "thread_history_1.sqlite"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE thread_history_projection_state "
            "(thread_id TEXT, next_rollout_byte_offset INTEGER, next_rollout_ordinal INTEGER)"
        )
        for row in rows:
            conn.execute("INSERT INTO thread_history_projection_state VALUES (?, ?, ?)", row)
        conn.commit()
    finally:
        conn.close()
    if threads_rows is not None:
        state = home / "state_5.sqlite"
        conn = sqlite3.connect(state)
        try:
            conn.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, history_mode TEXT, archived INTEGER)")
            for row in threads_rows:
                conn.execute("INSERT INTO threads VALUES (?, ?, ?, ?)", row)
            conn.commit()
        finally:
            conn.close()
    return db


def sha256_and_size(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def evidences(report: dict) -> list[str]:
    return [str(detail.get("evidence")) for detail in report["details"]]


class ProjectionParityTests(unittest.TestCase):
    def test_projection_missing_db_is_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, _, _ = build_rollout(tmp, [meta_record(), item_record(1)])
            result = doctor_session(rollout, codex_home=tmp)
            self.assertEqual(result.status, "HEALTHY")
            report = inspect_projection_parity(rollout, codex_home=tmp)
            self.assertEqual(report["status"], "NOT_APPLICABLE")

    def test_projection_caught_up_at_eof_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, _, size = build_rollout(tmp, [meta_record(), item_record(3)])
            build_projection_db(tmp, [("t-1", size, 4)])
            report = inspect_projection_parity(rollout, codex_home=tmp)
            self.assertEqual(report["status"], "MATCH")
            self.assertIn("caught_up_at_eof", evidences(report))
            self.assertEqual(doctor_session(rollout, codex_home=tmp).status, "HEALTHY")

    def test_boundary_ordinal_matches_is_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, offsets, _ = build_rollout(tmp, [meta_record(), item_record(3), item_record(4)])
            build_projection_db(
                tmp,
                [("t-1", offsets[1], 3)],
                threads_rows=[("t-1", str(rollout), "paginated", 0)],
            )
            report = inspect_projection_parity(rollout, codex_home=tmp)
            self.assertEqual(report["status"], "MATCH")
            self.assertIn("boundary_ordinal_ok", evidences(report))
            self.assertEqual(doctor_session(rollout, codex_home=tmp).status, "HEALTHY")

    def test_stale_cursor_boundary_mismatch_is_wedged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, offsets, _ = build_rollout(tmp, [meta_record(), item_record(3), item_record(4)])
            build_projection_db(
                tmp,
                [("t-1", offsets[1], 7)],
                threads_rows=[("t-1", str(rollout), "paginated", 0)],
            )
            report = inspect_projection_parity(rollout, codex_home=tmp)
            self.assertEqual(report["status"], "WEDGED")
            detail = report["details"][-1]
            self.assertEqual(detail["evidence"], "boundary_ordinal_mismatch")
            self.assertEqual(detail["expected"], 7)
            self.assertEqual(detail["actual"], 3)
            result = doctor_session(rollout, codex_home=tmp)
            self.assertIn("WEDGED_PROJECTION", result.findings)
            self.assertNotEqual(result.status, "HEALTHY")

    def test_cursor_beyond_extent_is_wedged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, _, size = build_rollout(tmp, [meta_record(), item_record(3)])
            build_projection_db(tmp, [("t-1", size + 100, 9)])
            report = inspect_projection_parity(rollout, codex_home=tmp)
            self.assertEqual(report["status"], "WEDGED")
            self.assertIn("projection_cursor_beyond_canonical_extent", evidences(report))
            result = doctor_session(rollout, codex_home=tmp)
            self.assertIn("WEDGED_PROJECTION", result.findings)

    def test_cursor_midline_is_wedged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, offsets, _ = build_rollout(tmp, [meta_record(), item_record(3)])
            build_projection_db(tmp, [("t-1", offsets[1] + 3, 3)])
            report = inspect_projection_parity(rollout, codex_home=tmp)
            self.assertEqual(report["status"], "WEDGED")
            self.assertIn("cursor_midline", evidences(report))

    def test_replayed_boundary_ordinal_is_wedged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, offsets, _ = build_rollout(tmp, [meta_record(), item_record(5), item_record(5)])
            build_projection_db(tmp, [("t-1", offsets[2], 5)])
            report = inspect_projection_parity(rollout, codex_home=tmp)
            self.assertEqual(report["status"], "WEDGED")
            self.assertIn("replayed_boundary_ordinal", evidences(report))
            result = doctor_session(rollout, codex_home=tmp)
            self.assertIn("WEDGED_PROJECTION", result.findings)

    def test_missing_state_db_row_falls_back_to_session_meta_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, offsets, _ = build_rollout(tmp, [meta_record(), item_record(3), item_record(4)])
            build_projection_db(tmp, [("t-1", offsets[1], 9)])
            report = inspect_projection_parity(rollout, codex_home=tmp)
            self.assertEqual(report["status"], "WEDGED")
            self.assertEqual(report["thread_id"], "t-1")
            self.assertEqual(report["details"][-1]["evidence"], "boundary_ordinal_mismatch")
            result = doctor_session(rollout, codex_home=tmp)
            self.assertIn("WEDGED_PROJECTION", result.findings)

    def test_sqlite_malformed_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, _, _ = build_rollout(tmp, [meta_record(), item_record(1)])
            (tmp / "thread_history_1.sqlite").write_bytes(b"\x00garbage-not-sqlite\x01\x02")
            result = doctor_session(rollout, codex_home=tmp)
            status = result.projection["status"]
            self.assertIn(status, {"NOT_APPLICABLE", "UNKNOWN"})
            if status == "NOT_APPLICABLE":
                self.assertEqual(result.status, "HEALTHY")
            else:
                self.assertIn("PROJECTION_ANALYSIS_INCOMPLETE", result.findings)
                self.assertNotEqual(result.status, "HEALTHY")

    def test_read_only_immutability(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, offsets, _ = build_rollout(tmp, [meta_record(), item_record(3), item_record(4)])
            db = build_projection_db(
                tmp,
                [("t-1", offsets[1], 3)],
                threads_rows=[("t-1", str(rollout), "paginated", 0)],
            )
            before_db = sha256_and_size(db)
            before_rollout = sha256_and_size(rollout)
            doctor_session(rollout, codex_home=tmp)
            self.assertEqual(sha256_and_size(db), before_db)
            self.assertEqual(sha256_and_size(rollout), before_rollout)

    def test_locked_sqlite_no_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            rollout, _, size = build_rollout(tmp, [meta_record(), item_record(3)])
            db = build_projection_db(tmp, [("t-1", size, 4)])
            holder = sqlite3.connect(str(db))
            try:
                holder.execute("BEGIN EXCLUSIVE")
                report = inspect_projection_parity(rollout, codex_home=tmp)
            finally:
                try:
                    holder.rollback()
                except sqlite3.Error:
                    pass
                holder.close()
            self.assertIn(report["status"], {"MATCH", "UNKNOWN", "NOT_APPLICABLE"})


if __name__ == "__main__":
    unittest.main()
