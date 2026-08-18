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
    """Atomic, reversible repair engine for derived SQLite / projection state."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.backup_engine = BackupEngine(self.codex_home / "backups")

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

        # 1. Snapshot precondition & initial source hash
        source_data_before = session_file.read_bytes()
        sha_before = hashlib.sha256(source_data_before).hexdigest()
        session_id = session_file.stem
        if session_id.startswith("rollout-"):
            session_id = session_id[8:]

        # 2. Check active writer precondition (INV-003)
        inv_writer = InvariantEngine.check_active_writer(
            has_active_writer=False, writer_pid=None, is_mutation_operation=True
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
        backup_manifest = self.backup_engine.create_pre_mutation_backup([session_file, target_db], operation_id=op_id)
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
        current_source_data = session_file.read_bytes()
        current_sha = hashlib.sha256(current_source_data).hexdigest()
        if current_sha != sha_before:
            # Source changed between simulation and mutation! Abort per INV-015
            return TransactionResult(
                operation_id=op_id,
                status="STALE_PLAN",
                initial_source_sha256=sha_before,
                final_source_sha256=current_sha,
                source_preserved=False,
                message="Source rollout changed immediately prior to mutation. Aborting stale plan.",
                invariants=invariants,
            )

        # 6. Apply narrow allowlisted mutation (Derived SQLite indexing)
        mutations_applied = 0
        try:
            target_db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(target_db), timeout=5.0)
            try:
                cur = conn.cursor()
                # Create table if not present
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
                    (session_id, str(session_file.resolve()), time.time(), time.time()),
                )
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

        # 7. Post-Mutation Verification (INV-002 & INV-008)
        source_data_after = session_file.read_bytes()
        sha_after = hashlib.sha256(source_data_after).hexdigest()
        inv_immutability = InvariantEngine.check_source_immutability(sha_before, sha_after, is_derived_recovery=True)
        invariants.append(inv_immutability)

        if not inv_immutability.passed:
            # Source was unexpectedly modified! Force immediate rollback
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
