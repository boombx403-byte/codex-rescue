"""Alpha8: stale writer-lock cleanup with evidence-gated removal.

Field evidence (#39823, #38792): after a crash or session switch Codex can
leave ``.lock`` files behind whose owner PID is dead. Rescue's own Alpha6
policy forbids automatic lock deletion; this module implements the
explicit, user-requested variant:

- Only locks whose recorded PID is verifiably dead (or unparseable after
  age threshold) are eligible.
- The lock file is copied to a timestamped backup before unlink, so the
  operation is reversible.
- Live-writer locks are never touched; the report fails closed instead.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .evidence import collect_session_evidence

# A lock without a parseable PID older than this is considered stale.
UNPARSEABLE_LOCK_STALE_SECONDS = 24 * 3600


@dataclass
class StaleLockReport:
    session_id: str
    session_path: str
    action_taken: str  # "none" | "removed" | "refused_live" | "nothing_stale"
    lock_path: str | None = None
    owner_pid: int | None = None
    owner_alive: bool | None = None
    lock_age_seconds: float | None = None
    backup_path: str | None = None
    reasons: list[str] = field(default_factory=list)
    write_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_path": self.session_path,
            "action_taken": self.action_taken,
            "lock_path": self.lock_path,
            "owner_pid": self.owner_pid,
            "owner_alive": self.owner_alive,
            "lock_age_seconds": self.lock_age_seconds,
            "backup_path": self.backup_path,
            "reasons": self.reasons,
            "write_performed": self.write_performed,
        }

    def render_text(self) -> str:
        lines = [
            f"Stale-lock cleanup: {self.session_id}",
            f"lock: {self.lock_path or '-'}",
        ]
        if self.owner_pid is not None:
            alive = (
                "alive"
                if self.owner_alive
                else ("dead" if self.owner_alive is False else "unknown")
            )
            lines.append(f"owner pid {self.owner_pid}: {alive}")
        if self.lock_age_seconds is not None:
            lines.append(f"age: {self.lock_age_seconds}s")
        lines.append(f"action: {self.action_taken}")
        if self.backup_path:
            lines.append(f"backup: {self.backup_path}")
        for r in self.reasons:
            lines.append(f"note: {r}")
        return "\n".join(lines)


def fix_stale_writer_lock(
    session_path: Path | str,
    codex_home: Path | str | None = None,
    *,
    remove: bool = False,
) -> StaleLockReport:
    ev = collect_session_evidence(session_path, codex_home=codex_home)
    report = StaleLockReport(
        session_id=ev.session_id,
        session_path=ev.session_path,
        action_taken="none",
    )

    if not ev.writer.lock_present or not ev.writer.lock_path:
        report.action_taken = "nothing_stale"
        report.reasons.append("no lock file present")
        return report

    lock = Path(ev.writer.lock_path)
    report.lock_path = str(lock)
    report.owner_pid = ev.writer.pid
    report.owner_alive = ev.writer.is_alive
    report.lock_age_seconds = ev.writer.lock_age_seconds

    if ev.writer.is_alive:
        report.action_taken = "refused_live"
        report.reasons.append(
            "owner process is alive; refusing to touch a live writer lock"
        )
        return report

    pid_known_dead = ev.writer.pid is not None and ev.writer.is_alive is False
    age = ev.writer.lock_age_seconds
    unparseable_but_old = (
        ev.writer.pid is None
        and isinstance(age, (int, float))
        and age >= UNPARSEABLE_LOCK_STALE_SECONDS
    )
    if not (pid_known_dead or unparseable_but_old):
        report.action_taken = "nothing_stale"
        report.reasons.append(
            "lock exists but staleness criteria not met "
            "(pid unknown and age below threshold)"
        )
        return report

    if pid_known_dead:
        report.reasons.append(f"recorded pid {ev.writer.pid} is not running")
    else:
        report.reasons.append(
            f"lock has no parseable pid and is {int(age or 0)}s old "
            f"(>= {UNPARSEABLE_LOCK_STALE_SECONDS}s)"
        )

    if not remove:
        report.reasons.append("dry-run: re-run with --fix to remove (backup kept)")
        return report

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = lock.with_name(lock.name + f".pre-fix-stale-{stamp}.bak")
    try:
        shutil.copy2(lock, backup)
    except OSError as exc:
        report.reasons.append(f"backup failed: {exc}")
        return report
    report.backup_path = str(backup)

    try:
        lock.unlink()
    except OSError as exc:
        report.reasons.append(f"unlink failed: {exc}")
        return report

    report.action_taken = "removed"
    report.write_performed = True
    return report
