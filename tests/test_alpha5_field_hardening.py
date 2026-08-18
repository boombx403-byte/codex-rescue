import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_rescue.doctor import doctor_session
from codex_rescue.field_evidence import inspect_workspace_portability, scan_field_evidence


class Alpha5FieldHardeningTests(unittest.TestCase):
    @staticmethod
    def _write(path: Path, records: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_interrupted_turn_without_durable_user_marker_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interrupted.jsonl"
            self._write(
                path,
                [
                    {"type": "session_meta", "payload": {"id": "x"}},
                    {"type": "event_msg", "payload": {"type": "task_started"}},
                    {
                        "type": "response_item",
                        "payload": {"type": "message", "role": "user", "content": "injected-context"},
                    },
                    {"type": "turn_context", "payload": {"turn_id": "t"}},
                    {"type": "event_msg", "payload": {"type": "turn_aborted"}},
                ],
            )
            report = scan_field_evidence(path)
            self.assertEqual(report.interrupted_input_boundary_count, 1)
            diagnosis = doctor_session(path)
            self.assertIn("INTERRUPTED_INPUT_NOT_DURABLE", diagnosis.findings)

    def test_durable_user_message_suppresses_interrupted_input_finding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "persisted.jsonl"
            self._write(
                path,
                [
                    {"type": "session_meta", "payload": {"id": "x"}},
                    {"type": "event_msg", "payload": {"type": "task_started"}},
                    {"type": "turn_context", "payload": {"turn_id": "t"}},
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "durable"},
                    },
                    {"type": "event_msg", "payload": {"type": "turn_aborted"}},
                ],
            )
            report = scan_field_evidence(path)
            self.assertEqual(report.interrupted_input_boundary_count, 0)
            diagnosis = doctor_session(path)
            self.assertNotIn("INTERRUPTED_INPUT_NOT_DURABLE", diagnosis.findings)

    def test_compaction_physical_dominance_is_reported_as_storage_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compacted.jsonl"
            self._write(
                path,
                [
                    {"type": "session_meta", "payload": {"id": "x"}},
                    {"type": "compacted", "payload": {"replacement_history": "x" * 2048}},
                    {"type": "compacted", "payload": {"replacement_history": "y" * 2048}},
                ],
            )
            with mock.patch("codex_rescue.field_evidence._STORAGE_AMPLIFICATION_MIN_BYTES", 1):
                report = scan_field_evidence(path)
                self.assertTrue(report.storage_amplification)
                self.assertGreater(report.compaction_byte_ratio, 0.5)
                diagnosis = doctor_session(path)
            self.assertIn("COMPACTION_STORAGE_AMPLIFICATION", diagnosis.findings)

    def test_wsl_cwd_on_windows_is_explicit_cross_platform_mismatch(self):
        with mock.patch("codex_rescue.field_evidence.os.name", "nt"):
            report = inspect_workspace_portability("/mnt/d/project")
        self.assertTrue(report.mismatch)
        self.assertEqual(report.saved_path_family, "wsl_mnt")
        self.assertEqual(report.suggested_native_cwd, "D:\\project")
        self.assertEqual(report.confidence, "strong")

    def test_windows_cwd_on_windows_is_not_mismatch(self):
        with mock.patch("codex_rescue.field_evidence.os.name", "nt"):
            report = inspect_workspace_portability("D:\\project")
        self.assertFalse(report.mismatch)
        self.assertEqual(report.saved_path_family, "windows_drive")


if __name__ == "__main__":
    unittest.main()
