"""Independent Differential Reference Oracle for Pairwise Tool Correlation.

Milestone R2 (Phases 10-12):
- Validates 1:1 pairing across function_call, custom_tool_call, and tool_search_call families.
- Tests correlation ambiguity on duplicate IDs, orphaned outputs, and cross-family mismatches.
- Compares production transcript parser state against an independent reference state oracle.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from codex_rescue.doctor import doctor_session
from codex_rescue.transcript import (
    TranscriptEvent,
    ParseResult,
    parse_transcript,
)


class DifferentialCorrelationOracle:
    """Independent reference implementation of tool correlation state machine."""

    def __init__(self) -> None:
        self.pending_calls: dict[str, dict[str, Any]] = {}
        self.completed_pairs: list[tuple[str, str, str]] = []  # (family, call_id, tool_name)
        self.ambiguities: list[str] = []
        self.seen_call_ids: set[str] = set()
        self.seen_output_ids: set[str] = set()

    def process_record(self, record: dict[str, Any]) -> None:
        if record.get("type") != "response_item":
            return
        payload = record.get("payload", {})
        ptype = payload.get("type", "")

        # 1. Call Events
        if ptype in ("function_call", "custom_tool_call", "tool_search_call"):
            call_id = payload.get("call_id")
            if not call_id:
                self.ambiguities.append("call_missing_id")
                return
            if call_id in self.seen_call_ids:
                self.ambiguities.append(f"duplicate_call_id:{call_id}")
                return
            self.seen_call_ids.add(call_id)
            
            family = "function" if ptype == "function_call" else ("custom" if ptype == "custom_tool_call" else "search")
            tool_name = payload.get("name", "search" if ptype == "tool_search_call" else "")
            self.pending_calls[call_id] = {
                "family": family,
                "tool_name": tool_name,
                "raw": payload,
            }

        # 2. Output Events
        elif ptype in ("function_call_output", "custom_tool_call_output", "tool_search_output"):
            call_id = payload.get("call_id")
            if not call_id:
                self.ambiguities.append("output_missing_id")
                return
            if call_id in self.seen_output_ids:
                self.ambiguities.append(f"duplicate_output_id:{call_id}")
                return
            self.seen_output_ids.add(call_id)

            output_family = "function" if ptype == "function_call_output" else ("custom" if ptype == "custom_tool_call_output" else "search")
            if call_id not in self.pending_calls:
                self.ambiguities.append(f"orphaned_output:{call_id}")
                return

            call_info = self.pending_calls.pop(call_id)
            if call_info["family"] != output_family:
                self.ambiguities.append(f"family_mismatch:{call_id}")
                return

            self.completed_pairs.append((call_info["family"], call_id, call_info["tool_name"]))


class TestCorrelationOracle(unittest.TestCase):
    """Differential correlation state machine verification against independent oracle."""

    def test_r2_oracle_nominal_pairwise_completion(self) -> None:
        """Verify nominal sequence of calls and outputs matches differential oracle 100%."""
        records = [
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "c1", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "ok"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "sql", "call_id": "c2", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c2", "output": "ok"}},
            {"type": "response_item", "payload": {"type": "tool_search_call", "name": "tool_search", "call_id": "c3", "query": "find"}},
            {"type": "response_item", "payload": {"type": "tool_search_output", "call_id": "c3", "output": "found"}},
        ]

        oracle = DifferentialCorrelationOracle()
        for r in records:
            oracle.process_record(r)

        self.assertEqual(len(oracle.completed_pairs), 3)
        self.assertEqual(len(oracle.pending_calls), 0)
        self.assertEqual(len(oracle.ambiguities), 0)

        # Compare with production parse_transcript
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-oracle.jsonl"
            meta = {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "o-1", "session_id": "o-1", "cwd": td}}
            with open(p, "wb") as f:
                f.write(json.dumps(meta).encode("utf-8") + b"\n")
                for r in records:
                    f.write(json.dumps(r).encode("utf-8") + b"\n")

            parsed = parse_transcript(p)
            self.assertEqual(len(parsed.unfinished_tool_calls), 0)
            self.assertEqual(len(parsed.correlation_ambiguities), 0)
            self.assertIsNone(parsed.corruption_class)
            self.assertEqual(parsed.valid_record_count, 7)

    def test_r2_oracle_cross_family_rejection(self) -> None:
        """Verify oracle and production both reject function_call paired with custom_tool_output."""
        records = [
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "m1", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "m1", "output": "ok"}},
        ]

        oracle = DifferentialCorrelationOracle()
        for r in records:
            oracle.process_record(r)

        self.assertEqual(len(oracle.completed_pairs), 0)
        self.assertEqual(len(oracle.ambiguities), 1)
        self.assertIn("family_mismatch:m1", oracle.ambiguities)

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-mismatch.jsonl"
            meta = {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "o-2", "session_id": "o-2", "cwd": td}}
            with open(p, "wb") as f:
                f.write(json.dumps(meta).encode("utf-8") + b"\n")
                for r in records:
                    f.write(json.dumps(r).encode("utf-8") + b"\n")

            parsed = parse_transcript(p)
            self.assertTrue(len(parsed.correlation_ambiguities) > 0)
            self.assertEqual(len(parsed.unfinished_tool_calls), 1)

    def test_r2_oracle_duplicate_call_id_detection(self) -> None:
        """Verify oracle and production flag duplicate call_ids as correlation ambiguity."""
        records = [
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "dup_1", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell2", "call_id": "dup_1", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "dup_1", "output": "ok"}},
        ]

        oracle = DifferentialCorrelationOracle()
        for r in records:
            oracle.process_record(r)

        self.assertIn("duplicate_call_id:dup_1", oracle.ambiguities)

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-dup.jsonl"
            meta = {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "o-3", "session_id": "o-3", "cwd": td}}
            with open(p, "wb") as f:
                f.write(json.dumps(meta).encode("utf-8") + b"\n")
                for r in records:
                    f.write(json.dumps(r).encode("utf-8") + b"\n")

            parsed = parse_transcript(p)
            self.assertTrue(len(parsed.correlation_ambiguities) > 0)


if __name__ == "__main__":
    unittest.main()
