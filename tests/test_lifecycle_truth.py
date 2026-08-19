from __future__ import annotations

import json
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
from codex_rescue.thread_store import (
    ROLLOUT_MISSING,
    THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE,
    WINDOWS_ROLLOUT_PATH_IDENTITY_DIVERGENCE,
)


class LifecycleTruthTests(unittest.TestCase):
    def test_live_running_child_is_working(self):
        result = classify_subagent_lifecycle(
            durable_state="NON_TERMINAL",
            runtime_active=True,
            presentation_active=None,
        )
        self.assertEqual(result.status, "WORKING")
        self.assertTrue(result.dispatchable)
        self.assertNotEqual(result.status, "DONE")

    def test_unknown_durable_state_is_not_promoted_to_working_by_live_writer_alone(self):
        result = classify_subagent_lifecycle(
            durable_state="UNKNOWN",
            runtime_active=True,
            presentation_active=None,
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIsNone(result.dispatchable)

    def test_terminal_retained_child_is_done_not_closed(self):
        result = classify_subagent_lifecycle(
            durable_state="TERMINAL",
            runtime_active=None,
            presentation_active=None,
        )
        self.assertEqual(result.status, "DONE")
        self.assertIsNone(result.dispatchable)
        self.assertNotEqual(result.status, "INACTIVE")

    def test_explicitly_closed_child_is_inactive(self):
        result = classify_subagent_lifecycle(
            durable_state="CLOSED",
            runtime_active=None,
            presentation_active=None,
        )
        self.assertEqual(result.status, "INACTIVE")
        self.assertFalse(result.dispatchable)

    def test_closed_child_with_conflicting_live_runtime_is_unknown(self):
        result = classify_subagent_lifecycle(
            durable_state="CLOSED",
            runtime_active=True,
            presentation_active=None,
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIsNone(result.dispatchable)

    def test_stale_ui_active_backend_idle(self):
        result = classify_presentation_truth(
            ui_active=True,
            ui_progress_visible=False,
            backend_active=False,
            backend_progress_observed=False,
        )
        self.assertEqual(result.status, "DIVERGED")
        self.assertEqual(result.findings, (STALE_ACTIVE_PRESENTATION,))

    def test_renderer_stream_absent_while_backend_active(self):
        result = classify_presentation_truth(
            ui_active=True,
            ui_progress_visible=False,
            backend_active=True,
            backend_progress_observed=True,
        )
        self.assertEqual(result.status, "DIVERGED")
        self.assertEqual(result.findings, (LIVE_TURN_PRESENTATION_DIVERGENCE,))

    def test_unknown_presentation_stays_unknown(self):
        result = classify_presentation_truth(
            ui_active=None,
            ui_progress_visible=None,
            backend_active=True,
            backend_progress_observed=True,
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.presentation_state, "UNKNOWN")
        self.assertEqual(result.findings, ())

    def test_archived_subagent_is_not_corruption_without_presentation_evidence(self):
        self.assertEqual(
            classify_archived_subagent_presentation(
                is_subagent=True,
                archived=True,
                presented_top_level=None,
            ),
            (),
        )
        self.assertEqual(
            classify_archived_subagent_presentation(
                is_subagent=True,
                archived=True,
                presented_top_level=True,
            ),
            (ARCHIVED_SUBAGENT_PRESENTATION_DIVERGENCE,),
        )

    def test_archive_os_error_with_existing_source_is_generic_divergence(self):
        findings = classify_archive_failure(
            source_exists=True,
            error_text="archive failed: os error 2",
            windows_identity_divergence=False,
        )
        self.assertEqual(findings, (THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE,))
        self.assertNotIn(ROLLOUT_MISSING, findings)
        self.assertNotIn(WINDOWS_ROLLOUT_PATH_IDENTITY_DIVERGENCE, findings)

    def test_archive_exact_windows_identity_divergence_is_specific(self):
        findings = classify_archive_failure(
            source_exists=True,
            error_text="archive failed: os error 2",
            windows_identity_divergence=True,
        )
        self.assertEqual(findings, (WINDOWS_ROLLOUT_PATH_IDENTITY_DIVERGENCE,))
        self.assertNotIn(ROLLOUT_MISSING, findings)

    def test_missing_source_requires_proven_absence(self):
        self.assertEqual(
            classify_archive_failure(
                source_exists=False,
                error_text="os error 2",
                windows_identity_divergence=None,
            ),
            (ROLLOUT_MISSING,),
        )
        self.assertEqual(
            classify_archive_failure(
                source_exists=None,
                error_text="os error 2",
                windows_identity_divergence=None,
            ),
            (),
        )

    def test_durable_scanner_distinguishes_terminal_from_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "child.jsonl"
            path.write_text(
                json.dumps({"type": "event_msg", "payload": {"type": "turn_started"}}) + "\n"
                + json.dumps({"type": "event_msg", "payload": {"type": "turn_completed"}}) + "\n",
                encoding="utf-8",
            )
            terminal = scan_durable_lifecycle(path)
            self.assertEqual(terminal.state, "TERMINAL")
            self.assertFalse(terminal.explicit_close)

            path.write_text(
                path.read_text(encoding="utf-8")
                + json.dumps({"type": "event_msg", "payload": {"type": "agent_closed"}}) + "\n",
                encoding="utf-8",
            )
            closed = scan_durable_lifecycle(path)
            self.assertEqual(closed.state, "CLOSED")
            self.assertTrue(closed.explicit_close)


class GraphLifecycleTests(unittest.TestCase):
    @staticmethod
    def _write(path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_nested_children_are_classified_without_ui_assumptions(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            sessions = home / "sessions"
            subagents = sessions / "subagents"
            root = sessions / "parent.jsonl"
            child1 = subagents / "child-one.jsonl"
            child2 = subagents / "child-two.jsonl"

            self._write(
                root,
                [
                    {"type": "turn_started", "subagent_id": "child-one"},
                    {"type": "task_complete"},
                ],
            )
            self._write(
                child1,
                [
                    {"type": "turn_started", "parent_session_id": "parent", "subagent_id": "child-two"},
                    {"type": "task_complete"},
                ],
            )
            self._write(
                child2,
                [
                    {"type": "turn_started", "parent_session_id": "child-one"},
                    {"type": "agent_closed"},
                ],
            )

            graph = build_session_graph(root, codex_home=home)
            self.assertEqual(graph.family_sessions_count, 3)
            self.assertEqual(graph.max_depth, 2)
            self.assertEqual(graph.root_node.lifecycle_class, "DONE")
            first = graph.root_node.children[0]
            second = first.children[0]
            self.assertEqual(first.lifecycle_class, "DONE")
            self.assertEqual(second.lifecycle_class, "INACTIVE")
            self.assertEqual(second.presentation_state, "UNKNOWN")
            self.assertEqual(second.finding_ids, [])

    def test_live_runtime_requires_non_terminal_durable_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            sessions = home / "sessions"
            root = sessions / "running.jsonl"
            self._write(root, [{"type": "turn_started"}])
            lock = root.with_suffix(".lock")
            lock.write_text("12345", encoding="utf-8")

            with mock.patch("codex_rescue.evidence.is_pid_alive", return_value=True):
                graph = build_session_graph(root, codex_home=home)

            self.assertEqual(graph.root_node.lifecycle_class, "WORKING")
            self.assertEqual(graph.root_node.lifecycle_status, "active")
            self.assertEqual(graph.root_node.presentation_state, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
