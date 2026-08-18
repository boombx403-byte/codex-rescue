from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

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


@pytest.fixture
def temp_codex_home(tmp_path):
    home = tmp_path / ".codex"
    home.mkdir()
    (home / "sessions").mkdir()
    (home / "archived_sessions").mkdir()
    (home / "subagents").mkdir()
    return home


def test_contracts_envelope():
    env = Envelope(command="doctor", session="s123", findings=["TRUNCATED_JSONL"])
    d = env.to_dict()
    assert d["schema_version"] == 1
    assert d["command"] == "doctor"
    assert d["session"] == "s123"
    assert d["findings"] == ["TRUNCATED_JSONL"]
    assert "data" not in d


def test_redact_and_privacy_audit():
    secret_text = "Here is my token Bearer abcd1234efgh5678ijkl and key sk-12345678901234567890"
    sanitized = redact_text(secret_text)
    assert "[REDACTED_BEARER_TOKEN]" in sanitized
    assert "[REDACTED_API_KEY]" in sanitized

    # Privacy audit
    clean_data = {"session_id": "test_1", "status": "HEALTHY", "metrics": {"count": 5}}
    assert audit_privacy(clean_data) == []

    leaky_data = {"session_id": "test_2", "token": "Bearer 1234567890abcdef1234567890"}
    violations = audit_privacy(leaky_data)
    assert len(violations) > 0


def test_batch_doctor_all_and_changed(temp_codex_home):
    s1 = temp_codex_home / "sessions" / "session_1.jsonl"
    s1.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n" + json.dumps({"type": "task_complete", "ordinal": 2}) + "\n")
    
    s2 = temp_codex_home / "archived_sessions" / "session_2.jsonl"
    s2.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n")

    summary = run_doctor_all(temp_codex_home)
    assert summary.sessions_scanned == 2
    assert summary.healthy >= 1

    # Incremental changed-only doctor
    changed_summary = run_doctor_changed(temp_codex_home)
    assert changed_summary.sessions_scanned == 2

    # Rescan on cache existence
    changed_again = run_doctor_changed(temp_codex_home)
    assert changed_again.sessions_scanned == 2


def test_explain_finding_codes():
    exp = get_explanation("TRUNCATED_JSONL")
    d = exp.to_dict()
    assert "WHAT_HAPPENED" in d
    assert "EVIDENCE_USED" in d
    assert "WHAT_IS_STILL_HEALTHY" in d
    assert "WHAT_RESCUE_CANNOT_KNOW" in d
    assert "RISK" in d
    assert "SAFE_NEXT_ACTION" in d


def test_diff_and_timeline(temp_codex_home):
    s_path = temp_codex_home / "sessions" / "diff_test.jsonl"
    s_path.write_text(
        json.dumps({"type": "turn_started", "ordinal": 1, "timestamp": "2026-08-18T10:00:00Z"}) + "\n" +
        json.dumps({"type": "tool_call", "name": "shell", "ordinal": 2, "timestamp": "2026-08-18T10:00:01Z"}) + "\n" +
        json.dumps({"type": "tool_output", "name": "shell", "output": "ok", "ordinal": 3, "timestamp": "2026-08-18T10:00:02Z"}) + "\n" +
        json.dumps({"type": "task_complete", "ordinal": 4, "timestamp": "2026-08-18T10:00:03Z"}) + "\n"
    )

    diff = diff_session(s_path, codex_home=temp_codex_home)
    assert diff.session_id == "diff_test"

    timeline = build_timeline(s_path)
    assert timeline.total_events == 4
    assert timeline.events[0].event_type == "turn_started"
    assert timeline.events[1].event_type == "tool_call_started"
    assert timeline.events[2].event_type == "tool_output_persisted"


def test_graph_and_storage(temp_codex_home):
    parent = temp_codex_home / "sessions" / "parent_session.jsonl"
    parent.write_text(json.dumps({"type": "turn_started", "subagent_id": "child_subagent_1"}) + "\n")

    child = temp_codex_home / "sessions" / "subagents" / "child_subagent_1.jsonl"
    child.write_text(json.dumps({"type": "turn_started", "parent_session_id": "parent_session"}) + "\n")

    graph = build_session_graph(parent, codex_home=temp_codex_home)
    assert graph.root_session_id == "parent_session"
    assert graph.family_sessions_count >= 1

    storage_rep = analyze_storage(temp_codex_home)
    assert storage_rep.total_sessions >= 1
    assert storage_rep.total_logical_bytes > 0


def test_schema_and_workspace(temp_codex_home):
    s_path = temp_codex_home / "sessions" / "ws_test.jsonl"
    s_path.write_text(json.dumps({"type": "turn_started", "cwd": "/mnt/c/Users/tester/repo"}) + "\n")

    schema_rep = inspect_schemas(temp_codex_home, [s_path])
    assert schema_rep.schema_coverage_pct > 0

    ws_rep = analyze_workspace(s_path, codex_home=temp_codex_home)
    assert ws_rep.saved_path_family == "wsl"
    assert ws_rep.translated_path == "C:\\Users\\tester\\repo"


def test_writer_inspector_and_read_only(temp_codex_home):
    s_path = temp_codex_home / "sessions" / "writer_test.jsonl"
    s_path.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n")
    
    lock_path = temp_codex_home / "sessions" / "writer_test.lock"
    lock_path.write_text(str(os.getpid()))

    report = inspect_writer(s_path, codex_home=temp_codex_home)
    assert report.lock_present is True
    assert report.owner_pid == os.getpid()
    assert report.owner_process_alive is True
    assert report.safe_to_modify is False


def test_recovery_plan_and_apply_safety_gates(temp_codex_home):
    s_path = temp_codex_home / "sessions" / "unindexed_test.jsonl"
    s_path.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n")

    db_path = temp_codex_home / "state.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, updated_at INTEGER)")
    conn.commit()
    conn.close()

    plan = generate_recovery_plan(s_path, codex_home=temp_codex_home)
    assert plan.plan_schema_version == 1
    assert plan.source_files_modified is False

    # Dry-run test
    res_dry = apply_recovery_plan(plan, dry_run=True, codex_home=temp_codex_home)
    assert res_dry.plan_applied is True
    assert res_dry.dry_run is True

    # Mutated source verification gate test
    plan_dict = plan.to_dict()
    plan_dict["SOURCE_SHA256"] = "invalid_hash_12345"
    res_mismatch = apply_recovery_plan(plan_dict, codex_home=temp_codex_home)
    assert res_mismatch.plan_applied is False
    assert "SOURCE_MUTATED" in res_mismatch.refusal_reason


def test_support_bundle_redaction_and_report(temp_codex_home, tmp_path):
    s_path = temp_codex_home / "sessions" / "bundle_test.jsonl"
    s_path.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n")

    bundle_out = tmp_path / "bundle.json"
    bundle_obj, path_str = generate_support_bundle(s_path, output_bundle_path=bundle_out, codex_home=temp_codex_home)
    assert bundle_obj.redaction_audit_passed is True
    assert audit_bundle_file(bundle_out) == []

    html_out = tmp_path / "report.html"
    report_file = generate_html_report(s_path, output_html_path=html_out, codex_home=temp_codex_home)
    assert Path(report_file).exists()
    html_text = Path(report_file).read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text
    assert "Codex Rescue Diagnostic Report" in html_text


def test_session_filters(temp_codex_home):
    s1 = temp_codex_home / "sessions" / "dup_1.jsonl"
    s1.write_text(json.dumps({"type": "turn_started"}) + "\n")
    s2 = temp_codex_home / "archived_sessions" / "dup_1.jsonl"
    s2.write_text(json.dumps({"type": "turn_started"}) + "\n")

    dups = filter_sessions(temp_codex_home, duplicates=True)
    assert len(dups) >= 2


def test_cli_exit_codes_and_json(temp_codex_home):
    s_path = temp_codex_home / "sessions" / "cli_test.jsonl"
    s_path.write_text(json.dumps({"type": "turn_started", "ordinal": 1}) + "\n" + json.dumps({"type": "task_complete", "ordinal": 2}) + "\n")

    # doctor --json
    code = main(["doctor", str(s_path), "--json", "--codex-home", str(temp_codex_home)])
    assert code == int(ExitCode.SUCCESS)

    # explain
    code = main(["explain", "TRUNCATED_JSONL", "--json"])
    assert code == int(ExitCode.SUCCESS)

    # schema
    code = main(["schema", "--codex-home", str(temp_codex_home), "--json"])
    assert code == int(ExitCode.SUCCESS)
