from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from codex_rescue.alpha7.autopilot import AutopilotEngine
from codex_rescue.alpha7.blackbox.observer import StateObserver
from codex_rescue.alpha7.blackbox.recorder import BlackBoxRecorder
from codex_rescue.alpha7.compatibility.portable import PortableSessionEngine
from codex_rescue.alpha7.simulation.transaction import TransactionalRepairEngine
from codex_rescue.alpha7.surfaces.app_server import RealAppServerClient, StdioJsonRpcClient


@contextlib.contextmanager
def safe_temp_codex_home():
    td = tempfile.mkdtemp()
    try:
        yield Path(td)
    finally:
        if os.name == "nt":
            time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


class RealSystemsQualificationTests(unittest.TestCase):
    def test_real_codex_app_server_binary_e2e(self):
        """Launches REAL installed Codex binary app-server against a disposable temp CODEX_HOME."""
        codex_bin = shutil.which("codex")
        if not codex_bin:
            self.skipTest("Real codex binary not in PATH")

        with safe_temp_codex_home() as chome:
            client = RealAppServerClient(chome, timeout=5.0)

            # 1. Launch real stdio server
            launched = client.launch_stdio_server(binary_path=codex_bin)
            self.assertTrue(launched, "Failed to launch real codex app-server")

            try:
                # 2. Real initialize handshake
                init_res = client.initialize()
                self.assertIn("userAgent", init_res)
                self.assertTrue(client._client.is_initialized)

                # 3. Real thread/list on empty disposable state
                threads = client.list_threads()
                self.assertIsInstance(threads, list)
                self.assertEqual(len(threads), 0)

                # 4. Real thread/read with nonexistent UUID (verifies -32600 handling)
                dummy_uuid = str(uuid.uuid4())
                t_missing = client.read_thread(dummy_uuid)
                self.assertIsNone(t_missing)

                # 5. Receive notifications
                notifs = client._client.get_notifications()
                self.assertIsInstance(notifs, list)
            finally:
                # 6. Clean shutdown
                client.shutdown()

    def test_synthetic_app_server_protocol_mock(self):
        """Tests StdioJsonRpcClient protocol dispatcher using a mock server."""
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
        res = {"id": req_id, "result": {"userAgent": "mock_codex/1.0", "codexHome": "/tmp"}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "initialized":
        continue
    elif method == "thread/list":
        # Send an asynchronous notification first to test reader queue
        sys.stdout.write(json.dumps({"method": "test/notification", "params": {"key": "val"}}) + "\\n")
        sys.stdout.flush()
        # Then send the response
        res = {"id": req_id, "result": {"data": [{"id": "t1", "title": "Test"}]}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "thread/read":
        tid = req.get("params", {}).get("threadId")
        if tid == "t1":
            res = {"id": req_id, "result": {"threadId": "t1", "turns": []}}
        else:
            res = {"id": req_id, "error": {"code": -32600, "message": "Thread not found"}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "shutdown":
        break
"""
        with safe_temp_codex_home() as td:
            script_path = td / "mock_app_server.py"
            script_path.write_text(server_script, encoding="utf-8")

            proc = subprocess.Popen(
                [sys.executable, str(script_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            client = RealAppServerClient(td)
            client._process = proc
            client._client = StdioJsonRpcClient(proc)

            # Handshake
            init_res = client.initialize()
            self.assertIn("userAgent", init_res)
            self.assertTrue(client._client.is_initialized)

            # List threads (interleaved notification handled seamlessly)
            threads = client.list_threads()
            self.assertEqual(len(threads), 1)
            self.assertEqual(threads[0]["id"], "t1")

            # Verify notification was queued
            notifs = client._client.get_notifications()
            self.assertEqual(len(notifs), 1)
            self.assertEqual(notifs[0]["method"], "test/notification")

            # Read existing thread
            t1 = client.read_thread("t1")
            self.assertIsNotNone(t1)
            self.assertEqual(t1["threadId"], "t1")

            # Read missing thread (returns None on -32600)
            t_missing = client.read_thread("t_missing")
            self.assertIsNone(t_missing)

            # Shutdown
            client.shutdown()

    def test_transactional_repair_and_source_immutability(self):
        with safe_temp_codex_home() as chome:
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
        with safe_temp_codex_home() as chome:
            sdir = chome / "sessions"
            sdir.mkdir(parents=True)

            recorder = BlackBoxRecorder()
            observer = StateObserver(chome, recorder)

            # Initial poll (empty)
            evs = observer.poll_once()
            self.assertEqual(len(evs), 0)
            self.assertIsNotNone(observer.last_known_good)

            # Add session file
            f1 = sdir / "sess1.jsonl"
            f1.write_text('{"turn":1}\n', encoding="utf-8")

            evs2 = observer.poll_once()
            self.assertEqual(len(evs2), 1)
            self.assertEqual(evs2[0].session_id, "sess1")

    def test_portable_roundtrip_with_derived_reconstruction(self):
        with safe_temp_codex_home() as td:
            src_home = td / "src_home"
            tgt_home = td / "tgt_home"
            src_sdir = src_home / "sessions"
            src_sdir.mkdir(parents=True)

            sess_file = src_sdir / "s_export.jsonl"
            sess_file.write_text('{"turn": 1, "text": "hello"}\n', encoding="utf-8")

            zip_path = td / "exported.rescue.zip"

            # 1. Export
            manifest = PortableSessionEngine.export_session(sess_file, zip_path)
            self.assertEqual(manifest.session_id, "s_export")
            self.assertEqual(manifest.source_integrity, "PROVEN_COMPLETE")

            # 2. Inspect
            inspected = PortableSessionEngine.inspect_package(zip_path)
            self.assertEqual(inspected.rollout_sha256, manifest.rollout_sha256)

            # 3. Plan & Import into isolated target
            plan = PortableSessionEngine.plan_import(zip_path, tgt_home)
            self.assertTrue(plan.safe_to_import)

            res = PortableSessionEngine.execute_import(zip_path, tgt_home, rebuild_sqlite_index=True)
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "IMPORTED")

            # 4. Verify target state
            tgt_file = tgt_home / "sessions" / "s_export.jsonl"
            self.assertTrue(tgt_file.exists())
            self.assertEqual(tgt_file.read_text(encoding="utf-8"), sess_file.read_text(encoding="utf-8"))

            tgt_db = tgt_home / "state_5.sqlite"
            self.assertTrue(tgt_db.exists())


if __name__ == "__main__":
    unittest.main()
