from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_rescue.artifacts import atomic_write, load_handoff, validate_handoff, write_rescue
from codex_rescue.discovery import discover_sessions, lightweight_scan, resolve_latest
from codex_rescue.doctor import SEVERITY, doctor_session
from codex_rescue.gitstate import GitStateError, compare_git_state, inspect_git_state
from codex_rescue.reconstruct import (
    build_handoff,
    continuation_prompt,
    recovery_brief,
    render_continuation_command,
)
from codex_rescue.salvage import file_sha256, file_snapshot, salvage_session
from codex_rescue.transcript import (
    CORRUPTED_TOOL_NAME_SENTINEL,
    MAX_RECORD_BYTES,
    MAX_RETAINED_FINDINGS,
    TranscriptEvent,
    parse_transcript,
)
from codex_rescue.verify import verify_rescue


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class AdversarialAuditTests(unittest.TestCase):
    """Exhaustive adversarial test suite probing edge states and invariants."""

    def _init_git_repo(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "audit@example.invalid"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "Audit"], cwd=path, check=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=path, check=True)
        (path / "file.txt").write_text("initial content\n", encoding="utf-8")
        subprocess.run(["git", "add", "file.txt"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)

    # =========================================================================
    # Category 1: Tool Call / Output Correlation Probes
    # =========================================================================

    def test_cat1_01_valid_call_missing_output_diagnosed_as_unfinished(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "s1", "cwd": td}},
                {"type": "response_item", "payload": {"type": "user_message", "message": "hello"}},
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "exec", "arguments": "{}"}},
            ]
            content = b"".join((json.dumps(r) + "\n").encode() for r in records)
            path.write_bytes(content)
            sha_before = _sha256(content)

            parsed = parse_transcript(path)
            self.assertEqual(len(parsed.unfinished_tool_calls), 1)
            self.assertEqual(parsed.unfinished_tool_calls[0]["call_id"], "c1")
            self.assertEqual(parsed.unfinished_tool_call_count, 1)

            doc = doctor_session(path)
            self.assertEqual(doc.status, "UNFINISHED_TOOL_CALL")
            self.assertIn("UNFINISHED_TOOL_CALL", doc.findings)
            self.assertEqual(file_sha256(path), sha_before)

    def test_cat1_02_output_without_matching_call_is_schema_issue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "s1", "cwd": td}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "orphan_999", "output": "success"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertTrue(parsed.correlation_ambiguities)
            self.assertEqual(parsed.correlation_ambiguities[0]["call_id"], "orphan_999")
            self.assertEqual(parsed.corruption_class, "UNKNOWN_OPERATIONAL_SCHEMA")

            doc = doctor_session(path)
            self.assertEqual(doc.status, "UNKNOWN_OPERATIONAL_SCHEMA")
            self.assertIn("UNKNOWN_OPERATIONAL_SCHEMA", doc.findings)

    def test_cat1_03_duplicate_call_ids_trigger_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            records = [
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "dup_1", "name": "tool_a", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "dup_1", "name": "tool_b", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "dup_1", "output": "ok"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertTrue(parsed.correlation_ambiguities)
            self.assertEqual(doctor_session(path).status, "UNKNOWN_OPERATIONAL_SCHEMA")

    def test_cat1_04_duplicate_output_ids_trigger_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            records = [
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "call_1", "name": "tool_a", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call_1", "output": "ok1"}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call_1", "output": "ok2"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertTrue(parsed.correlation_ambiguities)
            self.assertEqual(doctor_session(path).status, "UNKNOWN_OPERATIONAL_SCHEMA")

    def test_cat1_05_output_preceding_call_handled_without_crash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            records = [
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "inverted_1", "output": "early"}},
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "inverted_1", "name": "exec", "arguments": "{}"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            # Inverted call/output order is conservatively treated as an unmatched output / schema issue
            self.assertTrue(parsed.correlation_ambiguities)
            self.assertEqual(doctor_session(path).status, "UNKNOWN_OPERATIONAL_SCHEMA")

    def test_cat1_06_family_mismatch_fails_correlation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            records = [
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "mismatch_1", "name": "f1", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "mismatch_1", "output": "out"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertTrue(parsed.correlation_ambiguities)
            self.assertEqual(doctor_session(path).status, "UNKNOWN_OPERATIONAL_SCHEMA")

    def test_cat1_07_tool_search_call_and_output_match_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            records = [
                {"type": "response_item", "payload": {"type": "tool_search_call", "call_id": "ts1", "name": "tool_search", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "tool_search_output", "call_id": "ts1", "output": "results"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertEqual(len(parsed.unfinished_tool_calls), 0)
            self.assertEqual(doctor_session(path).status, "HEALTHY")

    # =========================================================================
    # Category 2: Corrupted Tool Names & Schema Issues
    # =========================================================================

    def test_cat2_01_tool_name_with_control_chars_diagnosed_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            bad_name = "bash\x00\x07\x1b[31m\r\n"
            record = {
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "c_bad", "name": bad_name, "arguments": "{}"},
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")

            parsed = parse_transcript(path)
            self.assertEqual(parsed.corruption_class, "CORRUPTED_TOOL_CALL")
            self.assertTrue(parsed.corrupted_tool_calls)
            finding = parsed.corrupted_tool_calls[0]
            self.assertNotIn("name", finding)
            self.assertIn("name_sha256", finding)
            self.assertIn("control_codepoints", finding)

            self.assertEqual(parsed.events[0].payload["name"], CORRUPTED_TOOL_NAME_SENTINEL)

            doc = doctor_session(path)
            self.assertEqual(doc.status, "CORRUPTED_TOOL_CALL")

            handoff = build_handoff(str(path), parsed, None, [], doc.status, doc.findings)
            brief = recovery_brief(handoff)
            self.assertNotIn(bad_name, json.dumps(handoff))
            self.assertNotIn(bad_name, brief)

    def test_cat2_02_all_c0_control_characters_flagged(self) -> None:
        for code in range(0x20):
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / f"rollout_ctrl_{code}.jsonl"
                bad_name = f"tool{chr(code)}name"
                record = {
                    "type": "response_item",
                    "payload": {"type": "function_call", "call_id": "c1", "name": bad_name, "arguments": "{}"},
                }
                path.write_text(json.dumps(record) + "\n", encoding="utf-8")
                parsed = parse_transcript(path)
                self.assertEqual(parsed.corruption_class, "CORRUPTED_TOOL_CALL", f"Failed for code {code}")

    def test_cat2_03_del_control_character_0x7f_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout_del.jsonl"
            bad_name = "tool\x7fname"
            record = {
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "c1", "name": bad_name, "arguments": "{}"},
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            parsed = parse_transcript(path)
            self.assertEqual(parsed.corruption_class, "CORRUPTED_TOOL_CALL")

    def test_cat2_04_valid_unicode_tool_name_not_corrupted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout_unicode.jsonl"
            valid_name = "инструмент_123_🔥_ünicöde"
            record = {
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "c1", "name": valid_name, "arguments": "{}"},
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            parsed = parse_transcript(path)
            self.assertFalse(parsed.corrupted_tool_calls)
            self.assertEqual(parsed.events[0].payload["name"], valid_name)

    def test_cat2_05_tool_call_without_name_is_schema_issue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            record = {
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "c1", "arguments": "{}"},
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            parsed = parse_transcript(path)
            self.assertTrue(parsed.operational_schema_issues)
            self.assertEqual(parsed.operational_schema_issues[0]["reason"], "tool call has no name")
            self.assertEqual(doctor_session(path).status, "UNKNOWN_OPERATIONAL_SCHEMA")

    def test_cat2_06_tool_call_without_call_id_is_schema_issue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            record = {
                "type": "response_item",
                "payload": {"type": "function_call", "name": "exec", "arguments": "{}"},
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            parsed = parse_transcript(path)
            self.assertTrue(parsed.operational_schema_issues)
            self.assertEqual(parsed.operational_schema_issues[0]["reason"], "operational record has no call id")

    def test_cat2_07_unknown_tool_envelope_type_is_schema_issue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            record = {
                "type": "response_item",
                "payload": {"type": "future_unknown_tool_call", "call_id": "c1", "name": "exec"},
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            parsed = parse_transcript(path)
            self.assertTrue(parsed.operational_schema_issues)
            self.assertEqual(parsed.operational_schema_issues[0]["reason"], "unknown operational payload type")

    # =========================================================================
    # Category 3: Payload & Memory Boundary Probes
    # =========================================================================

    def test_cat3_01_exact_oversized_threshold_boundary(self) -> None:
        threshold = 100_000
        with tempfile.TemporaryDirectory() as td:
            p_below = Path(td) / "below.jsonl"
            rec_below = {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "x" * 90_000}}
            p_below.write_text(json.dumps(rec_below) + "\n", encoding="utf-8")
            res_below = parse_transcript(p_below, oversized_threshold=threshold)
            self.assertFalse(res_below.oversized_records)

            p_above = Path(td) / "above.jsonl"
            rec_above = {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "x" * 110_000}}
            p_above.write_text(json.dumps(rec_above) + "\n", encoding="utf-8")
            res_above = parse_transcript(p_above, oversized_threshold=threshold)
            self.assertTrue(res_above.oversized_records)
            self.assertEqual(res_above.corruption_class, "OVERSIZED_PAYLOAD")

    def test_cat3_02_max_record_bytes_bounded_streaming(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "huge_line.jsonl"
            limit = 10_000
            big_line = b'{"type":"response_item","payload":{"data":"' + (b'A' * 40_000) + b'"}}\n'
            path.write_bytes(big_line)
            parsed = parse_transcript(path, max_record_bytes=limit)
            self.assertEqual(parsed.corruption_class, "OVERSIZED_PAYLOAD")
            self.assertEqual(parsed.oversized_record_count, 1)
            self.assertEqual(parsed.sha256, _sha256(big_line))

    def test_cat3_03_raw_nul_byte_in_line_stops_at_valid_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nul_stream.jsonl"
            line1 = json.dumps({"type": "session_meta", "payload": {"id": "s1"}}).encode() + b"\n"
            line2 = b'{"type":"response_item", \x00 "corrupted": true}\n'
            path.write_bytes(line1 + line2)

            parsed = parse_transcript(path)
            self.assertEqual(parsed.corruption_class, "MALFORMED_RECORD")
            self.assertEqual(parsed.valid_record_count, 1)
            self.assertEqual(parsed.last_valid_offset, len(line1))
            self.assertEqual(parsed.first_invalid_offset, len(line1))
            self.assertEqual(parsed.sha256, _sha256(line1 + line2))

    def test_cat3_04_truncated_jsonl_at_eof(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "truncated.jsonl"
            line1 = json.dumps({"type": "session_meta", "payload": {"id": "s1"}}).encode() + b"\n"
            line2 = b'{"type":"response_item","payload":{"incomplete":'
            path.write_bytes(line1 + line2)

            parsed = parse_transcript(path)
            self.assertEqual(parsed.corruption_class, "TRUNCATED_TRANSCRIPT")
            self.assertEqual(parsed.valid_record_count, 1)
            self.assertEqual(doctor_session(path).status, "TRUNCATED_TRANSCRIPT")

    def test_cat3_05_malformed_middle_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "corrupt_middle.jsonl"
            line1 = json.dumps({"type": "session_meta", "payload": {"id": "s1"}}).encode() + b"\n"
            line2 = b'INVALID NOT JSON RECORD\n'
            line3 = json.dumps({"type": "response_item", "payload": {"type": "user_message", "message": "hi"}}).encode() + b"\n"
            path.write_bytes(line1 + line2 + line3)

            parsed = parse_transcript(path)
            self.assertEqual(parsed.corruption_class, "MALFORMED_RECORD")
            self.assertEqual(parsed.valid_record_count, 1)
            self.assertEqual(doctor_session(path).status, "MALFORMED_RECORD")

    def test_cat3_06_non_object_json_record_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "array_record.jsonl"
            path.write_bytes(b'["not", "an", "object"]\n')
            parsed = parse_transcript(path)
            self.assertEqual(parsed.corruption_class, "MALFORMED_RECORD")

    # =========================================================================
    # Category 4: Compaction & History State Probes
    # =========================================================================

    def test_cat4_01_compaction_with_state_loss_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "compacted_loss.jsonl"
            records = [
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "tool1", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "out1"}},
                {
                    "type": "compacted",
                    "payload": {"summary": "truncated summary", "replacement_history": []},
                },
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertTrue(parsed.compacted)
            self.assertTrue(parsed.compaction_state_loss)
            self.assertTrue(parsed.compaction_loss_evidence)
            self.assertEqual(doctor_session(path).status, "COMPACTION_STATE_LOSS")

    def test_cat4_02_compaction_without_prior_tools_is_not_state_loss(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "compacted_clean.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "s1"}},
                {"type": "response_item", "payload": {"type": "user_message", "message": "hi"}},
                {
                    "type": "compacted",
                    "payload": {"summary": "summary", "replacement_history": []},
                },
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertTrue(parsed.compacted)
            self.assertFalse(parsed.compaction_state_loss)
            self.assertEqual(doctor_session(path).status, "HEALTHY")

    def test_cat4_03_context_compacted_payload_type_recognized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "context_compacted.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "s1"}},
                {"type": "event_msg", "payload": {"type": "context_compacted"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertTrue(parsed.compacted)

    # =========================================================================
    # Category 5: Redaction & Secret Handling Probes
    # =========================================================================

    def test_cat5_01_all_secret_patterns_redacted_in_handoff(self) -> None:
        secrets_test_text = (
            "sk-abcdefghijklmnopqrstuvwxyz123456 "
            "ghp_123456789012345678901234567890123456 "
            "github_pat_11AAAAAAA01234567890_abcdefghijklmnopqrstuvwxyz "
            "xoxb-123456789012-1234567890123-abcdefghijklmnopqrstuvwxyz "
            "npm_abcdefghijklmnopqrstuvwxyz123456 "
            "pypi-AgEIcHlwaS5vcmcCJDM4ZjM5ZGU4LTJjZjQtNGM3My1hNzZkLTcwNjQzYjI2YjAwMAACKls "
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisJWT "
            "https://user:password123@github.com/repo "
            "AKIAIOSFODNN7EXAMPLE "
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0\n-----END RSA PRIVATE KEY-----"
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "secrets.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "s1", "cwd": td}},
                {"type": "response_item", "payload": {"type": "user_message", "message": secrets_test_text}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": secrets_test_text}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            handoff = build_handoff(str(path), parsed, None, [], "HEALTHY", ["HEALTHY"])
            serialized = json.dumps(handoff)

            self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", serialized)
            self.assertNotIn("ghp_123456789012345678901234567890123456", serialized)
            self.assertNotIn("password123", serialized)
            self.assertNotIn("AKIAIOSFODNN7EXAMPLE", serialized)
            self.assertNotIn("MIIEowIBAAKCAQEA0", serialized)
            self.assertIn("[REDACTED", serialized)

    def test_cat5_02_data_url_inline_payloads_redacted(self) -> None:
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "data_url.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "s1", "cwd": td}},
                {"type": "response_item", "payload": {"type": "user_message", "message": f"look at {data_url}"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            handoff = build_handoff(str(path), parsed, None, [], "HEALTHY", ["HEALTHY"])
            serialized = json.dumps(handoff)
            self.assertNotIn("iVBORw0KGgoAAASUhEUgAAAAE", serialized)
            self.assertIn("[REDACTED_INLINE_PAYLOAD]", serialized)

    # =========================================================================
    # Category 6: Salvage Fault Injection & Source Immutability (P1, P10)
    # =========================================================================

    def test_cat6_01_salvage_preserves_source_bytes_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_git_repo(repo)

            source = root / "rollout.jsonl"
            content = (
                json.dumps({"type": "session_meta", "payload": {"session_id": "sess1", "cwd": str(repo)}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "user_message", "message": "do task"}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "exec", "arguments": "{}"}}) + "\n"
            ).encode("utf-8")
            source.write_bytes(content)

            sha_before = _sha256(content)
            size_before = len(content)

            doc = doctor_session(source)
            self.assertEqual(file_sha256(source), sha_before)

            salvage_res = salvage_session(source, doc.transcript, doc.status, doc.findings, root / "rescue", fork=True)
            self.assertTrue(salvage_res.original_untouched)
            self.assertEqual(salvage_res.source_sha256_before, sha_before)
            self.assertEqual(salvage_res.source_sha256_after, sha_before)
            self.assertEqual(file_sha256(source), sha_before)
            self.assertEqual(source.stat().st_size, size_before)

            verify_res = verify_rescue(root / "rescue", salvage_res.rescue_id)
            self.assertEqual(file_sha256(source), sha_before)
            self.assertEqual(source.stat().st_size, size_before)

    def test_cat6_02_salvage_fails_closed_without_fork(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "rollout.jsonl"
            source.write_text('{"type":"session_meta"}\n', encoding="utf-8")
            doc = doctor_session(source)
            with self.assertRaises(ValueError):
                salvage_session(source, doc.transcript, doc.status, doc.findings, Path(td) / "rescue", fork=False)

    # =========================================================================
    # Category 7: Verify Confidence & Git State Hardening (P2)
    # =========================================================================

    def test_cat7_01_clean_repo_with_no_blockers_is_safe_to_continue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_git_repo(repo)

            source = root / "rollout.jsonl"
            content = (
                json.dumps({"type": "session_meta", "payload": {"session_id": "s1", "cwd": str(repo)}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "user_message", "message": "task"}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "exec", "arguments": "{}"}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "ok"}}) + "\n"
            ).encode("utf-8")
            source.write_bytes(content)

            doc = doctor_session(source)
            salvage_res = salvage_session(source, doc.transcript, doc.status, doc.findings, root / "rescue", fork=True)
            verify_res = verify_rescue(root / "rescue", salvage_res.rescue_id)
            self.assertEqual(verify_res.status, "SAFE_TO_CONTINUE")
            self.assertEqual(verify_res.conflicts, ())
            self.assertEqual(verify_res.review_reasons, ())

    def test_cat7_02_untracked_file_causes_state_diverged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_git_repo(repo)

            source = root / "rollout.jsonl"
            content = (
                json.dumps({"type": "session_meta", "payload": {"session_id": "s1", "cwd": str(repo)}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "user_message", "message": "task"}}) + "\n"
            ).encode("utf-8")
            source.write_bytes(content)

            doc = doctor_session(source)
            salvage_res = salvage_session(source, doc.transcript, doc.status, doc.findings, root / "rescue", fork=True)

            (repo / "untracked.txt").write_text("hello", encoding="utf-8")

            verify_res = verify_rescue(root / "rescue", salvage_res.rescue_id)
            self.assertEqual(verify_res.status, "STATE_DIVERGED")
            self.assertTrue(any("diff_hash" in c for c in verify_res.conflicts))

    def test_cat7_03_modified_tracked_file_causes_state_diverged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_git_repo(repo)

            source = root / "rollout.jsonl"
            content = (
                json.dumps({"type": "session_meta", "payload": {"session_id": "s1", "cwd": str(repo)}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "user_message", "message": "task"}}) + "\n"
            ).encode("utf-8")
            source.write_bytes(content)

            doc = doctor_session(source)
            salvage_res = salvage_session(source, doc.transcript, doc.status, doc.findings, root / "rescue", fork=True)

            (repo / "file.txt").write_text("modified\n", encoding="utf-8")

            verify_res = verify_rescue(root / "rescue", salvage_res.rescue_id)
            self.assertEqual(verify_res.status, "STATE_DIVERGED")

    def test_cat7_04_deleted_tracked_file_causes_state_diverged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_git_repo(repo)

            source = root / "rollout.jsonl"
            content = (
                json.dumps({"type": "session_meta", "payload": {"session_id": "s1", "cwd": str(repo)}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "user_message", "message": "task"}}) + "\n"
            ).encode("utf-8")
            source.write_bytes(content)

            doc = doctor_session(source)
            salvage_res = salvage_session(source, doc.transcript, doc.status, doc.findings, root / "rescue", fork=True)

            (repo / "file.txt").unlink()

            verify_res = verify_rescue(root / "rescue", salvage_res.rescue_id)
            self.assertEqual(verify_res.status, "STATE_DIVERGED")

    def test_cat7_05_unknown_overall_confidence_causes_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_git_repo(repo)

            source = root / "rollout.jsonl"
            content = (
                json.dumps({"type": "session_meta", "payload": {"session_id": "s1", "cwd": str(repo)}}) + "\n"
                + json.dumps({"type": "response_item", "payload": {"type": "user_message", "message": "task"}}) + "\n"
            ).encode("utf-8")
            source.write_bytes(content)

            doc = doctor_session(source)
            # Create handoff through build_handoff but force overall_confidence to unknown
            handoff = build_handoff(str(source), doc.transcript, inspect_git_state(repo), [], doc.status, doc.findings)
            handoff["overall_confidence"] = "unknown"
            rescue_id, _ = write_rescue(root / "rescue", handoff, "brief", "prompt")
            verify_res = verify_rescue(root / "rescue", rescue_id)
            self.assertEqual(verify_res.status, "REVIEW_REQUIRED")
            self.assertIn("handoff contains load-bearing unknowns", verify_res.review_reasons)

    # =========================================================================
    # Category 8: Discovery & Lightweight Scan Probes
    # =========================================================================

    def test_cat8_01_discovery_bounded_head_tail_scan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sessions_dir = root / "sessions"
            sessions_dir.mkdir()

            rollout = sessions_dir / "rollout-2026-01-01T00-00-00-test.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "sess_disc", "cwd": str(root)}},
                {"type": "response_item", "payload": {"type": "user_message", "message": "first prompt"}},
                {"type": "response_item", "payload": {"type": "user_message", "message": "second prompt"}},
            ]
            rollout.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            discovered = discover_sessions(root, limit=10)
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0].session_id, "sess_disc")
            self.assertEqual(discovered[0].first_prompt, "first prompt")
            self.assertEqual(discovered[0].last_prompt, "second prompt")
            self.assertEqual(discovered[0].status, "healthy")

    def test_cat8_02_discovery_damaged_tail_classified_as_damaged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sessions_dir = root / "sessions"
            sessions_dir.mkdir()

            rollout = sessions_dir / "rollout-2026-01-01T00-00-00-damaged.jsonl"
            rollout.write_bytes(b'{"type":"session_meta"}\n{"type":"response_item", UNPARSEABLE GARBAGE\n')

            summary = lightweight_scan(rollout)
            self.assertEqual(summary.status, "damaged")
            self.assertEqual(summary.reason, "malformed tail")

    def test_cat8_03_resolve_latest_finds_newest_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sessions_dir = root / "sessions"
            sessions_dir.mkdir()

            r1 = sessions_dir / "rollout-1.jsonl"
            r2 = sessions_dir / "rollout-2.jsonl"
            r1.write_text('{"type":"session_meta"}\n', encoding="utf-8")
            r2.write_text('{"type":"session_meta"}\n', encoding="utf-8")

            os.utime(r1, (1000, 1000))
            os.utime(r2, (2000, 2000))

            latest = resolve_latest(root)
            self.assertEqual(latest, r2.resolve())

    # =========================================================================
    # Category 9: Deterministic Invariant Fuzzer & Combinatorial Probes
    # =========================================================================

    def test_cat9_01_fuzz_mutations_never_modify_source_or_crash_doctor(self) -> None:
        """Deterministic mutation generator testing invariants P1, P9."""
        base_records = [
            {"type": "session_meta", "payload": {"id": "fuzz_1", "cwd": "/tmp"}},
            {"type": "response_item", "payload": {"type": "user_message", "message": "fuzz prompt"}},
            {"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "tool1", "arguments": '{"param": 1}'}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "ok"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c2", "name": "tool2", "input": {}}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c2", "output": "done"}},
            {"type": "compacted", "payload": {"summary": "done", "replacement_history": [{"type": "user", "text": "fuzz"}]}},
        ]

        mutations: list[bytes] = []

        # 1. Base normal
        mutations.append(b"".join((json.dumps(r) + "\n").encode() for r in base_records))
        # 2. Dropped last output (unfinished)
        mutations.append(b"".join((json.dumps(r) + "\n").encode() for r in base_records[:5]))
        # 3. Truncated tail
        mutations.append(b"".join((json.dumps(r) + "\n").encode() for r in base_records)[:-15])
        # 4. Embedded NUL byte in JSON string
        mutations.append(b"".join((json.dumps(r) + "\n").encode() for r in base_records).replace(b"tool1", b"tool\x001"))
        # 5. Control chars in tool name
        mutations.append(b"".join((json.dumps(r) + "\n").encode() for r in base_records).replace(b"tool1", b"tool\x07\x1b1"))
        # 6. Replaced call ID with duplicate
        mutations.append(b"".join((json.dumps(r) + "\n").encode() for r in base_records).replace(b'"c2"', b'"c1"'))
        # 7. Non-JSON corrupted line inserted in middle
        mutations.append(
            b"".join((json.dumps(r) + "\n").encode() for r in base_records[:3])
            + b'!!!CORRUPTED MIDDLE RECORD!!!\n'
            + b"".join((json.dumps(r) + "\n").encode() for r in base_records[3:])
        )
        # 8. Empty file
        mutations.append(b"")
        # 9. Only invalid lines
        mutations.append(b"GARBAGE_LINE_1\nGARBAGE_LINE_2\n")

        for idx, mutated_bytes in enumerate(mutations):
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / f"fuzz_{idx}.jsonl"
                path.write_bytes(mutated_bytes)
                sha_before = _sha256(mutated_bytes)
                size_before = len(mutated_bytes)

                parsed = parse_transcript(path)
                self.assertIsInstance(parsed.to_dict(), dict)

                doc = doctor_session(path)
                self.assertIn(doc.status, SEVERITY)
                self.assertIn(doc.status, doc.findings)

                self.assertEqual(file_sha256(path), sha_before)
                self.assertEqual(path.stat().st_size, size_before)


if __name__ == "__main__":
    unittest.main()
