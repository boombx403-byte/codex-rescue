from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import write_rescue
from .gitstate import GitStateError, compare_git_state, inspect_git_state
from .journal import read_entries
from .reconstruct import build_handoff, continuation_prompt, recovery_brief


@dataclass(frozen=True)
class SalvageResult:
    rescue_id: str
    rescue_dir: str
    handoff_path: str
    continuation_command: str
    source_sha256_before: str
    source_sha256_after: str
    original_untouched: bool

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def salvage_session(
    session_path: str | Path,
    parsed: Any,
    doctor_status: str,
    findings: list[str],
    rescue_root: str | Path,
    fork: bool,
) -> SalvageResult:
    if not fork:
        raise ValueError("PoC salvage requires --fork; in-place recovery is forbidden")
    source = Path(session_path).resolve()
    source_before = file_sha256(source)
    metadata = getattr(parsed, "session_metadata", {}) or {}
    cwd = metadata.get("cwd") if isinstance(metadata, dict) else None
    git_state = None
    if cwd:
        try:
            git_state = inspect_git_state(cwd)
        except GitStateError:
            git_state = None
    source_id = metadata.get("session_id") if isinstance(metadata, dict) else source.stem
    journal_entries, _partial = read_entries(rescue_root, source_id or source.stem)
    if git_state and journal_entries:
        latest = journal_entries[-1]
        expected = {
            "worktree": latest.get("worktree"),
            "head_sha": latest.get("head_sha"),
            "diff_hash": latest.get("diff_hash"),
            "changed_files": latest.get("changed_files"),
        }
        conflicts = compare_git_state(expected, git_state)
        if conflicts:
            doctor_status = "REPO_STATE_DIVERGED"
            findings = ["REPO_STATE_DIVERGED", *[item for item in findings if item != "REPO_STATE_DIVERGED"]]
    handoff = build_handoff(str(source), parsed, git_state, journal_entries, doctor_status, findings)
    provisional_brief = recovery_brief(handoff)
    provisional_prompt = continuation_prompt(Path("handoff.v1.json"))
    rescue_id, rescue_dir = write_rescue(Path(rescue_root), handoff, provisional_brief, provisional_prompt)
    handoff_path = rescue_dir / "handoff.v1.json"
    # Regenerate the bounded prompt with its exact absolute handoff path. This file is
    # outside the content-addressed handoff and does not change the rescue id.
    from .artifacts import atomic_write

    atomic_write(rescue_dir / "CONTINUATION_PROMPT.md", continuation_prompt(handoff_path).encode("utf-8"))
    source_after = file_sha256(source)
    command = f'codex -C "{handoff["session"].get("cwd") or source.parent}" "Continue from {handoff_path}"'
    return SalvageResult(
        rescue_id=rescue_id,
        rescue_dir=str(rescue_dir),
        handoff_path=str(handoff_path),
        continuation_command=command,
        source_sha256_before=source_before,
        source_sha256_after=source_after,
        original_untouched=source_before == source_after,
    )
