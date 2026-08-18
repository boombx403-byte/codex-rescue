from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.graph import PathNamespace, detect_path_namespace
from codex_rescue.alpha7.invariants import (
    InvariantCheckResult,
    InvariantEngine,
    InvariantEvaluation,
    InvariantId,
    InvariantStatus,
)


@dataclass
class PortableManifest:
    package_version: str
    session_id: str
    rollout_filename: str
    rollout_sha256: str
    rollout_bytes: int
    created_at: float
    source_platform: str
    source_namespace: str
    source_integrity: str = "PROVEN_COMPLETE"
    records_count: int = 0
    rollout_schema_version: int = 1
    archive_state: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "package_version": self.package_version,
            "session_id": self.session_id,
            "rollout_filename": self.rollout_filename,
            "rollout_sha256": self.rollout_sha256,
            "rollout_bytes": self.rollout_bytes,
            "created_at": self.created_at,
            "source_platform": self.source_platform,
            "source_namespace": self.source_namespace,
            "source_integrity": self.source_integrity,
            "records_count": self.records_count,
            "rollout_schema_version": self.rollout_schema_version,
            "archive_state": self.archive_state,
            "metadata": self.metadata,
        }


@dataclass
class ImportPlan:
    session_id: str
    target_rollout_path: str
    conflict_detected: bool
    conflict_reason: Optional[str]
    safe_to_import: bool
    requires_remapping: bool
    invariants: List[InvariantCheckResult] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return self.safe_to_import

    @property
    def has_conflict(self) -> bool:
        return self.conflict_detected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_rollout_path": self.target_rollout_path,
            "conflict_detected": self.conflict_detected,
            "conflict_reason": self.conflict_reason,
            "safe_to_import": self.safe_to_import,
            "requires_remapping": self.requires_remapping,
            "invariants": [
                {"id": i.invariant_id.value, "status": i.status.value, "message": i.message}
                for i in self.invariants
            ],
        }


class PortableSessionEngine:
    """Exports and imports portable session packages with integrity, dry-run, and derived state reconstruction."""

    @staticmethod
    def export_session(
        session_path: Path,
        output_zip_path: Path,
        metadata: Optional[Dict[str, Any]] = None,
        workspace_path: Optional[str] = None,
        is_archived: bool = False,
    ) -> PortableManifest:
        if not session_path.exists():
            raise FileNotFoundError(f"Session file not found: {session_path}")

        data = session_path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        session_id = session_path.stem
        if session_id.startswith("rollout-"):
            session_id = session_id[8:]

        # Count records
        records_count = sum(1 for line in data.splitlines() if line.strip())

        meta = dict(metadata or {})
        if workspace_path:
            meta["workspace_path"] = workspace_path

        ns = detect_path_namespace(session_path)
        manifest = PortableManifest(
            package_version="1.0",
            session_id=session_id,
            rollout_filename=session_path.name,
            rollout_sha256=sha,
            rollout_bytes=len(data),
            created_at=time.time(),
            source_platform=os.name,
            source_namespace=ns.value,
            records_count=records_count,
            archive_state=is_archived,
            metadata=meta,
        )

        output_zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest.to_dict(), indent=2))
            zf.writestr(session_path.name, data)

        return manifest

    @staticmethod
    def inspect_package(package_zip_path: Path) -> PortableManifest:
        if not package_zip_path.exists():
            raise FileNotFoundError(f"Package not found: {package_zip_path}")

        try:
            with zipfile.ZipFile(package_zip_path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    raise ValueError("Package missing manifest.json")
                manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))

                # Verify payload file exists and matches hash
                fname = manifest_data["rollout_filename"]
                if fname not in zf.namelist():
                    raise ValueError(f"Package missing declared rollout file: {fname}")

                payload = zf.read(fname)
                calc_sha = hashlib.sha256(payload).hexdigest()
                if calc_sha != manifest_data["rollout_sha256"]:
                    raise ValueError("Package integrity check failed: SHA-256 mismatch")

                return PortableManifest(**manifest_data)
        except zipfile.BadZipFile as e:
            raise ValueError(f"Corrupt or invalid zip archive: {e}")

    @staticmethod
    def plan_import(
        package_zip_path: Path,
        target_codex_home: Path,
    ) -> ImportPlan:
        manifest = PortableSessionEngine.inspect_package(package_zip_path)
        invariants: List[InvariantCheckResult] = []

        # Check schema support (INV-007)
        inv_schema = InvariantEngine.check_schema_support(
            manifest.rollout_schema_version,
            {1},
            is_mutation_operation=True,
        )
        invariants.append(inv_schema)

        target_dir = (
            target_codex_home / "archived_sessions"
            if manifest.archive_state
            else target_codex_home / "sessions"
        )
        target_file = target_dir / manifest.rollout_filename

        conflict = False
        reason = None
        if target_file.exists():
            conflict = True
            reason = f"Target session file already exists: {target_file}"

        safe = inv_schema.passed and not conflict

        return ImportPlan(
            session_id=manifest.session_id,
            target_rollout_path=str(target_file),
            conflict_detected=conflict,
            conflict_reason=reason,
            safe_to_import=safe,
            requires_remapping=(manifest.source_platform != os.name),
            invariants=invariants,
        )

    @staticmethod
    def execute_import(
        package_zip_path: Path,
        target_codex_home: Path,
        plan: Optional[ImportPlan] = None,
        dry_run: bool = False,
        rebuild_sqlite_index: bool = True,
    ) -> Any:
        active_plan = plan or PortableSessionEngine.plan_import(package_zip_path, target_codex_home)
        if not active_plan.safe_to_import:
            return {"success": False, "action": "BLOCKED", "reason": active_plan.conflict_reason}

        if dry_run:
            return {"success": True, "action": "DRY_RUN_PASSED", "plan": active_plan.to_dict()}

        manifest = PortableSessionEngine.inspect_package(package_zip_path)
        target_path = Path(active_plan.target_rollout_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(package_zip_path, "r") as zf:
            payload = zf.read(manifest.rollout_filename)
            target_path.write_bytes(payload)

        # Reconstruct derived SQLite index in target CODEX_HOME
        if rebuild_sqlite_index:
            state_db = target_codex_home / "state_5.sqlite"
            try:
                conn = sqlite3.connect(str(state_db), timeout=5.0)
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS threads (
                            id TEXT PRIMARY KEY,
                            rollout_path TEXT,
                            created_at REAL,
                            updated_at REAL
                        )
                        """
                    )
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO threads (id, rollout_path, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (manifest.session_id, str(target_path.resolve()), time.time(), time.time()),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass

        return {
            "success": True,
            "action": "IMPORTED",
            "session_id": manifest.session_id,
            "target_path": str(target_path),
        }
