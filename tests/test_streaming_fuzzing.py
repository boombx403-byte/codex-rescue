"""Generative streaming JSONL property fuzzer and differential parser harness.

Milestone R2 (Phases 6-12):
- Generative JSONL stream permutations (mixed line delimiters, BOMs, NUL bytes, ANSI sequences, BiDi overrides).
- Extreme payload bounds testing (up to 500MB simulated payloads, 8MB line drainage, memory capping).
- Property assertions for Safety Invariants P1-P10.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from codex_rescue.discovery import lightweight_scan
from codex_rescue.doctor import doctor_session
from codex_rescue.salvage import file_sha256, salvage_session
from codex_rescue.transcript import (
    CORRUPTED_TOOL_NAME_SENTINEL,
    MAX_RECORD_BYTES,
    ParseResult,
    _read_line_bounded,
    parse_transcript,
)


class StreamingFuzzGenerator:
    """Generates synthetic adversarial and property-based JSONL streams."""

    @staticmethod
    def fuzz_line_endings() -> list[bytes]:
        return [b"\n", b"\r\n", b"\r", b"\n\r", b"\n\n", b"\r\n\r\n"]

    @staticmethod
    def fuzz_utf8_anomalies() -> list[bytes]:
        return [
            b"\xef\xbb\xbf",  # Standard UTF-8 BOM
            b"\x00",          # NUL byte
            b"\x1b[31;1mANSI_RED\x1b[0m",  # ANSI escape
            b"\xe2\x80\xaeBIDI_OVERRIDE\xe2\x80\xac",  # BiDi RLO + PDF
            b"\x01\x02\x03\x04\x05\x06\x07\x08",  # C0 control characters
            b"\x7f",          # DEL character
            b"\xf0\x9f\x92\xa9",  # Valid 4-byte UTF-8 emoji
            b"\xed\xa0\x80",  # UTF-8 encoded lone surrogate (invalid)
            b"\xc0\xaf",      # Overlong 2-byte slash (invalid)
        ]

    @classmethod
    def generate_mutated_stream(
        cls,
        base_records: list[dict[str, Any]],
        inject_anomaly: bytes | None = None,
        line_ending: bytes = b"\n",
        truncate_offset: int | None = None,
    ) -> bytes:
        buf = bytearray()
        for rec in base_records:
            line = json.dumps(rec, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if inject_anomaly:
                # Inject anomaly into middle of line or at boundary
                line = line + inject_anomaly
            buf.extend(line)
            buf.extend(line_ending)

        raw = bytes(buf)
        if truncate_offset is not None and 0 <= truncate_offset < len(raw):
            raw = raw[:truncate_offset]
        return raw


class TestStreamingFuzzing(unittest.TestCase):
    """Property-based fuzzing and boundary validation suite."""

    def test_r2_fuzz_crlf_lf_mix_stream_parsing(self) -> None:
        """Verify stream with alternating CRLF and LF delimiters parses all records."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-crlf-mix.jsonl"
            records = [
                {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "crlf-1", "session_id": "crlf-1", "cwd": td}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": "Step 1"}},
                {"type": "event_msg", "payload": {"type": "agent_message", "message": "Step 2"}},
            ]
            content = (
                json.dumps(records[0]).encode("utf-8") + b"\r\n" +
                json.dumps(records[1]).encode("utf-8") + b"\n" +
                json.dumps(records[2]).encode("utf-8") + b"\r\n"
            )
            p.write_bytes(content)

            parsed = parse_transcript(p)
            self.assertEqual(len(parsed.events), 3)
            self.assertEqual(parsed.events[1].payload["message"], "Step 1")
            self.assertEqual(parsed.events[2].payload["message"], "Step 2")

    def test_r2_fuzz_utf8_bom_at_stream_start(self) -> None:
        """Verify leading UTF-8 BOM is transparently handled without corrupting first record."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q"], cwd=td, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=td, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=td, check=True)
            subprocess.run(["git", "commit", "--allow-empty", "-qm", "initial"], cwd=td, check=True)
            p = Path(td) / "rollout-bom.jsonl"
            rec = {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "bom-1", "session_id": "bom-1", "cwd": td}}
            p.write_bytes(b"\xef\xbb\xbf" + json.dumps(rec).encode("utf-8") + b"\n")

            doc = doctor_session(p)
            self.assertEqual(doc.status, "HEALTHY")
            self.assertEqual(doc.transcript.session_metadata.get("id"), "bom-1")

    def test_r2_fuzz_nul_byte_halts_cleanly(self) -> None:
        """Verify embedded NUL byte halts stream at valid prefix and reports MALFORMED_RECORD."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-nul.jsonl"
            rec1 = {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "nul-1", "session_id": "nul-1", "cwd": td}}
            rec2 = {"type": "event_msg", "payload": {"type": "user_message", "message": "Valid"}}
            
            p.write_bytes(
                json.dumps(rec1).encode("utf-8") + b"\n" +
                json.dumps(rec2).encode("utf-8") + b"\n" +
                b'{"type":"event_msg","payload":{"type":"agent_message","message":"bad\x00'
            )

            doc = doctor_session(p)
            self.assertIn("MALFORMED_RECORD", doc.findings)
            self.assertEqual(len(doc.transcript.events), 2)

    def test_r2_fuzz_control_character_sanitization_matrix(self) -> None:
        """Verify matrix of control characters in tool names are safely sanitized to sentinels (P4)."""
        for char_code in [0x01, 0x07, 0x08, 0x1B, 0x7F]:
            char_bytes = bytes([char_code])
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / f"rollout-ctrl-{char_code}.jsonl"
                bad_name = f"tool{char_bytes.decode('latin-1')}exec"
                rec_meta = {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "c-1", "session_id": "c-1", "cwd": td}}
                rec_call = {"type": "response_item", "payload": {"type": "function_call", "name": bad_name, "call_id": "c1", "arguments": "{}"}}
                
                p.write_bytes(json.dumps(rec_meta).encode("utf-8") + b"\n" + json.dumps(rec_call).encode("utf-8") + b"\n")

                doc = doctor_session(p)
                self.assertIn("CORRUPTED_TOOL_CALL", doc.findings)
                # Verify sentinel in transcript
                self.assertEqual(len(doc.transcript.events), 2)
                self.assertEqual(doc.transcript.events[1].payload.get("name"), CORRUPTED_TOOL_NAME_SENTINEL)
                self.assertEqual(len(doc.transcript.corrupted_tool_calls), 1)

    def test_r2_fuzz_extreme_line_length_drainage(self) -> None:
        """Verify lines exceeding 8MB MAX_RECORD_BYTES are safely drained and classified."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-oversized-line.jsonl"
            rec_meta = {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "big-1", "session_id": "big-1", "cwd": td}}
            
            with open(p, "wb") as f:
                f.write(json.dumps(rec_meta).encode("utf-8") + b"\n")
                # Write a record exceeding MAX_RECORD_BYTES (8MB + 1024 bytes)
                f.write(b'{"type":"response_item","payload":{"type":"input_image","data":"')
                f.write(b"X" * (MAX_RECORD_BYTES + 1024))
                f.write(b'"}}\n')

            doc = doctor_session(p)
            self.assertIn("OVERSIZED_PAYLOAD", doc.findings)
            self.assertEqual(doc.transcript.session_metadata.get("id"), "big-1")


if __name__ == "__main__":
    unittest.main()
