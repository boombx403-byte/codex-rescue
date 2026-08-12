from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)
    if os.name != "nt":
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def write_rescue(root: Path, handoff: dict[str, Any], brief: str, continuation: str) -> tuple[str, Path]:
    handoff_bytes = canonical_json(handoff)
    rescue_id = hashlib.sha256(handoff_bytes).hexdigest()[:24]
    rescue_dir = root / "rescues" / rescue_id
    atomic_write(rescue_dir / "handoff.v1.json", handoff_bytes + b"\n")
    atomic_write(rescue_dir / "RECOVERY_BRIEF.md", brief.encode("utf-8"))
    atomic_write(rescue_dir / "CONTINUATION_PROMPT.md", continuation.encode("utf-8"))
    return rescue_id, rescue_dir


def load_handoff(root: Path, rescue_id: str) -> dict[str, Any]:
    path = root / "rescues" / rescue_id / "handoff.v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    actual_id = hashlib.sha256(canonical_json(data)).hexdigest()[:24]
    if actual_id != rescue_id:
        raise ValueError(f"handoff hash mismatch: expected {rescue_id}, actual {actual_id}")
    return data

