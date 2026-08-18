from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from codex_rescue.apply_plan import apply_recovery_plan
from codex_rescue.bundle import audit_bundle_file, generate_support_bundle
from codex_rescue.cli import main
from codex_rescue.contracts import Envelope, ExitCode
from codex_rescue.diff import diff_session
from codex_rescue.doctor_batch import run_doctor_all, run_doctor_changed
from codex_rescue.evidence import collect_session_evidence, detect_path_family, translate_path
from codex_rescue.explanations import get_explanation
from codex_rescue.graph import build_session_graph
from codex_rescue.plan import generate_recovery_plan
from codex_rescue.redact import audit_privacy, redact_text, sanitize_path
from codex_rescue.report import generate_html_report
from codex_rescue.schema_inspector import inspect_schemas
from codex_rescue.sessions_filter import filter_sessions
from codex_rescue.storage import analyze_storage
from codex_rescue.timeline import build_timeline
from codex_rescue.workspace import analyze_workspace
from codex_rescue.writer_inspector import inspect_writer


class Alpha6FeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp_dir.name) / ".codex"
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "sessions").mkdir(parents=True, exist_ok=True)
        (self.home / "archived_sessions").mkdir(parents=True, exist_ok=True)
        (self.home / "subagents").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_contracts_envelope(self):
        env = Envelope(command="doctor", session="s123", findings=["TRUNCATED_JSONL"])
        d = env.to_dict()
        self.assertEqual(d["schema_version"], 1)
        self.assertEqual(d["command"], "doctor")
        self.assertEqual(d["session"], "s123")
        self.assertEqual(d["findings"], ["TRUNCATED_JSONL"])
        self.assertNotIn("data", d)

    def test_redact_and_privacy_audit(self):
        secret_text = "Here is my token Bearer abcd1234efgh5678ijkl and key sk-12345678901234567890"
        sanitized = redact_text(secret_text)
        self.assertIn("[REDACTED_BEARER_TOKEN]", sanitized)
        self.assertIn("[REDACTED_API_KEY]", sanitized)

        clean_data = {"session_id": "test_1", "status": "HEALTHY", "metrics": {"count": 5}}
        self.assertEqual(audit_privacy(clean_data), [])

        leaky_data = {"session_id": "test_2", "token": "Bearer 1234567890abcdef1234567890"}
        violations = audit_privacy(leaky_data)
        self.assertTrue(len(violations) > 0)

    def test_batch_doctor_all_and_changed(self):
        s1 = self.home / "sessions" / "session_1.jsonl"
        s1.write_text(
            json.dumps({"type": "turn_started", "ordinal": 1}) + "\n" +
            json.dumps({"type": "task_complete", "ordinal": 2}) + "\n",
            encoding="utf-8",
        )

        s2 = self.home / "archived_sessions" / "session_2.jsonl"
        s2.write_text(
            json.dumps({"type": "turn_started", "ordinal": 1}) + "\n",
            encoding="utf-8",
        )

        summary = run_doctor_all(self.home)
        self.assertEqual(summary.sessions_scanned, 2)
        self.assertTrue(summary.healthy >= 1)

        changed_summary = run_doctor_changed(self.home)
        self.assertEqual(changed_summary.sessions_scanned, 2)

        changed_again = run_doctor_changed(self.home)
        self.assertEqual(changed_again.sessions_scanned, 2)

    def test_explain_finding_codes(self):
        exp = get_explanation("TRUNCATED_JSONL")
        d = exp.to_dict()
        self.assertIn("WHAT_HAPPENED", d)
        self.assertIn("EVIDENCE_USED", d)
        self.assertIn("WHAT_IS_STILL_HEALTHY", d)
        self.assertIn("WHAT_RESCUE_CANNOT_KNOW", d)
        self.assertIn("RISK", d)
        self.assertIn("SAFE_NEXT_ACTION", d)

    def test_diff_and_timeline(self):
        s_path = self.home / "sessions" / "diff_test.jsonl"
        s_path.write_text(
            json.dumps({"type": "turn_started", "ordinal": 1, "timestamp": "2026-08-18T10:00:00Z"}) + "\n" +
            json.dumps({"type": "tool_call", "name": "shell", "ordinal": 2, "timestamp": "2026-08-18T10:00:01Z"}) + "\n" +
            json.dumps({"type": "tool_output", "name": "shell", "output": "ok", "ordinal": 3, "timestamp": "2026-08-18T10:00:02Z"}) + "\n" +
            json.dumps({"type": "task_complete", "ordinal": 4, "timestamp": "2026-08-18T10:00:03Z"}) + "\n",
            encoding="utf-8",
        )

        diff = diff_session(s_path, codex_home=self.home)
        self.assertEqual(diff.session_id, "diff_test")

        timeline = build_timeline(s_path)
        self.assertEqual(timeline.total_events, 4)
        self.assertEqual(timeline.events[0].event_type, "turn_started")
        self.assertEqual(timeline.events[1].event_type, "tool_call_started")
        self.assertEqual(timeline.events[2].event_type, "tool_output_persisted")

    def test_graph_and_storage(self):
        parent = self.home / "sessions" / "parent_session.jsonl"
        parent.write_text(json.dumps({"type": "turn_started", "subagent_id": "child_subagent_1"}) + "\n", encoding="utf-8")

        (self.home / "sessions" / "subagents").mkdir(parents=True, exist_ok=True)
        child = self.home / "sessions" / "subagents" / "child_subagent_1.jsonl"
        child.write_text(json.dumps({"type": "turn_started", "parent_session_id": "parent_session"}) + "\n", encoding="utf-8")

        graph = build_session_graph(parent, codex_home=self.home)
        self.assertEqual(graph.root_session_id, "parent_session")
        self.assertTrue(graph.family_sessions_count >= 1)

        storage_rep = analyze_storage(self.home)
        self.assertTrue(storage_rep.total_sessions >= 1)
        self.assertTrue(storage_rep.total_logical_bytes > 0)

    def test_schema_and_workspace(self):
        s_path = self.home / "sessions" / "ws_test.jsonl"
        s_path.write_text(json.dumps({"type": "turn_started", "cwd": "/mnt/c/Users/tester/repo"}) + "\n", encoding="utf-8")

        schema_rep = inspect_schemas(self.home, [s_path])
        self.assertTrue(schema_rep.schema_coverage_pct > 0)

        ws_rep = analyze_workspace(s_path, codex_home=self.home)
        self.assertEqual(ws_rep.saved_path_family, "wsl")
        self.assertEqual(ws_rep.translated_path, "C:\\Users\\tester\\repo")

    def test_writer_inspector_and_read_only(self):
        s_path = self.home / "sessions" / "writer_test.jsonl"
        s_path.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n", encoding="utf-8")

        lock_path = self.home / "sessions" / "writer_test.lock"
        lock_path.write_text(str(os.getpid()), encoding="utf-8")

        report = inspect_writer(s_path, codex_home=self.home)
        self.assertTrue(report.lock_present)
        self.assertEqual(report.owner_pid, os.getpid())
        self.assertTrue(report.owner_process_alive)
        self.assertFalse(report.safe_to_modify)

    def test_recovery_plan_and_apply_safety_gates(self):
        s_path = self.home / "sessions" / "unindexed_test.jsonl"
        s_path.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n", encoding="utf-8")

        db_path = self.home / "state.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, updated_at INTEGER)")
        conn.commit()
        conn.close()

        plan = generate_recovery_plan(s_path, codex_home=self.home)
        self.assertEqual(plan.plan_schema_version, 1)
        self.assertFalse(plan.source_files_modified)

        res_dry = apply_recovery_plan(plan, dry_run=True, codex_home=self.home)
        self.assertTrue(res_dry.plan_applied)
        self.assertTrue(res_dry.dry_run)

        plan_dict = plan.to_dict()
        plan_dict["SOURCE_SHA256"] = "invalid_hash_12345"
        res_mismatch = apply_recovery_plan(plan_dict, codex_home=self.home)
        self.assertFalse(res_mismatch.plan_applied)
        self.assertIn("SOURCE_MUTATED", res_mismatch.refusal_reason or "")

    def test_support_bundle_redaction_and_report(self):
        s_path = self.home / "sessions" / "bundle_test.jsonl"
        s_path.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n", encoding="utf-8")

        bundle_out = Path(self.tmp_dir.name) / "bundle.json"
        bundle_obj, path_str = generate_support_bundle(s_path, output_bundle_path=bundle_out, codex_home=self.home)
        self.assertTrue(bundle_obj.redaction_audit_passed)
        self.assertEqual(audit_bundle_file(bundle_out), [])

        html_out = Path(self.tmp_dir.name) / "report.html"
        report_file = generate_html_report(s_path, output_html_path=html_out, codex_home=self.home)
        self.assertTrue(Path(report_file).exists())
        html_text = Path(report_file).read_text(encoding="utf-8")
        self.assertIn("<!DOCTYPE html>", html_text)
        self.assertIn("Codex Rescue Diagnostic Report", html_text)

    def test_session_filters(self):
        s1 = self.home / "sessions" / "dup_1.jsonl"
        s1.write_text(json.dumps({"type": "turn_started"}) + "\n", encoding="utf-8")
        s2 = self.home / "archived_sessions" / "dup_1.jsonl"
        s2.write_text(json.dumps({"type": "turn_started"}) + "\n", encoding="utf-8")

        dups = filter_sessions(self.home, duplicates=True)
        self.assertTrue(len(dups) >= 2)

    def test_cli_exit_codes_and_json(self):
        s_path = self.home / "sessions" / "cli_test.jsonl"
        s_path.write_text(
            json.dumps({"type": "turn_started", "ordinal": 1}) + "\n" +
            json.dumps({"type": "task_complete", "ordinal": 2}) + "\n",
            encoding="utf-8",
        )

        code = main(["doctor", str(s_path), "--json", "--codex-home", str(self.home)])
        self.assertEqual(code, int(ExitCode.SUCCESS))

        code = main(["explain", "TRUNCATED_JSONL", "--json"])
        self.assertEqual(code, int(ExitCode.SUCCESS))

        code = main(["schema", "--codex-home", str(self.home), "--json"])
        self.assertEqual(code, int(ExitCode.SUCCESS))


if __name__ == "__main__":
    unittest.main()
