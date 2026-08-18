from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.graph import PathNamespace, SurfaceObservation, SurfaceVisibility, detect_path_namespace, normalize_canonical_path


@dataclass
class DesktopHealthReport:
    desktop_process_running: bool = False
    app_server_reachable: bool = False
    filesystem_threads_count: int = 0
    sqlite_threads_count: int = 0
    app_server_threads_count: int = 0
    filesystem_only_count: int = 0
    sqlite_only_count: int = 0
    projection_divergence_count: int = 0
    broken_paths_count: int = 0
    active_writers_count: int = 0
    overall_status: str = "HEALTHY"  # HEALTHY, DEGRADED, BLOCKED, UNKNOWN
    data_loss_evidence: str = "NONE"  # NONE, SUSPECTED, CONFIRMED
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "desktop_process_running": self.desktop_process_running,
            "app_server_reachable": self.app_server_reachable,
            "filesystem_threads_count": self.filesystem_threads_count,
            "sqlite_threads_count": self.sqlite_threads_count,
            "app_server_threads_count": self.app_server_threads_count,
            "filesystem_only_count": self.filesystem_only_count,
            "sqlite_only_count": self.sqlite_only_count,
            "projection_divergence_count": self.projection_divergence_count,
            "broken_paths_count": self.broken_paths_count,
            "active_writers_count": self.active_writers_count,
            "overall_status": self.overall_status,
            "data_loss_evidence": self.data_loss_evidence,
            "details": self.details,
        }


class DesktopAdapter:
    """First-class inspection adapter for Codex Desktop."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.state_db_path = self.codex_home / "state.db"

    def get_status(self) -> DesktopHealthReport:
        report = DesktopHealthReport()

        # 1. Discover filesystem threads
        fs_sessions = {}
        sessions_dir = self.codex_home / "sessions"
        archived_dir = self.codex_home / "archived_sessions"

        for sdir in [sessions_dir, archived_dir]:
            if sdir.exists():
                for p in sdir.glob("*.jsonl"):
                    sid = p.stem
                    fs_sessions[sid] = p

        report.filesystem_threads_count = len(fs_sessions)

        # 2. Inspect SQLite threads
        sqlite_sessions = set()
        if self.state_db_path.exists():
            try:
                uri = f"file:{self.state_db_path.resolve()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=2.0)
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='threads'")
                    if cursor.fetchone():
                        cursor.execute("SELECT id, rollout_path FROM threads")
                        for row in cursor.fetchall():
                            tid = row[0]
                            rpath = row[1] if len(row) > 1 else None
                            sqlite_sessions.add(tid)
                            if rpath and not Path(rpath).exists() and not (self.codex_home / rpath).exists():
                                report.broken_paths_count += 1
                finally:
                    conn.close()
            except Exception as e:
                report.details["sqlite_error"] = str(e)

        report.sqlite_threads_count = len(sqlite_sessions)

        # 3. Calculate divergences
        fs_set = set(fs_sessions.keys())
        report.filesystem_only_count = len(fs_set - sqlite_sessions)
        report.sqlite_only_count = len(sqlite_sessions - fs_set)

        if report.filesystem_only_count > 0 or report.broken_paths_count > 0 or report.sqlite_only_count > 0:
            report.overall_status = "DEGRADED"
        else:
            report.overall_status = "HEALTHY"

        return report

    def get_session_diff(self, session_id: str) -> Dict[str, Any]:
        """Compares filesystem rollout state against Desktop SQLite record."""
        report = self.get_status()
        session_file = None
        for sdir in [self.codex_home / "sessions", self.codex_home / "archived_sessions"]:
            cand = sdir / f"{session_id}.jsonl"
            if cand.exists():
                session_file = cand
                break

        sqlite_data = None
        if self.state_db_path.exists():
            try:
                uri = f"file:{self.state_db_path.resolve()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=2.0)
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM threads WHERE id=?", (session_id,))
                    row = cur.fetchone()
                    if row:
                        sqlite_data = [str(x) for x in row]
                finally:
                    conn.close()
            except Exception:
                pass

        return {
            "session_id": session_id,
            "filesystem_exists": session_file is not None,
            "filesystem_path": str(session_file) if session_file else None,
            "sqlite_exists": sqlite_data is not None,
            "sqlite_row": sqlite_data,
            "status": "MATCH" if (session_file is not None and sqlite_data is not None) else "DIVERGENT",
        }
