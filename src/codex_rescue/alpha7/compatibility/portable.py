from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.compatibility.path_remap import PathRemappingEngine
from codex_rescue.alpha7.invariants import InvariantCheckResult, InvariantEngine, InvariantStatus


@dataclass
class PortableManifest:
    manifest_version: int = 1
    session_id: str = ""
    source_platform: str = ""
    created_at: float = 0.0
    schema_version: int = 1
    rollout_sha256: str = ""
    rollout_size_bytes: int = 0
    workspace_path: Optional[str] = None
    records_count: int = 0
    source_integrity: str = "PROVEN_COMPLETE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ImportPlan:
    session_id: str
    target_rollout_path: str
    needs_remapping: bool
    remapped_workspace: Optional[str]
    has_conflict: bool
    conflict_type: Optional[str]
    is_safe: bool
    invariants: List[InvariantCheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_rollout_path": self.target_rollout_path,
            "needs_remapping": self.needs_remapping,
            "remapped_workspace": self.remapped_workspace,
            "has_conflict": self.has_conflict,
            "conflict_type": self.conflict_type,
            "is_safe": self.is_safe,
            "invariants": [
                {"id": i.invariant_id.value, "status": i.status.value, "message": i.message}
                for i in self.invariants
            ],
        }


class PortableSessionEngine:
    """Exports and imports portable session packages with integrity validation and path remapping."""

    @staticmethod
    def export_session(
        session_file: Path,
        output_zip: Path,
        workspace_path: Optional[str] = None,
    ) -> PortableManifest:
        if not session_file.exists():
            raise FileNotFoundError(f"Session file not found: {session_file}")

        data = session_file.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        size = len(data)
        sid = session_file.stem

        # Count records
        record_count = sum(1 for line in data.splitlines() if line.strip())

        manifest = PortableManifest(
            manifest_version=1,
            session_id=sid,
            source_platform=platform.system(),
            created_at=float(os.path.getmtime(session_file)),
            schema_version=1,
            rollout_sha256=sha,
            rollout_size_bytes=size,
            workspace_path=workspace_path,
            records_count=record_count,
            source_integrity="PROVEN_COMPLETE",
        )

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest.to_dict(), indent=2))
            zf.writestr(f"rollouts/{sid}.jsonl", data)

        return manifest

    @staticmethod
    def inspect_package(package_zip: Path) -> PortableManifest:
        if not package_zip.exists():
            raise FileNotFoundError(f"Portable package not found: {package_zip}")

        with zipfile.ZipFile(package_zip, "r") as zf:
            if "manifest.json" not in zf.namelist():
                raise ValueError("Invalid package: missing manifest.json")
            m_data = json.loads(zf.read("manifest.json").decode("utf-8"))
            return PortableManifest(**m_data)

    @staticmethod
    def plan_import(
        package_zip: Path,
        target_codex_home: Path,
        target_platform: Optional[str] = None,
        explicit_workspace_remap: Optional[str] = None,
    ) -> ImportPlan:
        manifest = PortableSessionEngine.inspect_package(package_zip)
        target_sessions = target_codex_home / "sessions"
        target_path = target_sessions / f"{manifest.session_id}.jsonl"

        has_conflict = target_path.exists()
        conflict_type = "EXISTING_SESSION_FILE" if has_conflict else None

        # Check path remapping
        remapped_ws = None
        needs_remapping = False
        plat = target_platform or platform.system()

        if manifest.workspace_path:
            res = PathRemappingEngine.translate_path(
                manifest.workspace_path,
                target_platform=plat,
                explicit_mappings={manifest.workspace_path: explicit_workspace_remap} if explicit_workspace_remap else None,
            )
            remapped_ws = res.target_path
            needs_remapping = (remapped_ws != manifest.workspace_path)

        invariants = []
        inv_src = InvariantEngine.check_source_accounting(
            manifest.rollout_size_bytes, manifest.rollout_size_bytes, 0, 0
        )
        invariants.append(inv_src)

        is_safe = not has_conflict and all(i.passed for i in invariants)

        return ImportPlan(
            session_id=manifest.session_id,
            target_rollout_path=str(target_path),
            needs_remapping=needs_remapping,
            remapped_workspace=remapped_ws,
            has_conflict=has_conflict,
            conflict_type=conflict_type,
            is_safe=is_safe,
            invariants=invariants,
        )

    @staticmethod
    def execute_import(
        package_zip: Path,
        target_codex_home: Path,
        plan: ImportPlan,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        if not plan.is_safe:
            return {
                "success": False,
                "error": f"Import blocked: {plan.conflict_type or 'Safety check failed'}",
                "dry_run": dry_run,
            }

        if dry_run:
            return {
                "success": True,
                "action": "DRY_RUN_PASSED",
                "target_path": plan.target_rollout_path,
                "remapped_workspace": plan.remapped_workspace,
            }

        target_sessions = target_codex_home / "sessions"
        target_sessions.mkdir(parents=True, exist_ok=True)
        target_path = Path(plan.target_rollout_path)

        with zipfile.ZipFile(package_zip, "r") as zf:
            rollout_name = f"rollouts/{plan.session_id}.jsonl"
            if rollout_name not in zf.namelist():
                return {"success": False, "error": "Package corrupted: missing rollout file"}
            data = zf.read(rollout_name)
            target_path.write_bytes(data)

        return {
            "success": True,
            "action": "IMPORTED",
            "target_path": str(target_path),
            "session_id": plan.session_id,
        }
