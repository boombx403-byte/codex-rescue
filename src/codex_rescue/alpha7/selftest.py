from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.invariants import InvariantCheckResult, InvariantEngine, InvariantStatus
from codex_rescue.alpha7.recovery.backup import BackupEngine
from codex_rescue.alpha7.simulation.transaction import SchemaFingerprint
from codex_rescue.alpha7.surfaces.app_server import RealAppServerClient
from codex_rescue.alpha7.surfaces.detector import SurfaceDetector


@dataclass
class SelfTestItem:
    name: str
    passed: bool
    status: str = "PASS"  # PASS, NOT_FOUND, NOT_AVAILABLE, CORRUPT, FAIL
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "status": self.status,
            "details": self.details,
            "error": self.error,
        }


@dataclass
class SelfTestReport:
    rescue_runtime_status: str = "PASS"
    codex_binary_status: str = "NOT_FOUND"
    codex_home_status: str = "NOT_FOUND"
    codex_state_status: str = "NOT_FOUND"
    app_server_status: str = "NOT_AVAILABLE"
    backup_engine_status: str = "PASS"
    invariant_engine_status: str = "PASS"
    overall_status: str = "LIMITED"  # PASS, LIMITED, DEGRADED, FAIL
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    checks: List[SelfTestItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "rescue_runtime_status": self.rescue_runtime_status,
            "codex_binary_status": self.codex_binary_status,
            "codex_home_status": self.codex_home_status,
            "codex_state_status": self.codex_state_status,
            "app_server_status": self.app_server_status,
            "backup_engine_status": self.backup_engine_status,
            "invariant_engine_status": self.invariant_engine_status,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "checks": [c.to_dict() for c in self.checks],
        }


class SelfTestEngine:
    """Evaluates Rescue internal capabilities alongside real Codex environment readiness."""

    @staticmethod
    def run_self_test(codex_home: Optional[Path] = None) -> SelfTestReport:
        report = SelfTestReport()
        home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

        # 1. Check temp directory creation & sandbox capability (Rescue runtime)
        try:
            with tempfile.TemporaryDirectory() as td:
                test_file = Path(td) / "probe.tmp"
                test_file.write_text("ok", encoding="utf-8")
                assert test_file.read_text(encoding="utf-8") == "ok"
            report.checks.append(SelfTestItem("sandbox_temp_creation", True, status="PASS"))
        except Exception as e:
            report.checks.append(SelfTestItem("sandbox_temp_creation", False, status="FAIL", error=str(e)))
            report.rescue_runtime_status = "FAIL"

        # 2. Check backup engine functionality (Rescue runtime)
        try:
            with tempfile.TemporaryDirectory() as td:
                b_engine = BackupEngine(backup_root=Path(td) / "backups")
                sample = Path(td) / "sample.jsonl"
                sample.write_text('{"turn":1}\n', encoding="utf-8")
                manifest = b_engine.create_pre_mutation_backup([sample])
                assert manifest.verified
                assert len(manifest.entries) == 1
            report.checks.append(SelfTestItem("backup_and_hashing_engine", True, status="PASS"))
            report.backup_engine_status = "PASS"
        except Exception as e:
            report.checks.append(SelfTestItem("backup_and_hashing_engine", False, status="FAIL", error=str(e)))
            report.backup_engine_status = "FAIL"
            report.rescue_runtime_status = "FAIL"

        # 3. Check invariant engine (Rescue runtime)
        try:
            inv = InvariantEngine.check_source_accounting(100, 100, 0, 0)
            assert inv.passed
            report.checks.append(SelfTestItem("invariant_engine", True, status="PASS"))
            report.invariant_engine_status = "PASS"
        except Exception as e:
            report.checks.append(SelfTestItem("invariant_engine", False, status="FAIL", error=str(e)))
            report.invariant_engine_status = "FAIL"
            report.rescue_runtime_status = "FAIL"

        # 4. Check Codex binary availability (Environment)
        codex_bin = shutil.which("codex")
        if codex_bin:
            report.codex_binary_status = "PASS"
            report.checks.append(SelfTestItem("codex_binary", True, status="PASS", details={"path": codex_bin}))
        else:
            report.codex_binary_status = "NOT_FOUND"
            report.checks.append(SelfTestItem("codex_binary", False, status="NOT_FOUND"))

        # 5. Check CODEX_HOME accessibility (Environment)
        if home.exists() and os.access(str(home), os.R_OK):
            report.codex_home_status = "PASS"
            report.checks.append(SelfTestItem("codex_home", True, status="PASS", details={"path": str(home)}))
        else:
            report.codex_home_status = "NOT_FOUND"
            report.checks.append(SelfTestItem("codex_home", False, status="NOT_FOUND"))

        # 6. Check Codex State DB (Environment)
        state_db = home / "state_5.sqlite"
        if state_db.exists():
            fp = SchemaFingerprint.compute(state_db)
            if fp and "threads" in fp.tables:
                report.codex_state_status = "PASS"
                report.checks.append(SelfTestItem("codex_state_db", True, status="PASS", details={"tables": list(fp.tables.keys())}))
            else:
                report.codex_state_status = "CORRUPT"
                report.checks.append(SelfTestItem("codex_state_db", False, status="CORRUPT", error="Missing threads table or unreadable schema"))
        else:
            report.codex_state_status = "NOT_FOUND"
            report.checks.append(SelfTestItem("codex_state_db", False, status="NOT_FOUND"))

        # 7. Check App Server Reachability (Environment)
        if codex_bin:
            app_client = RealAppServerClient(home, timeout=2.0)
            if app_client.launch_stdio_server(binary_path=codex_bin):
                try:
                    init_res = app_client.initialize()
                    report.app_server_status = "PASS"
                    report.checks.append(SelfTestItem("app_server_handshake", True, status="PASS", details=init_res))
                except Exception as e:
                    report.app_server_status = "FAILED"
                    report.checks.append(SelfTestItem("app_server_handshake", False, status="FAILED", error=str(e)))
                finally:
                    app_client.shutdown()
            else:
                report.app_server_status = "NOT_AVAILABLE"
                report.checks.append(SelfTestItem("app_server_handshake", False, status="NOT_AVAILABLE"))
        else:
            report.app_server_status = "NOT_AVAILABLE"
            report.checks.append(SelfTestItem("app_server_handshake", False, status="NOT_AVAILABLE"))

        report.total_checks = len(report.checks)
        report.passed_checks = sum(1 for c in report.checks if c.passed)
        report.failed_checks = report.total_checks - report.passed_checks

        # Determine overall status model
        if report.rescue_runtime_status == "FAIL":
            report.overall_status = "FAIL"
        elif report.codex_state_status == "CORRUPT" or report.app_server_status == "FAILED":
            report.overall_status = "DEGRADED"
        elif report.codex_binary_status == "PASS" and (report.codex_state_status == "PASS" or report.app_server_status == "PASS"):
            report.overall_status = "PASS"
        else:
            # Clean Rescue runtime but empty/missing Codex state
            report.overall_status = "LIMITED"

        return report
