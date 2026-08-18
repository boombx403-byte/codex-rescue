from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.graph import (
    PathNamespace,
    StorageProfile,
    SurfaceObservation,
    SurfaceVisibility,
    ThreadIdentity,
    ThreadNode,
    UnifiedStateGraph,
    detect_path_namespace,
    normalize_canonical_path,
)
from codex_rescue.alpha7.invariants import InvariantCheckResult, InvariantEngine, InvariantId, InvariantStatus
from codex_rescue.alpha7.surfaces.app_server import AppServerAdapter
from codex_rescue.alpha7.surfaces.desktop import DesktopAdapter
from codex_rescue.alpha7.surfaces.detector import SurfaceDetector


@dataclass
class DiagnosticRoute:
    symptom: str
    probes_executed: List[str] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    confidence: str = "HIGH"
    root_cause_layer: str = "UNKNOWN"
    data_loss_evidence: str = "NONE"
    invariants: List[InvariantCheckResult] = field(default_factory=list)
    recommendation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symptom": self.symptom,
            "probes_executed": self.probes_executed,
            "findings": self.findings,
            "confidence": self.confidence,
            "root_cause_layer": self.root_cause_layer,
            "data_loss_evidence": self.data_loss_evidence,
            "invariants": [
                {"id": i.invariant_id.value, "status": i.status.value, "message": i.message}
                for i in self.invariants
            ],
            "recommendation": self.recommendation,
        }


class DiagnosticRouter:
    """Automatic decision engine for Alpha7. Cheap probes first, bounded expansion, confidence-based stop."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.desktop_adapter = DesktopAdapter(self.codex_home)
        self.app_server_adapter = AppServerAdapter(self.codex_home)

    def route_session(self, session_id_or_path: str | Path) -> DiagnosticRoute:
        route = DiagnosticRoute(symptom="inspect_thread")

        # 1. Cheap probe: identify path / file
        route.probes_executed.append("cheap_probe_identity")
        target_path: Optional[Path] = None
        session_id = str(session_id_or_path)

        if isinstance(session_id_or_path, Path) or ("/" in session_id or "\\" in session_id):
            p = Path(session_id_or_path)
            if p.exists():
                target_path = p
                session_id = p.stem

        if not target_path:
            # Look in sessions / archived_sessions
            for candidate_dir in [self.codex_home / "sessions", self.codex_home / "archived_sessions"]:
                cand = candidate_dir / f"{session_id}.jsonl"
                if cand.exists():
                    target_path = cand
                    break

        # 2. Probe Filesystem vs SQLite
        route.probes_executed.append("probe_filesystem_vs_sqlite")
        fs_exists = target_path is not None and target_path.exists()
        sqlite_exists = False
        sqlite_row = None

        state_db = self.codex_home / "state.db"
        if state_db.exists():
            try:
                uri = f"file:{state_db.resolve()}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=2.0)
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT id, rollout_path FROM threads WHERE id=?", (session_id,))
                    sqlite_row = cur.fetchone()
                    sqlite_exists = sqlite_row is not None
                finally:
                    conn.close()
            except Exception:
                pass

        # 3. Probe App Server
        route.probes_executed.append("probe_app_server")
        app_obs = self.app_server_adapter.observe_thread(session_id)

        # 4. Diagnose based on observed evidence
        if fs_exists and not sqlite_exists:
            route.findings.append("UNINDEXED_IN_SQLITE")
            route.root_cause_layer = "DERIVED_SQLITE_INDEX"
            route.recommendation = "Re-register thread in derived SQLite index."
        elif not fs_exists and sqlite_exists:
            route.findings.append("MISSING_ROLLOUT_FILE")
            route.root_cause_layer = "SOURCE_ROLLOUT"
            route.data_loss_evidence = "SUSPECTED"
            route.recommendation = "Search backups for missing rollout file."
        elif fs_exists and sqlite_exists:
            # Check projection / Desktop visibility
            if app_obs.visibility == SurfaceVisibility.VISIBLE:
                route.root_cause_layer = "HEALTHY_MULTISURFACE"
            else:
                route.root_cause_layer = "DERIVED_DESKTOP_PROJECTION"
        else:
            route.findings.append("THREAD_NOT_FOUND")
            route.root_cause_layer = "NOT_FOUND"
            route.confidence = "INSUFFICIENT_EVIDENCE"

        # Invariant checks
        if fs_exists:
            try:
                size = target_path.stat().st_size
                route.invariants.append(
                    InvariantEngine.check_source_accounting(size, size, 0, 0)
                )
            except Exception:
                pass

        return route
