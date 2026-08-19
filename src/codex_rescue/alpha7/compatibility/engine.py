from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from codex_rescue.alpha7.invariants import InvariantCheckResult, InvariantEngine, InvariantStatus

import enum


class CompatibilityVerdict(str, enum.Enum):
    SUPPORTED = "SUPPORTED"
    BEST_EFFORT = "BEST_EFFORT"
    READ_ONLY_ONLY = "READ_ONLY_ONLY"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


SUPPORTED_ROLLOUT_SCHEMAS: Set[int] = {1, 2}
SUPPORTED_SQLITE_SCHEMAS: Set[int] = {1, 2, 3}


@dataclass
class CompatibilityReport:
    verdict: str
    rollout_schema_version: int
    sqlite_schema_version: int
    rollout_schema_supported: bool
    sqlite_schema_supported: bool
    app_server_supported: bool
    mutation_allowed: bool
    read_only_diagnosis_allowed: bool = True
    rejection_reason: Optional[str] = None
    invariants: List[InvariantCheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "rollout_schema_version": self.rollout_schema_version,
            "sqlite_schema_version": self.sqlite_schema_version,
            "rollout_schema_supported": self.rollout_schema_supported,
            "sqlite_schema_supported": self.sqlite_schema_supported,
            "app_server_supported": self.app_server_supported,
            "mutation_allowed": self.mutation_allowed,
            "read_only_diagnosis_allowed": self.read_only_diagnosis_allowed,
            "rejection_reason": self.rejection_reason,
            "invariants": [
                {"id": i.invariant_id.value, "status": i.status.value, "message": i.message}
                for i in self.invariants
            ],
        }


class CompatibilityEngine:
    """Evaluates compatibility between Codex Rescue Alpha7 and environment schemas."""

    @staticmethod
    def evaluate(
        rollout_schema: int = 1,
        sqlite_schema: int = 1,
        app_server_protocol: str = "v1",
    ) -> CompatibilityReport:
        rollout_ok = rollout_schema in SUPPORTED_ROLLOUT_SCHEMAS
        sqlite_ok = sqlite_schema in SUPPORTED_SQLITE_SCHEMAS
        app_ok = app_server_protocol in ("v1", "v2")

        invariants = []
        inv_rollout = InvariantEngine.check_schema_support(
            rollout_schema, SUPPORTED_ROLLOUT_SCHEMAS, is_mutation_operation=True
        )
        invariants.append(inv_rollout)

        inv_sqlite = InvariantEngine.check_schema_support(
            sqlite_schema, SUPPORTED_SQLITE_SCHEMAS, is_mutation_operation=True
        )
        invariants.append(inv_sqlite)

        mutation_allowed = rollout_ok and sqlite_ok
        reason = None
        if not mutation_allowed:
            if not rollout_ok:
                reason = f"UNKNOWN_ROLLOUT_SCHEMA_{rollout_schema}"
            elif not sqlite_ok:
                reason = f"UNKNOWN_SQLITE_SCHEMA_{sqlite_schema}"

        if rollout_ok and sqlite_ok and app_ok:
            verdict = CompatibilityVerdict.SUPPORTED.value
        elif rollout_ok and sqlite_ok:
            verdict = CompatibilityVerdict.BEST_EFFORT.value
        elif rollout_ok:
            verdict = CompatibilityVerdict.READ_ONLY_ONLY.value
        else:
            verdict = CompatibilityVerdict.UNSUPPORTED.value

        return CompatibilityReport(
            verdict=verdict,
            rollout_schema_version=rollout_schema,
            sqlite_schema_version=sqlite_schema,
            rollout_schema_supported=rollout_ok,
            sqlite_schema_supported=sqlite_ok,
            app_server_supported=app_ok,
            mutation_allowed=mutation_allowed,
            read_only_diagnosis_allowed=True,
            rejection_reason=reason,
            invariants=invariants,
        )
