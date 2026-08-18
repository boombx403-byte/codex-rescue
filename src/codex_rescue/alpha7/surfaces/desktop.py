from __future__ import annotations

import json
import os
import platform
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codex_rescue.alpha7.graph import (
    PathNamespace,
    SurfaceObservation,
    SurfaceVisibility,
    detect_path_namespace,
    normalize_canonical_path,
)

SQLITE_CANDIDATE_NAMES = (
    "state_5.sqlite",
    "state.db",
    "codex.db",
    "threads.db",
    "logs_2.sqlite",
)

STATE_TABLE_CANDIDATES = (
    "thread_history_projection_state",
    "threads",
    "session_index",
    "backfill_state",
)


@dataclass
class DiscoveredSessionFile:
    session_id: str
    path: Path
    is_archived: bool
    size_bytes: int
    modified_time: float


@dataclass
class DesktopHealthReport:
    desktop_process_running: bool = False
    desktop_process_pids: List[int] = field(default_factory=list)
    app_server_reachable: bool = False
    discovered_db_paths: List[str] = field(default_factory=list)
    introspected_tables: Dict[str, List[str]] = field(default_factory=dict)
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
    is_truncated_discovery: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "desktop_process_running": self.desktop_process_running,
            "desktop_process_pids": self.desktop_process_pids,
            "app_server_reachable": self.app_server_reachable,
            "discovered_db_paths": self.discovered_db_paths,
            "introspected_tables": self.introspected_tables,
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
            "is_truncated_discovery": self.is_truncated_discovery,
            "details": self.details,
        }


class DesktopAdapter:
    """Production-grade Codex Desktop adapter with multi-DB discovery, schema introspection, and process tracking."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

    def detect_running_processes(self) -> Tuple[bool, List[int]]:
        """Introspects OS process table for active Codex Desktop / electron instances."""
        pids: List[int] = []
        system = platform.system()

        try:
            if system == "Windows":
                # Use tasklist
                cmd = ["tasklist", "/FI", "IMAGENAME eq Codex.exe", "/FO", "CSV", "/NH"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        parts = [p.strip(' "') for p in line.split(",")]
                        if len(parts) >= 2 and parts[1].isdigit():
                            pids.append(int(parts[1]))
            else:
                # Use pgrep or ps
                cmd = ["pgrep", "-f", "Codex"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        if line.strip().isdigit():
                            pids.append(int(line.strip()))
        except Exception:
            pass

        return len(pids) > 0, pids

    def discover_all_sessions(
        self,
        max_scan_limit: int = 10000,
    ) -> Tuple[List[DiscoveredSessionFile], bool]:
        """Discovers standard, nested, and date-based session rollouts across sessions and archived_sessions."""
        sessions: List[DiscoveredSessionFile] = []
        is_truncated = False

        sessions_dir = self.codex_home / "sessions"
        archived_dir = self.codex_home / "archived_sessions"

        for sdir, is_archived in [(sessions_dir, False), (archived_dir, True)]:
            if not sdir.exists():
                continue

            # Scan recursively: *.jsonl and rollout-*.jsonl
            try:
                for p in sdir.rglob("*.jsonl"):
                    if len(sessions) >= max_scan_limit:
                        is_truncated = True
                        break

                    try:
                        stat = p.stat()
                        sid = p.stem
                        if sid.startswith("rollout-"):
                            sid = sid[8:]
                        sessions.append(
                            DiscoveredSessionFile(
                                session_id=sid,
                                path=p,
                                is_archived=is_archived,
                                size_bytes=stat.st_size,
                                modified_time=stat.st_mtime,
                            )
                        )
                    except OSError:
                        continue
            except Exception:
                continue

        return sessions, is_truncated

    def get_status(self, max_scan_limit: int = 10000) -> DesktopHealthReport:
        report = DesktopHealthReport()

        # 1. Process detection
        proc_running, pids = self.detect_running_processes()
        report.desktop_process_running = proc_running
        report.desktop_process_pids = pids

        # 2. Filesystem sessions discovery
        fs_sessions, is_trunc = self.discover_all_sessions(max_scan_limit=max_scan_limit)
        report.filesystem_threads_count = len(fs_sessions)
        report.is_truncated_discovery = is_trunc
        fs_map = {s.session_id: s for s in fs_sessions}

        # 3. Discover SQLite state databases
        sqlite_sessions: Set[str] = set()
        for db_name in SQLITE_CANDIDATE_NAMES:
            db_path = self.codex_home / db_name
            if not db_path.exists() or db_path.stat().st_size == 0:
                continue

            report.discovered_db_paths.append(str(db_path))
            try:
                uri = f"file:{db_path.resolve()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=0.5)
                try:
                    conn.execute("PRAGMA query_only=ON")
                    conn.execute("PRAGMA busy_timeout=100")
                    cur = conn.cursor()

                    # Introspect tables
                    cur.execute("SELECT name FROM sqlite_schema WHERE type='table'")
                    tables = [str(r[0]) for r in cur.fetchall()]
                    report.introspected_tables[db_name] = tables

                    # Inspect thread IDs and rollout paths
                    for target_table in STATE_TABLE_CANDIDATES:
                        if target_table in tables:
                            # Check columns
                            cur.execute(f"PRAGMA table_info('{target_table}')")
                            cols = {str(r[1]) for r in cur.fetchall()}
                            id_col = next((c for c in ("thread_id", "session_id", "id") if c in cols), None)
                            path_col = next((c for c in ("rollout_path", "path") if c in cols), None)

                            if id_col:
                                query = f"SELECT \"{id_col}\"" + (f", \"{path_col}\"" if path_col else "") + f" FROM \"{target_table}\""
                                cur.execute(query)
                                for row in cur.fetchall():
                                    tid = str(row[0])
                                    sqlite_sessions.add(tid)
                                    if path_col and len(row) > 1 and row[1]:
                                        rpath = str(row[1])
                                        if not Path(rpath).exists() and not (self.codex_home / rpath).exists():
                                            report.broken_paths_count += 1
                finally:
                    conn.close()
            except Exception as e:
                report.details[f"db_error_{db_name}"] = str(e)

        report.sqlite_threads_count = len(sqlite_sessions)

        # 4. Divergences
        fs_set = set(fs_map.keys())
        report.filesystem_only_count = len(fs_set - sqlite_sessions)
        report.sqlite_only_count = len(sqlite_sessions - fs_set)

        if report.filesystem_only_count > 0 or report.broken_paths_count > 0 or report.sqlite_only_count > 0:
            report.overall_status = "DEGRADED"
        else:
            report.overall_status = "HEALTHY"

        return report

    def get_session_diff(self, session_id: str) -> Dict[str, Any]:
        """Compares physical filesystem rollout existence against all SQLite stores."""
        fs_sessions, _ = self.discover_all_sessions()
        matched_fs = next((s for s in fs_sessions if s.session_id == session_id), None)

        sqlite_matches = []
        for db_name in SQLITE_CANDIDATE_NAMES:
            db_path = self.codex_home / db_name
            if not db_path.exists():
                continue
            try:
                uri = f"file:{db_path.resolve()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=0.5)
                try:
                    cur = conn.cursor()
                    for t in STATE_TABLE_CANDIDATES:
                        try:
                            cur.execute(f"SELECT * FROM \"{t}\" WHERE id=? OR thread_id=? OR session_id=?", (session_id, session_id, session_id))
                            rows = cur.fetchall()
                            if rows:
                                sqlite_matches.append({"db": db_name, "table": t, "rows": [list(r) for r in rows]})
                        except Exception:
                            continue
                finally:
                    conn.close()
            except Exception:
                pass

        return {
            "session_id": session_id,
            "filesystem_exists": matched_fs is not None,
            "filesystem_path": str(matched_fs.path) if matched_fs else None,
            "is_archived": matched_fs.is_archived if matched_fs else False,
            "sqlite_matches": sqlite_matches,
            "sqlite_exists": len(sqlite_matches) > 0,
            "status": "MATCH" if (matched_fs and sqlite_matches) else "DIVERGENT",
        }
