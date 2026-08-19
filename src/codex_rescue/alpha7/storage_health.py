from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.thread_identity import resolve_thread_identity


@dataclass
class LargeRolloutInfo:
    filename: str
    bytes: int
    thread_id: Optional[str] = None
    rollout_id: Optional[str] = None
    is_archived: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StorageHealthLimits:
    max_files: int = 50_000
    max_bytes: int = 50 * 1024 * 1024 * 1024  # 50GB
    large_file_threshold_bytes: int = 50 * 1024 * 1024  # 50MB
    oversized_record_threshold_bytes: int = 16 * 1024 * 1024  # 16MB
    timeout_sec: float = 10.0


@dataclass
class StorageHealthReport:
    codex_home_bytes: Optional[int] = None
    codex_home_bytes_status: str = "MEASURED"  # MEASURED, ESTIMATED, UNKNOWN
    sessions_count: int = 0
    archived_sessions_count: int = 0
    rollout_bytes_total: int = 0
    large_rollouts: List[LargeRolloutInfo] = field(default_factory=list)
    oversized_record_candidates: List[Dict[str, Any]] = field(default_factory=list)
    duplicate_physical_sources: List[Dict[str, Any]] = field(default_factory=list)
    unreadable_regions: List[Dict[str, Any]] = field(default_factory=list)
    state_db_sizes: Dict[str, int] = field(default_factory=dict)
    scan_truncated: bool = False
    duration_sec: float = 0.0
    limits: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "codex_home_bytes": self.codex_home_bytes,
            "codex_home_bytes_status": self.codex_home_bytes_status,
            "sessions_count": self.sessions_count,
            "archived_sessions_count": self.archived_sessions_count,
            "rollout_bytes_total": self.rollout_bytes_total,
            "large_rollouts": [r.to_dict() for r in self.large_rollouts],
            "oversized_record_candidates": self.oversized_record_candidates,
            "duplicate_physical_sources": self.duplicate_physical_sources,
            "unreadable_regions": self.unreadable_regions,
            "state_db_sizes": self.state_db_sizes,
            "scan_truncated": self.scan_truncated,
            "duration_sec": self.duration_sec,
            "limits": self.limits,
        }


class StorageHealthEngine:
    """Bounded, streaming product diagnostic engine for CODEX_HOME storage and scalability.

    Strictly read-only: does not perform deletions, modifications, or cleanups.
    Does not materialize large JSONL files entirely in memory.
    """

    @staticmethod
    def scan_codex_home(
        codex_home: Path,
        limits: Optional[StorageHealthLimits] = None,
    ) -> StorageHealthReport:
        lim = limits or StorageHealthLimits()
        start_t = time.time()

        report = StorageHealthReport(
            limits={
                "max_files": lim.max_files,
                "max_bytes": lim.max_bytes,
                "large_file_threshold_bytes": lim.large_file_threshold_bytes,
                "timeout_sec": lim.timeout_sec,
            }
        )

        if not codex_home.exists() or not codex_home.is_dir():
            report.codex_home_bytes_status = "UNKNOWN"
            report.duration_sec = round(time.time() - start_t, 3)
            return report

        total_home_bytes = 0
        total_files_scanned = 0
        is_truncated = False
        seen_filenames: Dict[str, List[str]] = {}

        # 1. State databases scan (state_5.sqlite, goals_1.sqlite, logs_2.sqlite, etc.)
        for db_file in codex_home.glob("*.sqlite*"):
            try:
                st = db_file.stat()
                report.state_db_sizes[db_file.name] = st.st_size
                total_home_bytes += st.st_size
            except OSError:
                report.unreadable_regions.append({"path": str(db_file), "error": "Unreadable state DB"})

        # 2. Sessions and archived sessions scanning (bounded streaming)
        scan_dirs = [
            (codex_home / "sessions", False),
            (codex_home / "archived_sessions", True),
        ]

        for sdir, is_archived in scan_dirs:
            if not sdir.exists():
                continue

            try:
                for root, _, files in os.walk(str(sdir)):
                    for fname in files:
                        total_files_scanned += 1
                        if total_files_scanned > lim.max_files or (time.time() - start_t) > lim.timeout_sec:
                            is_truncated = True
                            break

                        fpath = Path(root) / fname
                        try:
                            st = fpath.stat()
                            fsize = st.st_size
                            total_home_bytes += fsize

                            if fname.endswith(".jsonl"):
                                report.rollout_bytes_total += fsize
                                if is_archived:
                                    report.archived_sessions_count += 1
                                else:
                                    report.sessions_count += 1

                                # Track physical duplicates
                                if fname in seen_filenames:
                                    seen_filenames[fname].append(str(fpath))
                                else:
                                    seen_filenames[fname] = [str(fpath)]

                                # Resolve identity without stem fallback
                                ident = resolve_thread_identity(fpath)

                                # Check large rollout
                                if fsize >= lim.large_file_threshold_bytes:
                                    report.large_rollouts.append(
                                        LargeRolloutInfo(
                                            filename=fname,
                                            bytes=fsize,
                                            thread_id=ident.thread_id,
                                            rollout_id=ident.filename_rollout_id,
                                            is_archived=is_archived,
                                        )
                                    )

                                # Quick bounded check for oversized records on large files
                                if fsize >= lim.oversized_record_threshold_bytes:
                                    # Sample first 64KB without materializing whole file
                                    try:
                                        with open(fpath, "rb") as fh:
                                            sample = fh.read(65536)
                                            if b"\n" not in sample and len(sample) == 65536:
                                                report.oversized_record_candidates.append(
                                                    {
                                                        "filename": fname,
                                                        "bytes": fsize,
                                                        "thread_id": ident.thread_id,
                                                        "estimated_single_record": True,
                                                    }
                                                )
                                    except Exception:
                                        pass
                        except OSError as e:
                            report.unreadable_regions.append({"path": str(fpath), "error": str(e)})

                    if is_truncated:
                        break
            except Exception as e:
                report.unreadable_regions.append({"path": str(sdir), "error": str(e)})

        # Record duplicates
        for fname, paths in seen_filenames.items():
            if len(paths) > 1:
                report.duplicate_physical_sources.append({"filename": fname, "paths": paths})

        report.codex_home_bytes = total_home_bytes
        report.codex_home_bytes_status = "ESTIMATED" if is_truncated else "MEASURED"
        report.scan_truncated = is_truncated
        report.duration_sec = round(time.time() - start_t, 3)

        return report
