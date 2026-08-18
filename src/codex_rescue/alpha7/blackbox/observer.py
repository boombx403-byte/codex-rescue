from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codex_rescue.alpha7.blackbox.recorder import BlackBoxRecorder, EventType, StructuralEvent


class StateObserver:
    """Active observer polling safe local state to generate real Black Box structural events."""

    def __init__(self, codex_home: Path, recorder: BlackBoxRecorder):
        self.codex_home = codex_home
        self.recorder = recorder
        self._last_fs_state: Dict[str, float] = {}
        self._last_db_state: Dict[str, int] = {}
        self.poll_count = 0

    def poll_once(self) -> List[StructuralEvent]:
        """Performs one observation sweep across filesystem and SQLite state."""
        events: List[StructuralEvent] = []
        self.poll_count += 1

        # 1. Observe filesystem session rollouts
        sessions_dir = self.codex_home / "sessions"
        current_fs_state: Dict[str, float] = {}
        if sessions_dir.exists():
            for p in sessions_dir.rglob("*.jsonl"):
                try:
                    current_fs_state[str(p)] = p.stat().st_mtime
                except OSError:
                    continue

        # Detect additions & modifications
        for p_str, mtime in current_fs_state.items():
            sid = Path(p_str).stem
            if p_str not in self._last_fs_state:
                e = self.recorder.record_event(
                    EventType.ROLLOUT_CREATED,
                    session_id=sid,
                    details={"path": p_str, "mtime": mtime, "source": "OBSERVED"},
                )
                events.append(e)
            elif mtime > self._last_fs_state[p_str]:
                e = self.recorder.record_event(
                    EventType.ROLLOUT_APPENDED,
                    session_id=sid,
                    details={"path": p_str, "mtime": mtime, "source": "OBSERVED"},
                )
                events.append(e)

        # Detect deletions
        for p_str in self._last_fs_state:
            if p_str not in current_fs_state:
                sid = Path(p_str).stem
                e = self.recorder.record_event(
                    EventType.ROLLOUT_DELETED,
                    session_id=sid,
                    details={"path": p_str, "source": "OBSERVED"},
                )
                events.append(e)

        self._last_fs_state = current_fs_state

        # 2. Observe SQLite state databases
        current_db_state: Dict[str, int] = {}
        for db_name in ("state_5.sqlite", "state.db", "codex.db"):
            db_path = self.codex_home / db_name
            if not db_path.exists() or db_path.stat().st_size == 0:
                continue

            try:
                uri = f"file:{db_path.resolve()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=0.1)
                try:
                    conn.execute("PRAGMA query_only=ON")
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_schema WHERE type='table'")
                    tables = [str(r[0]) for r in cur.fetchall()]
                    for t in tables:
                        if t in ("threads", "thread_history_projection_state", "session_index"):
                            cur.execute(f"SELECT count(*) FROM \"{t}\"")
                            cnt = int(cur.fetchone()[0])
                            current_db_state[f"{db_name}:{t}"] = cnt
                finally:
                    conn.close()
            except Exception:
                continue

        # Detect SQLite table row count changes
        for db_table, count in current_db_state.items():
            if db_table in self._last_db_state and count != self._last_db_state[db_table]:
                e = self.recorder.record_event(
                    EventType.INDEX_ROW_UPDATED,
                    details={
                        "target": db_table,
                        "old_count": self._last_db_state[db_table],
                        "new_count": count,
                        "source": "OBSERVED",
                    },
                )
                events.append(e)

        self._last_db_state = current_db_state
        return events
