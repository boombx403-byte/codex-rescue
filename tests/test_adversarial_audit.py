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

from codex_rescue.artifacts import atomic_write, load_handoff, validate_handoff, write_rescue
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
    """Rigorous, pruned adversarial regression suite defending core safety invariants."""

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
    # Group 1: Tool Call / Output Correlation & Invariant Defense
    # =========================================================================

    def test_valid_call_missing_output_diagnosed_as_unfinished(self) -> None:
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

    def test_orphaned_output_diagnosed_as_schema_issue(self) -> None:
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

    def test_duplicate_call_ids_trigger_correlation_ambiguity(self) -> None:
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

    def test_duplicate_output_ids_trigger_correlation_ambiguity(self) -> None:
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

    def test_inverted_output_preceding_call_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            records = [
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "inverted_1", "output": "early"}},
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "inverted_1", "name": "exec", "arguments": "{}"}},
            ]
            path.write_bytes(b"".join((json.dumps(r) + "\n").encode() for r in records))

            parsed = parse_transcript(path)
            self.assertTrue(parsed.correlation_ambiguities)
            self.assertEqual(doctor_session(path).status, "UNKNOWN_OPERATIONAL_SCHEMA")

    def test_call_output_family_mismatch_fails_correlation(self) -> None:
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

    # =========================================================================
    # Group 2: Corrupted Tool Names & Schema Hardening
    # =========================================================================

    def test_tool_name_with_control_chars_diagnosed_and_sanitized_in_artifacts(self) -> None:
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

    def test_all_c0_and_del_control_characters_flagged(self) -> None:
        for code in (*range(0x20), 0x7F):
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / f"rollout_ctrl_{code}.jsonl"
                bad_name = f"tool{chr(code)}name"
                record = {
                    "type": "response_item",
                    "payload": {"type": "function_call", "call_id": "c1", "name": bad_name, "arguments": "{}"},
                }
                path.write_text(json.dumps(record) + "\n", encoding="utf-8")
                parsed = parse_transcript(path)
                self.assertEqual(parsed.corruption_class, "CORRUPTED_TOOL_CALL", f"Failed for codepoint {code}")

    def test_valid_unicode_tool_name_not_flagged_as_corrupted(self) -> None:
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

    def test_tool_call_without_name_is_schema_issue(self) -> None:
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

    def test_tool_call_without_call_id_is_schema_issue(self) -> None:
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

    def test_unknown_operational_envelope_is_schema_issue(self) -> None:
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
    # Group 3: Production Payload Thresholds & Boundaries
    # =========================================================================

    def test_production_oversized_payload_threshold_boundaries(self) -> None:
        """Verify boundaries against production default threshold (1_000_000 bytes)."""
        with tempfile.TemporaryDirectory() as td:
            # 1. Plain text payload below default threshold (e.g. 800_000 bytes total record)
            p_below = Path(td) / "below.jsonl"
            records_below = [
                {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c1", "name": "custom_tool", "input": {}}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "A" * 799_900}},
            ]
            p_below.write_bytes(b"".join((json.dumps(r) + "\n").encode("utf-8") for r in records_below))
            res_below = parse_transcript(p_below)
            self.assertFalse(res_below.oversized_records)
            self.assertEqual(doctor_session(p_below).status, "HEALTHY")

            # 2. Plain text payload above default threshold (e.g. 1_000_050 bytes total line)
            p_above = Path(td) / "above.jsonl"
            records_above = [
                {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c1", "name": "custom_tool", "input": {}}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "B" * 1_000_000}},
            ]
            p_above.write_bytes(b"".join((json.dumps(r) + "\n").encode("utf-8") for r in records_above))
            res_above = parse_transcript(p_above)
            self.assertTrue(res_above.oversized_records)
            self.assertEqual(res_above.corruption_class, "OVERSIZED_PAYLOAD")
            self.assertEqual(doctor_session(p_above).status, "OVERSIZED_PAYLOAD")

            # 3. Base64 payload below vs above payload_floor boundary (500_000 bytes)
            p_b64_below = Path(td) / "b64_below.jsonl"
            records_b64_below = [
                {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c1", "name": "custom_tool", "input": {}}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "base64 " + ("C" * 400_000)}},
            ]
            p_b64_below.write_bytes(b"".join((json.dumps(r) + "\n").encode("utf-8") for r in records_b64_below))
            res_b64_below = parse_transcript(p_b64_below)
            self.assertFalse(res_b64_below.oversized_records)
            self.assertEqual(doctor_session(p_b64_below).status, "HEALTHY")

            p_b64_above = Path(td) / "b64_above.jsonl"
            records_b64_above = [
                {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c1", "name": "custom_tool", "input": {}}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "base64 " + ("D" * 550_000)}},
            ]
            p_b64_above.write_bytes(b"".join((json.dumps(r) + "\n").encode("utf-8") for r in records_b64_above))
            res_b64_above = parse_transcript(p_b64_above)
            self.assertTrue(res_b64_above.oversized_records)
            self.assertEqual(doctor_session(p_b64_above).status, "OVERSIZED_PAYLOAD")

    def test_max_record_bytes_bounded_streaming_preserves_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "huge_line.jsonl"
            limit = 10_000
            big_line = b'{"type":"response_item","payload":{"data":"' + (b'A' * 40_000) + b'"}}\n'
            path.write_bytes(big_line)
            parsed = parse_transcript(path, max_record_bytes=limit)
            self.assertEqual(parsed.corruption_class, "OVERSIZED_PAYLOAD")
            self.assertEqual(parsed.oversized_record_count, 1)
            self.assertEqual(parsed.sha256, _sha256(big_line))

    def test_truncated_jsonl_at_eof_diagnosed_as_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "truncated.jsonl"
            line1 = json.dumps({"type": "session_meta", "payload": {"id": "s1"}}).encode() + b"\n"
            line2 = b'{"type":"response_item","payload":{"incomplete":'
            path.write_bytes(line1 + line2)

            parsed = parse_transcript(path)
            self.assertEqual(parsed.corruption_class, "TRUNCATED_TRANSCRIPT")
            self.assertEqual(parsed.valid_record_count, 1)
            self.assertEqual(doctor_session(path).status, "TRUNCATED_TRANSCRIPT")

    def test_malformed_middle_record_diagnosed_as_malformed(self) -> None:
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

    def test_non_object_json_record_diagnosed_as_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "array_record.jsonl"
            path.write_bytes(b'["not", "an", "object"]\n')
            parsed = parse_transcript(path)
            self.assertEqual(parsed.corruption_class, "MALFORMED_RECORD")

    # =========================================================================
    # Group 4: Compaction & State Loss Detection
    # =========================================================================

    def test_compaction_with_state_loss_detected(self) -> None:
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

    def test_compaction_without_prior_tools_is_not_state_loss(self) -> None:
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

    def test_context_compacted_payload_type_recognized(self) -> None:
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
    # Group 5: Secret Redaction & Token Handling
    # =========================================================================

    def test_secret_patterns_redacted_in_handoff_and_brief(self) -> None:
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

    def test_data_url_inline_payloads_redacted(self) -> None:
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
    # Group 6: Salvage Immutability & Fail-Closed Guards
    # =========================================================================

    def test_salvage_preserves_source_bytes_and_sha256_exactly(self) -> None:
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

    def test_salvage_fails_closed_without_fork(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "rollout.jsonl"
            source.write_text('{"type":"session_meta"}\n', encoding="utf-8")
            doc = doctor_session(source)
            with self.assertRaises(ValueError):
                salvage_session(source, doc.transcript, doc.status, doc.findings, Path(td) / "rescue", fork=False)

    # =========================================================================
    # Group 7: Verify Confidence & Git State Hardening (P2)
    # =========================================================================

    def test_clean_repo_with_no_blockers_is_safe_to_continue(self) -> None:
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

    def test_untracked_file_causes_state_diverged(self) -> None:
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

    def test_modified_tracked_file_causes_state_diverged(self) -> None:
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

    def test_deleted_tracked_file_causes_state_diverged(self) -> None:
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

    def test_unknown_overall_confidence_causes_review_required(self) -> None:
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
            handoff = build_handoff(str(source), doc.transcript, inspect_git_state(repo), [], doc.status, doc.findings)
            handoff["overall_confidence"] = "unknown"
            rescue_id, _ = write_rescue(root / "rescue", handoff, "brief", "prompt")
            verify_res = verify_rescue(root / "rescue", rescue_id)
            self.assertEqual(verify_res.status, "REVIEW_REQUIRED")
            self.assertIn("handoff contains load-bearing unknowns", verify_res.review_reasons)

    # =========================================================================
    # Group 8: Deterministic Invariant Fuzzing
    # =========================================================================

    def test_deterministic_fuzz_mutations_preserve_invariants(self) -> None:
        """Deterministic mutation generator verifying invariants P1 and P9."""
        base_records = [
            {"type": "session_meta", "payload": {"id": "fuzz_1", "cwd": "/tmp"}},
            {"type": "response_item", "payload": {"type": "user_message", "message": "fuzz prompt"}},
            {"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "tool1", "arguments": '{"param": 1}'}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "ok"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c2", "name": "tool2", "input": {}}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c2", "output": "done"}},
            {"type": "compacted", "payload": {"summary": "done", "replacement_history": [{"type": "user", "text": "fuzz"}]}},
        ]

        mutations: list[bytes] = [
            b"".join((json.dumps(r) + "\n").encode() for r in base_records),
            b"".join((json.dumps(r) + "\n").encode() for r in base_records[:5]),
            b"".join((json.dumps(r) + "\n").encode() for r in base_records)[:-15],
            b"".join((json.dumps(r) + "\n").encode() for r in base_records).replace(b"tool1", b"tool\x001"),
            b"".join((json.dumps(r) + "\n").encode() for r in base_records).replace(b"tool1", b"tool\x07\x1b1"),
            b"".join((json.dumps(r) + "\n").encode() for r in base_records).replace(b'"c2"', b'"c1"'),
            (
                b"".join((json.dumps(r) + "\n").encode() for r in base_records[:3])
                + b'!!!CORRUPTED MIDDLE RECORD!!!\n'
                + b"".join((json.dumps(r) + "\n").encode() for r in base_records[3:])
            ),
            b"",
            b"GARBAGE_LINE_1\nGARBAGE_LINE_2\n",
        ]

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
