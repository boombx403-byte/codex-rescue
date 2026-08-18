from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = str(Path(__file__).resolve().parent.parent.parent / "src")


class CliSubprocessE2ETests(unittest.TestCase):
    def _make_env(self, chome: Path) -> dict:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(chome)
        pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{pp}" if pp else SRC_DIR
        return env

    def test_cli_auto_no_args_subprocess(self):
        with tempfile.TemporaryDirectory() as td:
            chome = Path(td)
            env = self._make_env(chome)

            cmd = [sys.executable, "-m", "codex_rescue", "auto", "--json", "--codex-home", str(chome)]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=5.0,
            )
            self.assertEqual(proc.returncode, 0, f"Stderr: {proc.stderr}")
            data = json.loads(proc.stdout)
            self.assertEqual(data["data"]["action_taken"], "INSPECTED")

    def test_cli_self_test_subprocess(self):
        with tempfile.TemporaryDirectory() as td:
            chome = Path(td)
            env = self._make_env(chome)
            cmd = [sys.executable, "-m", "codex_rescue", "self-test", "--json", "--codex-home", str(chome)]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=5.0,
            )
            self.assertEqual(proc.returncode, 0, f"Stderr: {proc.stderr}")
            data = json.loads(proc.stdout)
            self.assertEqual(data["data"]["overall_status"], "PASS")

    def test_cli_interactive_surface_selector_simulated(self):
        with tempfile.TemporaryDirectory() as td:
            chome = Path(td)
            env = self._make_env(chome)
            sdir = chome / "sessions"
            sdir.mkdir(parents=True)
            # Create session to have CLI surface
            (sdir / "s1.jsonl").write_text('{"turn":1}\n', encoding="utf-8")
            # Create state.db to have Desktop surface
            state_db = chome / "state.db"
            state_db.write_text("", encoding="utf-8")

            # Pass "1\n" via stdin to select CLI
            cmd = [sys.executable, "-m", "codex_rescue", "auto", "--codex-home", str(chome)]
            proc = subprocess.run(
                cmd,
                input="1\n",
                capture_output=True,
                text=True,
                env=env,
                timeout=5.0,
            )
            self.assertEqual(proc.returncode, 0, f"Stderr: {proc.stderr}")
            self.assertIn("Autopilot", proc.stdout)

    def test_cli_repair_safe_subprocess(self):
        with tempfile.TemporaryDirectory() as td:
            chome = Path(td)
            env = self._make_env(chome)
            sdir = chome / "sessions"
            sdir.mkdir(parents=True)
            sess = sdir / "s_repair.jsonl"
            sess.write_text('{"turn":1, "prompt": "repair me"}\n', encoding="utf-8")

            cmd = [
                sys.executable,
                "-m",
                "codex_rescue",
                "auto",
                "--repair-safe",
                "--no-prompt",
                "--json",
                "--codex-home",
                str(chome),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=5.0,
            )
            self.assertEqual(proc.returncode, 0, f"Stderr: {proc.stderr}")
            data = json.loads(proc.stdout)
            self.assertEqual(data["data"]["action_taken"], "REPAIRED")
            self.assertTrue(data["data"]["transaction"]["source_preserved"])


if __name__ == "__main__":
    unittest.main()
