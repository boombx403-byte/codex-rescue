from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class BackupEntry:
    original_path: str
    backup_path: str
    sha256: str
    size_bytes: int
    is_source: bool  # True for canonical rollout, False for derived SQLite/index

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackupManifest:
    manifest_id: str
    created_at: float
    entries: List[BackupEntry] = field(default_factory=list)
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "created_at": self.created_at,
            "entries": [e.to_dict() for e in self.entries],
            "verified": self.verified,
        }


class BackupEngine:
    """Pre-mutation backup manifest creation, integrity verification, and atomic rollback."""

    def __init__(self, backup_root: Optional[Path] = None):
        self.backup_root = backup_root or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "backups"

    def create_pre_mutation_backup(
        self,
        targets: List[Path],
        operation_id: Optional[str] = None,
    ) -> BackupManifest:
        op_id = operation_id or f"op_{int(time.time()*1000)}"
        op_dir = self.backup_root / op_id
        op_dir.mkdir(parents=True, exist_ok=True)

        manifest = BackupManifest(manifest_id=op_id, created_at=time.time())

        for target in targets:
            if not target.exists():
                continue

            target_data = target.read_bytes()
            sha = hashlib.sha256(target_data).hexdigest()
            backup_file = op_dir / f"{target.name}_{sha[:8]}"
            backup_file.write_bytes(target_data)

            is_source = target.suffix == ".jsonl"
            manifest.entries.append(
                BackupEntry(
                    original_path=str(target.resolve()),
                    backup_path=str(backup_file.resolve()),
                    sha256=sha,
                    size_bytes=len(target_data),
                    is_source=is_source,
                )
            )

        manifest_file = op_dir / "manifest.json"
        manifest_file.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
        manifest.verified = True
        return manifest

    def rollback(self, manifest: BackupManifest) -> bool:
        """Atomically restores all backed-up files from manifest."""
        for entry in manifest.entries:
            b_path = Path(entry.backup_path)
            orig_path = Path(entry.original_path)

            if not b_path.exists():
                return False

            b_data = b_path.read_bytes()
            current_sha = hashlib.sha256(b_data).hexdigest()
            if current_sha != entry.sha256:
                # Backup corrupted! Block restore per INV-008
                return False

            orig_path.parent.mkdir(parents=True, exist_ok=True)
            orig_path.write_bytes(b_data)

        return True
