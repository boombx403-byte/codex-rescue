from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.invariants import InvariantCheckResult, InvariantEngine, InvariantStatus
from codex_rescue.alpha7.recovery.backup import BackupEngine
from codex_rescue.alpha7.surfaces.detector import SurfaceDetector


@dataclass
class SelfTestItem:
    name: str
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "details": self.details,
            "error": self.error,
        }


@dataclass
class SelfTestReport:
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    overall_status: str = "PASS"  # PASS, RESCUE_ACCESS_FAILURE, WARNINGS
    checks: List[SelfTestItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "overall_status": self.overall_status,
            "checks": [c.to_dict() for c in self.checks],
        }


class SelfTestEngine:
    """Distinguishes internal Rescue capability failures from user Codex state failures."""

    @staticmethod
    def run_self_test(codex_home: Optional[Path] = None) -> SelfTestReport:
        report = SelfTestReport()
        home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

        # 1. Check temp directory creation & sandbox capability
        try:
            with tempfile.TemporaryDirectory() as td:
                test_file = Path(td) / "probe.tmp"
                test_file.write_text("ok", encoding="utf-8")
                assert test_file.read_text(encoding="utf-8") == "ok"
            report.checks.append(SelfTestItem("sandbox_temp_creation", True))
        except Exception as e:
            report.checks.append(SelfTestItem("sandbox_temp_creation", False, error=str(e)))

        # 2. Check backup engine functionality
        try:
            with tempfile.TemporaryDirectory() as td:
                b_engine = BackupEngine(backup_root=Path(td) / "backups")
                sample = Path(td) / "sample.jsonl"
                sample.write_text('{"turn":1}\n', encoding="utf-8")
                manifest = b_engine.create_pre_mutation_backup([sample])
                assert manifest.verified
                assert len(manifest.entries) == 1
            report.checks.append(SelfTestItem("backup_and_hashing_engine", True))
        except Exception as e:
            report.checks.append(SelfTestItem("backup_and_hashing_engine", False, error=str(e)))

        # 3. Check surface discovery
        try:
            topo = SurfaceDetector.detect_topology(home)
            report.checks.append(
                SelfTestItem("surface_discovery", True, details={"surfaces_found": topo.detected_surface_count})
            )
        except Exception as e:
            report.checks.append(SelfTestItem("surface_discovery", False, error=str(e)))

        # 4. Check invariant engine
        try:
            inv = InvariantEngine.check_source_accounting(100, 100, 0, 0)
            assert inv.passed
            report.checks.append(SelfTestItem("invariant_engine", True))
        except Exception as e:
            report.checks.append(SelfTestItem("invariant_engine", False, error=str(e)))

        report.total_checks = len(report.checks)
        report.passed_checks = sum(1 for c in report.checks if c.passed)
        report.failed_checks = report.total_checks - report.passed_checks
        report.overall_status = "PASS" if report.failed_checks == 0 else "RESCUE_ACCESS_FAILURE"

        return report
