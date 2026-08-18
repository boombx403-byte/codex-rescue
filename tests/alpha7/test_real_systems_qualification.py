from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from codex_rescue.alpha7.autopilot import AutopilotEngine
from codex_rescue.alpha7.blackbox.observer import StateObserver
from codex_rescue.alpha7.blackbox.recorder import BlackBoxRecorder
from codex_rescue.alpha7.compatibility.portable import PortableSessionEngine
from codex_rescue.alpha7.simulation.transaction import TransactionalRepairEngine
from codex_rescue.alpha7.surfaces.app_server import RealAppServerClient, StdioJsonRpcClient


class DummyStdioProcess:
    """Mock process mimicking stdio JSON-RPC 2.0 stream for protocol verification."""

    def __init__(self):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.returncode = None

    def poll(self):
        return self.returncode


class RealSystemsQualificationTests(unittest.TestCase):
    def test_app_server_json_rpc_handshake_and_read(self):
        # Create a real subprocess python script that acts as an App Server JSON-RPC server
        server_script = """
import sys, json

while True:
    line = sys.stdin.readline()
    if not line:
        break
    req = json.loads(line)
    req_id = req.get("id")
    method = req.get("method")
    if method == "initialize":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"protocol_version": "v1", "server_version": "26.1"}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "initialized":
        continue
    elif method == "thread/list":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"threads": [{"id": "t1", "title": "Test"}]}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "thread/read":
        tid = req.get("params", {}).get("thread_id")
        if tid == "t1":
            res = {"jsonrpc": "2.0", "id": req_id, "result": {"thread_id": "t1", "turns": []}}
        else:
            res = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32600, "message": "Thread not found"}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "shutdown":
        break
"""
        with tempfile.TemporaryDirectory() as td:
            script_path = Path(td) / "mock_app_server.py"
            script_path.write_text(server_script, encoding="utf-8")

            proc = subprocess.Popen(
                [sys.executable, str(script_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            client = RealAppServerClient(Path(td))
            client._process = proc
            client._client = StdioJsonRpcClient(proc)

            # Handshake
            init_res = client.initialize()
            self.assertEqual(init_res["server_version"], "26.1")
            self.assertTrue(client._client.is_initialized)

            # List threads
            threads = client.list_threads()
            self.assertEqual(len(threads), 1)
            self.assertEqual(threads[0]["id"], "t1")

            # Read existing thread
            t1 = client.read_thread("t1")
            self.assertIsNotNone(t1)
            self.assertEqual(t1["thread_id"], "t1")

            # Read missing thread (returns None gracefully on -32600)
            t_missing = client.read_thread("t_missing")
            self.assertIsNone(t_missing)

            # Shutdown
            client.shutdown()

    def test_transactional_repair_and_source_immutability(self):
        with tempfile.TemporaryDirectory() as td:
            chome = Path(td)
            sdir = chome / "sessions"
            sdir.mkdir(parents=True)
            sess = sdir / "session_tx.jsonl"
            sess.write_text('{"turn": 1, "prompt": "test"}\n', encoding="utf-8")

            engine = TransactionalRepairEngine(chome)
            res = engine.execute_derived_index_repair(sess)

            self.assertEqual(res.status, "REPAIRED")
            self.assertTrue(res.source_preserved)
            self.assertEqual(res.initial_source_sha256, res.final_source_sha256)
            self.assertEqual(res.applied_mutations_count, 1)

            # Verify SQLite DB exists and contains index
            state_db = chome / "state_5.sqlite"
            self.assertTrue(state_db.exists())

    def test_state_observer_detects_real_changes(self):
        with tempfile.TemporaryDirectory() as td:
            chome = Path(td)
            sdir = chome / "sessions"
            sdir.mkdir(parents=True)

            recorder = BlackBoxRecorder()
            observer = StateObserver(chome, recorder)

            # Initial poll (empty)
            evs = observer.poll_once()
            self.assertEqual(len(evs), 0)

            # Add session file
            f1 = sdir / "sess1.jsonl"
            f1.write_text('{"turn":1}\n', encoding="utf-8")

            evs2 = observer.poll_once()
            self.assertEqual(len(evs2), 1)
            self.assertEqual(evs2[0].session_id, "sess1")

    def test_portable_roundtrip_with_derived_reconstruction(self):
        with tempfile.TemporaryDirectory() as td:
            src_home = Path(td) / "src_home"
            tgt_home = Path(td) / "tgt_home"
            src_sdir = src_home / "sessions"
            src_sdir.mkdir(parents=True)

            sess_file = src_sdir / "s_export.jsonl"
            sess_file.write_text('{"turn": 1, "text": "hello"}\n', encoding="utf-8")

            zip_path = Path(td) / "exported.rescue.zip"

            # 1. Export
            manifest = PortableSessionEngine.export_session(sess_file, zip_path)
            self.assertEqual(manifest.session_id, "s_export")

            # 2. Inspect
            inspected = PortableSessionEngine.inspect_package(zip_path)
            self.assertEqual(inspected.rollout_sha256, manifest.rollout_sha256)

            # 3. Plan & Import into isolated target
            plan = PortableSessionEngine.plan_import(zip_path, tgt_home)
            self.assertTrue(plan.safe_to_import)

            ok = PortableSessionEngine.execute_import(zip_path, tgt_home, rebuild_sqlite_index=True)
            self.assertTrue(ok)

            # 4. Verify target state
            tgt_file = tgt_home / "sessions" / "s_export.jsonl"
            self.assertTrue(tgt_file.exists())
            self.assertEqual(tgt_file.read_text(encoding="utf-8"), sess_file.read_text(encoding="utf-8"))

            tgt_db = tgt_home / "state_5.sqlite"
            self.assertTrue(tgt_db.exists())


if __name__ == "__main__":
    unittest.main()
