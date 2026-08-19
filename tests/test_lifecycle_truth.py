from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_rescue.graph import build_session_graph
from codex_rescue.lifecycle_truth import (
    ARCHIVED_SUBAGENT_PRESENTATION_DIVERGENCE,
    LIVE_TURN_PRESENTATION_DIVERGENCE,
    STALE_ACTIVE_PRESENTATION,
    classify_archive_failure,
    classify_archived_subagent_presentation,
    classify_presentation_truth,
    classify_subagent_lifecycle,
    scan_durable_lifecycle,
)
from codex_rescue.spawn_edges import SPAWN_EDGE_CLOSED, SPAWN_EDGE_OPEN, SPAWN_EDGE_UNRECORDED
from codex_rescue.thread_store import (
    ROLLOUT_MISSING,
    THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE,
    WINDOWS_ROLLOUT_PATH_IDENTITY_DIVERGENCE,
)


class LifecycleTruthTests(unittest.TestCase):
    def test_live_running_child_is_working(self):
        result = classify_subagent_lifecycle(
            durable_state="NON_TERMINAL", runtime_active=True, presentation_active=None,
            spawn_edge_status=SPAWN_EDGE_OPEN,
        )
        self.assertEqual(result.status, "WORKING")
        self.assertTrue(result.dispatchable)

    def test_unknown_durable_state_is_not_promoted_to_working_by_live_writer_alone(self):
        result = classify_subagent_lifecycle(
            durable_state="UNKNOWN", runtime_active=True, presentation_active=None,
            spawn_edge_status=SPAWN_EDGE_OPEN,
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIsNone(result.dispatchable)

    def test_terminal_retained_child_is_done_not_closed(self):
        result = classify_subagent_lifecycle(
            durable_state="TERMINAL", runtime_active=None, presentation_active=None,
            spawn_edge_status=SPAWN_EDGE_OPEN,
        )
        self.assertEqual(result.status, "DONE")
        self.assertIsNone(result.dispatchable)
        self.assertNotEqual(result.status, "INACTIVE")

    def test_open_edge_with_unknown_runtime_does_not_fabricate_working(self):
        result = classify_subagent_lifecycle(
            durable_state="NON_TERMINAL", runtime_active=None, presentation_active=None,
            spawn_edge_status=SPAWN_EDGE_OPEN,
        )
        self.assertEqual(result.status, "UNKNOWN")

    def test_closed_edge_with_unknown_runtime_is_inactive(self):
        result = classify_subagent_lifecycle(
            durable_state="NON_TERMINAL", runtime_active=None, presentation_active=None,
            spawn_edge_status=SPAWN_EDGE_CLOSED,
        )
        self.assertEqual(result.status, "INACTIVE")
        self.assertFalse(result.dispatchable)

    def test_closed_edge_overrides_working_presentation_without_live_runtime(self):
        result = classify_subagent_lifecycle(
            durable_state="NON_TERMINAL", runtime_active=None, presentation_active=True,
            spawn_edge_status=SPAWN_EDGE_CLOSED,
        )
        self.assertEqual(result.status, "INACTIVE")
        self.assertFalse(result.dispatchable)
        self.assertEqual(result.presentation_state, "ACTIVE")

    def test_closed_edge_with_conflicting_live_runtime_is_unknown(self):
        result = classify_subagent_lifecycle(
            durable_state="NON_TERMINAL", runtime_active=True, presentation_active=True,
            spawn_edge_status=SPAWN_EDGE_CLOSED,
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIsNone(result.dispatchable)

    def test_unrecorded_edge_does_not_fabricate_closed(self):
        result = classify_subagent_lifecycle(
            durable_state="NON_TERMINAL", runtime_active=None, presentation_active=None,
            spawn_edge_status=SPAWN_EDGE_UNRECORDED,
        )
        self.assertEqual(result.status, "UNKNOWN")

    def test_stale_ui_active_backend_idle(self):
        result = classify_presentation_truth(
            ui_active=True, ui_progress_visible=False,
            backend_active=False, backend_progress_observed=False,
        )
        self.assertEqual(result.status, "DIVERGED")
        self.assertEqual(result.findings, (STALE_ACTIVE_PRESENTATION,))

    def test_renderer_stream_absent_while_backend_active(self):
        result = classify_presentation_truth(
            ui_active=True, ui_progress_visible=False,
            backend_active=True, backend_progress_observed=True,
        )
        self.assertEqual(result.status, "DIVERGED")
        self.assertEqual(result.findings, (LIVE_TURN_PRESENTATION_DIVERGENCE,))

    def test_unknown_presentation_stays_unknown(self):
        result = classify_presentation_truth(
            ui_active=None, ui_progress_visible=None,
            backend_active=True, backend_progress_observed=True,
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.presentation_state, "UNKNOWN")
        self.assertEqual(result.findings, ())

    def test_archived_subagent_is_not_corruption_without_presentation_evidence(self):
        self.assertEqual(
            classify_archived_subagent_presentation(is_subagent=True, archived=True, presented_top_level=None),
            (),
        )
        self.assertEqual(
            classify_archived_subagent_presentation(is_subagent=True, archived=True, presented_top_level=True),
            (ARCHIVED_SUBAGENT_PRESENTATION_DIVERGENCE,),
        )

    def test_archive_error_text_without_corroboration_is_not_root_cause_evidence(self):
        for text in (
            "archive failed: os error 2",
            "archive permission denied",
            "archive operation cancelled",
            "archive unsupported",
            "generic reference mismatch wording",
            "thread not found while unarchive requested",
        ):
            with self.subTest(text=text):
                findings = classify_archive_failure(
                    source_exists=True,
                    error_text=text,
                    windows_identity_divergence=False,
                    persisted_reference_divergence=False,
                )
                self.assertEqual(findings, ())
                self.assertNotIn(ROLLOUT_MISSING, findings)
                self.assertNotIn(THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE, findings)

    def test_archive_proven_persisted_reference_divergence_is_generic_divergence(self):
        findings = classify_archive_failure(
            source_exists=True,
            error_text="archive failed",
            windows_identity_divergence=False,
            persisted_reference_divergence=True,
        )
        self.assertEqual(findings, (THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE,))

    def test_archive_exact_windows_identity_divergence_is_specific(self):
        findings = classify_archive_failure(
            source_exists=True,
            error_text="archive failed: os error 2",
            windows_identity_divergence=True,
            persisted_reference_divergence=True,
        )
        self.assertEqual(findings, (WINDOWS_ROLLOUT_PATH_IDENTITY_DIVERGENCE,))

    def test_missing_source_requires_proven_absence(self):
        self.assertEqual(
            classify_archive_failure(
                source_exists=False, error_text="os error 2",
                windows_identity_divergence=None, persisted_reference_divergence=None,
            ),
            (ROLLOUT_MISSING,),
        )
        self.assertEqual(
            classify_archive_failure(
                source_exists=None, error_text="os error 2",
                windows_identity_divergence=None, persisted_reference_divergence=None,
            ),
            (),
        )

    def test_rollout_scanner_does_not_invent_spawn_edge_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "child.jsonl"
            path.write_text(
                json.dumps({"type": "event_msg", "payload": {"type": "turn_started"}}) + "\n"
                + json.dumps({"type": "event_msg", "payload": {"type": "turn_completed"}}) + "\n"
                + json.dumps({"type": "event_msg", "payload": {"type": "agent_closed"}}) + "\n",
                encoding="utf-8",
            )
            result = scan_durable_lifecycle(path)
            self.assertEqual(result.state, "TERMINAL")
            self.assertFalse(result.explicit_close)
            self.assertEqual(result.last_event, "turn_completed")


class GraphLifecycleTests(unittest.TestCase):
    @staticmethod
    def _write(path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    @staticmethod
    def _spawn_edges(home: Path, rows: list[tuple[str, str, str]]) -> None:
        db = sqlite3.connect(home / "state_5.sqlite")
        try:
            db.execute(
                "CREATE TABLE thread_spawn_edges ("
                "parent_thread_id TEXT NOT NULL, "
                "child_thread_id TEXT NOT NULL PRIMARY KEY, "
                "status TEXT NOT NULL)"
            )
            db.executemany("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)", rows)
            db.commit()
        finally:
            db.close()

    def test_nested_children_use_spawn_edge_state_without_ui_assumptions(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            sessions = home / "sessions"
            subagents = sessions / "subagents"
            root = sessions / "parent.jsonl"
            child1 = subagents / "child-one.jsonl"
            child2 = subagents / "child-two.jsonl"
            self._write(root, [{"type": "turn_started", "subagent_id": "child-one"}, {"type": "task_complete"}])
            self._write(child1, [{"type": "turn_started", "parent_session_id": "parent", "subagent_id": "child-two"}, {"type": "task_complete"}])
            self._write(child2, [{"type": "turn_started", "parent_session_id": "child-one"}, {"type": "agent_closed"}])
            self._spawn_edges(home, [("parent", "child-one", "open"), ("child-one", "child-two", "closed")])

            graph = build_session_graph(root, codex_home=home)
            self.assertEqual(graph.family_sessions_count, 3)
            self.assertEqual(graph.max_depth, 2)
            self.assertEqual(graph.root_node.lifecycle_class, "DONE")
            first = graph.root_node.children[0]
            second = first.children[0]
            self.assertEqual(first.lifecycle_class, "DONE")
            self.assertEqual(first.spawn_edge["status"], SPAWN_EDGE_OPEN)
            self.assertEqual(second.lifecycle_class, "INACTIVE")
            self.assertFalse(second.dispatchable)
            self.assertEqual(second.spawn_edge["status"], SPAWN_EDGE_CLOSED)
            self.assertEqual(second.presentation_state, "UNKNOWN")
            self.assertEqual(second.finding_ids, [])
            payload = graph.to_dict()
            self.assertEqual(payload["tree"]["children"][0]["children"][0]["spawn_edge"]["status"], SPAWN_EDGE_CLOSED)

    def test_live_runtime_requires_non_terminal_durable_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            sessions = home / "sessions"
            root = sessions / "running.jsonl"
            self._write(root, [{"type": "turn_started"}])
            root.with_suffix(".lock").write_text("12345", encoding="utf-8")
            with mock.patch("codex_rescue.evidence.is_pid_alive", return_value=True):
                graph = build_session_graph(root, codex_home=home)
            self.assertEqual(graph.root_node.lifecycle_class, "WORKING")
            self.assertEqual(graph.root_node.lifecycle_status, "active")
            self.assertEqual(graph.root_node.presentation_state, "UNKNOWN")
            self.assertEqual(graph.root_node.spawn_edge["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
