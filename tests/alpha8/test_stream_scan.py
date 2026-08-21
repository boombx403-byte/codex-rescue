"""Alpha8 stream_scan tests: one pass, bounded memory, truncated tail."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_rescue.stream_scan import stream_scan_rollout


class StreamScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _write(self, name: str, chunks: list[bytes]) -> Path:
        p = self.root / name
        p.write_bytes(b"".join(chunks))
        return p

    def test_healthy_rollout_single_pass_counts(self) -> None:
        recs = [
            {"type": "session_meta", "payload": {"cwd": "C:\\w"}},
            {"type": "turn_started", "ordinal": 1},
            {"type": "task_complete", "ordinal": 2},
        ]
        blob = b"".join(
            json.dumps(r).encode("utf-8") + b"\n" for r in recs
        )
        p = self._write("ok.jsonl", [blob])
        res = stream_scan_rollout(p)
        self.assertTrue(res.scanned_complete)
        self.assertFalse(res.truncated_tail)
        self.assertEqual(res.records_total, 3)
        self.assertEqual(res.records_ok, 3)
        self.assertEqual(res.oversized_count, 0)
        self.assertEqual(res.malformed_count, 0)
        self.assertIsNotNone(res.sha256_prefix)

    def test_truncated_tail_isolated_not_corruption(self) -> None:
        good = json.dumps({"type": "turn_started"}).encode() + b"\n"
        partial = b'{"type": "task_comp'  # no newline, cut mid-record
        p = self._write("cut.jsonl", [good, partial])
        res = stream_scan_rollout(p)
        self.assertTrue(res.truncated_tail)
        self.assertEqual(res.truncated_tail_offset, len(good))
        self.assertEqual(res.records_ok, 1)
        self.assertEqual(res.malformed_count, 0)

    def test_oversized_line_drained_and_counted(self) -> None:
        good = json.dumps({"type": "a"}).encode() + b"\n"
        huge = b'{"type": "big", "blob": "' + b"x" * (17 * 1024 * 1024) + b'"}\n'
        p = self._write("huge.jsonl", [good, huge])
        res = stream_scan_rollout(p, max_record_bytes=1024 * 1024)
        # The oversized record is drained and counted with true byte length.
        self.assertEqual(res.records_total, 2)
        self.assertEqual(res.oversized_count, 1)
        self.assertGreater(res.largest_record_bytes, 16 * 1024 * 1024)
        self.assertEqual(res.samples_oversized[0]["byte_length"], len(huge))

    def test_media_payload_detection_and_estimation(self) -> None:
        dataurl = "data:image/png;base64," + "A" * 4096
        media_rec = {
            "type": "event_msg",
            "payload": {"image_url": {"url": dataurl}},
        }
        plain = {"type": "turn_started"}
        blob = (
            json.dumps(media_rec).encode()
            + b"\n"
            + json.dumps(plain).encode()
            + b"\n"
        )
        p = self._write("media.jsonl", [blob])
        res = stream_scan_rollout(p)
        self.assertEqual(res.media_record_count, 1)
        self.assertGreaterEqual(res.media_bytes_total, 4096)

    def test_max_records_cap_marks_incomplete(self) -> None:
        lines = b"".join(
            json.dumps({"type": "t", "i": i}).encode() + b"\n" for i in range(50)
        )
        p = self._write("many.jsonl", [lines])
        res = stream_scan_rollout(p, max_records=10)
        self.assertFalse(res.scanned_complete)
        self.assertEqual(res.records_total, 10)


if __name__ == "__main__":
    unittest.main()
