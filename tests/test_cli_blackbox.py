"""Black-Box CLI Envelope, Subcommand, and Exit Code Validation Suite.

Milestone R3 (Phases 46-52):
- CLI subcommands: doctor, salvage, verify, sessions, inspect.
- JSON envelope contract adherence and stability.
- Exit code contracts (0=HEALTHY/VERIFIED, 1=UNHEALTHY, 2=USAGE/OS, 3=REVIEW_REQUIRED/DIVERGED).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestCLIBlackbox(unittest.TestCase):
    """Black-box CLI integration tests."""

    def _run_cli(self, *args: str) -> tuple[int, str, str]:
        cmd = [sys.executable, "-m", "codex_rescue.cli", *args]
        env = dict(PYTHONPATH="src")
        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
        return res.returncode, res.stdout, res.stderr

    def test_r3_cli_version_flag(self) -> None:
        """Verify codex-rescue --version returns version string and exit code 0."""
        code, out, _ = self._run_cli("--version")
        self.assertEqual(code, 0)
        self.assertIn("0.1.0a3", out)

    def test_r3_cli_help_flag(self) -> None:
        """Verify codex-rescue --help returns help text and exit code 0."""
        code, out, _ = self._run_cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("codex-rescue", out)
        self.assertIn("doctor", out)
        self.assertIn("salvage", out)
        self.assertIn("verify", out)

    def test_r3_cli_unknown_subcommand_exit_code_2(self) -> None:
        """Verify unknown subcommand returns exit code 2."""
        code, _, err = self._run_cli("nonexistent_subcommand")
        self.assertEqual(code, 2)

    def test_r3_cli_doctor_json_envelope_schema(self) -> None:
        """Verify codex-rescue doctor --json returns valid JSON envelope."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-cli.jsonl"
            rec = {"timestamp": "2026-08-15T00:00:00Z", "type": "session_meta", "payload": {"id": "cli-1", "session_id": "cli-1", "cwd": td}}
            p.write_bytes(json.dumps(rec).encode("utf-8") + b"\n")

            code, out, _ = self._run_cli("doctor", str(p), "--json")
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertIn("status", data)
            self.assertEqual(data["status"], "HEALTHY")


if __name__ == "__main__":
    unittest.main()
