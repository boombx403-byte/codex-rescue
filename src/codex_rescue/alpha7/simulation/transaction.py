from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.invariants import (
    InvariantCheckResult,
    InvariantEngine,
    InvariantEvaluation,
    InvariantId,
    InvariantStatus,
)
from codex_rescue.alpha7.recovery.backup import BackupEngine, BackupManifest
from codex_rescue.alpha7.simulation.simulator import RepairSimulator, SimulationResult
from codex_rescue.alpha7.surfaces.desktop import DesktopAdapter, WriterStatus


def compute_file_sha256(path: Path) -> str:
    """Computes SHA-256 hash using streaming 64KB chunks to preserve bounded memory."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


@dataclass
class TransactionResult:
    operation_id: str
    status: str  # "REPAIRED", "ROLLED_BACK", "BLOCKED", "STALE_PLAN", "VERIFY_FAILED"
    initial_source_sha256: str
    final_source_sha256: str
    source_preserved: bool
    backup_manifest: Optional[BackupManifest] = None
    applied_mutations_count: int = 0
    message: str = ""
    invariants: List[InvariantCheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "status": self.status,
            "source_preserved": self.source_preserved,
            "initial_source_sha256": self.initial_source_sha256,
            "final_source_sha256": self.final_source_sha256,
            "applied_mutations_count": self.applied_mutations_count,
            "message": self.message,
            "invariants": [
                {"id": i.invariant_id.value, "status": i.status.value, "message": i.message}
                for i in self.invariants
            ],
        }


class TransactionalRepairEngine:
    """Atomic, reversible repair engine for derived SQLite state with real writer guards and streaming hashing."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.backup_engine = BackupEngine(self.codex_home / "backups")
        self.desktop_adapter = DesktopAdapter(self.codex_home)

    def execute_derived_index_repair(
        self,
        session_file: Path,
        state_db_name: str = "state_5.sqlite",
    ) -> TransactionResult:
        op_id = f"tx_{int(time.time()*1000)}"
        invariants: List[InvariantCheckResult] = []

        if not session_file.exists():
            return TransactionResult(
                operation_id=op_id,
                status="BLOCKED",
                initial_source_sha256="",
                final_source_sha256="",
                source_preserved=False,
                message=f"Session file not found: {session_file}",
            )

        # 1. Snapshot precondition & initial source hash via streaming
        sha_before = compute_file_sha256(session_file)
        session_id = session_file.stem
        if session_id.startswith("rollout-"):
            session_id = session_id[8:]

        # 2. Check active writer precondition (INV-003) - Fail-closed on ACTIVE or UNKNOWN
        writer_status = self.desktop_adapter.detect_writer_status()
        if writer_status != WriterStatus.INACTIVE_CONFIRMED:
            inv_writer = InvariantCheckResult(
                invariant_id=InvariantId.INV_003,
                status=InvariantStatus.FAIL,
                message=f"Mutation blocked: active writer status is {writer_status.value}",
            )
            invariants.append(inv_writer)
            return TransactionResult(
                operation_id=op_id,
                status="BLOCKED",
                initial_source_sha256=sha_before,
                final_source_sha256=sha_before,
                source_preserved=True,
                message=f"Mutation blocked: writer state is {writer_status.value} (fail-closed guard)",
                invariants=invariants,
            )

        inv_writer = InvariantCheckResult(
            invariant_id=InvariantId.INV_003,
            status=InvariantStatus.PASS,
            message="No active Codex writer processes detected.",
        )
        invariants.append(inv_writer)

        # 3. Simulate repair in isolated temp sandbox (INV-015)
        sim_res = RepairSimulator.simulate_derived_index_repair(session_file)
        invariants.extend(sim_res.invariants)
        if not sim_res.safe_to_apply:
            return TransactionResult(
                operation_id=op_id,
                status="BLOCKED",
                initial_source_sha256=sha_before,
                final_source_sha256=sha_before,
                source_preserved=True,
                message="Sandbox simulation failed safety invariants.",
                invariants=invariants,
            )

        # 4. Create Pre-Mutation Backup (INV-005)
        target_db = self.codex_home / state_db_name
        backup_targets = [session_file]
        if target_db.exists():
            backup_targets.append(target_db)

        backup_manifest = self.backup_engine.create_pre_mutation_backup(backup_targets, operation_id=op_id)
        if not backup_manifest.verified:
            return TransactionResult(
                operation_id=op_id,
                status="BLOCKED",
                initial_source_sha256=sha_before,
                final_source_sha256=sha_before,
                source_preserved=True,
                message="Pre-mutation backup verification failed.",
                invariants=invariants,
            )

        # 5. Recheck preconditions immediately before mutation (INV-015)
        current_sha = compute_file_sha256(session_file)
        if current_sha != sha_before:
            return TransactionResult(
                operation_id=op_id,
                status="STALE_PLAN",
                initial_source_sha256=sha_before,
                final_source_sha256=current_sha,
                source_preserved=False,
                message="Source rollout changed immediately prior to mutation. Aborting stale plan.",
                invariants=invariants,
            )

        writer_recheck = self.desktop_adapter.detect_writer_status()
        if writer_recheck != WriterStatus.INACTIVE_CONFIRMED:
            return TransactionResult(
                operation_id=op_id,
                status="BLOCKED",
                initial_source_sha256=sha_before,
                final_source_sha256=sha_before,
                source_preserved=True,
                message="Writer appeared immediately prior to mutation. Aborting.",
                invariants=invariants,
            )

        # 6. Apply narrow allowlisted mutation (Derived SQLite indexing)
        mutations_applied = 0
        try:
            target_db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(target_db), timeout=5.0)
            try:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name='threads'")
                if not cur.fetchone():
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS threads (
                            id TEXT PRIMARY KEY,
                            rollout_path TEXT NOT NULL,
                            created_at INTEGER NOT NULL,
                            updated_at INTEGER NOT NULL,
                            source TEXT NOT NULL DEFAULT 'cli',
                            model_provider TEXT NOT NULL DEFAULT 'openai',
                            cwd TEXT NOT NULL DEFAULT '',
                            title TEXT NOT NULL DEFAULT '',
                            sandbox_policy TEXT NOT NULL DEFAULT 'read-only',
                            approval_mode TEXT NOT NULL DEFAULT 'auto'
                        )
                        """
                    )

                cur.execute("PRAGMA table_info('threads')")
                existing_cols = {r[1]: r for r in cur.fetchall()}
                now_ts = int(time.time())

                row_data = {
                    "id": session_id,
                    "rollout_path": str(session_file.resolve()),
                    "created_at": now_ts,
                    "updated_at": now_ts,
                    "source": "cli",
                    "model_provider": "openai",
                    "cwd": str(self.codex_home),
                    "title": session_id,
                    "sandbox_policy": "read-only",
                    "approval_mode": "auto",
                }

                cols_to_insert = [c for c in row_data if c in existing_cols]
                placeholders = ", ".join("?" for _ in cols_to_insert)
                col_names = ", ".join(f'"{c}"' for c in cols_to_insert)
                values = tuple(row_data[c] for c in cols_to_insert)

                cur.execute(f"INSERT OR REPLACE INTO threads ({col_names}) VALUES ({placeholders})", values)
                conn.commit()
                mutations_applied = 1
            finally:
                conn.close()
        except Exception as e:
            # Rollback immediately on failure
            self.backup_engine.rollback(backup_manifest)
            return TransactionResult(
                operation_id=op_id,
                status="ROLLED_BACK",
                initial_source_sha256=sha_before,
                final_source_sha256=sha_before,
                source_preserved=True,
                backup_manifest=backup_manifest,
                message=f"Database write failed; state rolled back: {e}",
                invariants=invariants,
            )

        # 7. Post-Mutation Verification (INV-002 & INV-008) via streaming hash
        sha_after = compute_file_sha256(session_file)
        inv_immutability = InvariantEngine.check_source_immutability(sha_before, sha_after, is_derived_recovery=True)
        invariants.append(inv_immutability)

        if not inv_immutability.passed:
            self.backup_engine.rollback(backup_manifest)
            return TransactionResult(
                operation_id=op_id,
                status="ROLLED_BACK",
                initial_source_sha256=sha_before,
                final_source_sha256=sha_after,
                source_preserved=False,
                backup_manifest=backup_manifest,
                message="Source immutability violation detected; rolled back.",
                invariants=invariants,
            )

        return TransactionResult(
            operation_id=op_id,
            status="REPAIRED",
            initial_source_sha256=sha_before,
            final_source_sha256=sha_after,
            source_preserved=True,
            backup_manifest=backup_manifest,
            applied_mutations_count=mutations_applied,
            message="Derived state successfully repaired and verified. Source rollout preserved.",
            invariants=invariants,
        )
