"""Alpha8 slim tests: media dedupe into a clean fork, source untouched."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from codex_rescue.slim import slim_rollout


def _dataurl(tag: str, size: int = 1024) -> str:
    return "data:image/png;base64," + (tag * size)[:size]


class SlimTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _src(self, records: list[dict]) -> tuple[Path, bytes]:
        blob = b"".join(json.dumps(r).encode() + b"\n" for r in records)
        p = self.root / "rollout.jsonl"
        p.write_bytes(blob)
        return p, blob

    def test_dry_run_measures_without_fork_file(self) -> None:
        img1 = _dataurl("A")
        records = [
            {"type": "m", "payload": {"url": img1}},
            {"type": "m", "payload": {"url": img1}},  # duplicate
            {"type": "t"},
        ]
        src, _ = self._src(records)
        before = src.read_bytes()
        report = slim_rollout(src, keep_fork=False)
        self.assertFalse(report.write_performed)
        self.assertIsNone(report.fork_path)
        self.assertEqual(report.media_dupes_removed, 1)
        self.assertEqual(report.media_unique_kept, 1)
        self.assertGreater(report.bytes_saved, 0)
        self.assertEqual(src.read_bytes(), before)  # source untouched

    def test_keep_fork_writes_deduped_output(self) -> None:
        img1 = _dataurl("B")
        img2 = _dataurl("C", 512)
        records = [
            {"type": "m", "payload": {"u": img1}},
            {"type": "m", "payload": {"u": img1}},  # dupe of first
            {"type": "m", "payload": {"u": img2}},
            {"type": "plain"},
        ]
        src, _ = self._src(records)
        report = slim_rollout(src, keep_fork=True)
        fork = Path(report.fork_path)
        self.assertTrue(fork.exists())
        lines = [json.loads(x) for x in fork.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 4)
        # First occurrence preserved verbatim.
        self.assertEqual(lines[0]["payload"]["u"], img1)
        # Duplicate replaced by a stub marker.
        marker = f"[REDACTED_DUPLICATE_MEDIA:"
        self.assertIn(marker, lines[1]["payload"]["u"])
        # Unique second payload preserved.
        self.assertEqual(lines[2]["payload"]["u"], img2)

    def test_source_sha_recorded_and_matches(self) -> None:
        records = [{"type": "a"}, {"type": "b"}]
        src, blob = self._src(records)
        report = slim_rollout(src, keep_fork=False)
        self.assertEqual(
            report.source_sha256,
            hashlib.sha256(blob).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
