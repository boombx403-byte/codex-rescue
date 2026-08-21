"""Alpha8: safe derived-state reconciliation with timestamped backups.

Reconciles diverged thread-store metadata against on-disk rollout reality:

- ``\\\\?\\C:\\...`` extended-length rollout_path / cwd forms rewritten to the
  plain display path (the exact string the Codex UI matches on).
- Persisted WSL ``/mnt/<drive>/...`` cwd values translated to the Windows-native
  ``<Drive>:\\...`` form when the runtime family disagrees with the stored one.

Safety model (mirrors the read-only-first project philosophy):

- Dry-run by default; mutation requires an explicit ``--write``.
- Every mutated store is copied to a timestamped backup before the first write.
- SQLite updates run inside a single transaction per database and are rolled
  back on any error.
- JSONL session files are never modified by this module.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .alpha5 import _connect_read_only, _quote_identifier
from .windows_paths import (
    compare_windows_paths,
    has_windows_namespace_divergence,
    normalize_windows_extended_path,
)

MAX_DB_CANDIDATES = 32
MAX_ROWS_PER_DB = 100_000

_WSL_MNT_RE = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")


@dataclass
class ReconcileRow:
    db_path: str
    table: str
    id_column: str | None
    row_id: str | None
    column: str
    old_value: str
    new_value: str
    kind: str  # "extended_path" | "wsl_cwd"

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_path": self.db_path,
            "table": self.table,
            "row_id": self.row_id,
            "column": self.column,
            "kind": self.kind,
            "old": self.old_value,
            "new": self.new_value,
        }


@dataclass
class ReconcileReport:
    codex_home: str
    write_performed: bool = False
    backups: list[dict[str, str]] = field(default_factory=list)
    changes: list[ReconcileRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scanned_dbs: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "codex_home": self.codex_home,
            "write_performed": self.write_performed,
            "scanned_dbs": self.scanned_dbs,
            "backups": self.backups,
            "changes": [c.to_dict() for c in self.changes],
            "errors": self.errors,
        }

    def render_text(self) -> str:
        mode = "WRITE" if self.write_performed else "DRY-RUN"
        lines = [
            f"Reconcile ({mode}) — {self.codex_home}",
            f"Databases scanned: {self.scanned_dbs}",
            f"Planned changes:   {len(self.changes)}",
        ]
        for change in self.changes:
            lines.append(
                f"  * [{change.kind}] {Path(change.db_path).name}."
                f"{change.table}.{change.column}"
                f" (id={change.row_id or '?'})\n"
                f"      old: {change.old_value}\n"
                f"      new: {change.new_value}"
            )
        for backup in self.backups:
            lines.append(f"  backup: {backup['source']} -> {backup['backup']}")
        for err in self.errors:
            lines.append(f"  ERROR: {err}")
        return "\n".join(lines)


def _translate_wsl_to_windows(value: str) -> str | None:
    """Return the Windows-native equivalent of a persisted WSL /mnt/<drive> path."""
    match = _WSL_MNT_RE.match(value.replace("\\", "/"))
    if not match:
        return None
    drive = match.group(1).upper()
    suffix = match.group(2) or ""
    windows = f"{drive}:\\{suffix.replace('/', chr(92))}" if suffix else f"{drive}:\\"
    return windows


def _candidate_dbs(root: Path) -> list[Path]:
    found: set[Path] = set()
    for pattern in ("*.sqlite", "*.sqlite3", "*.db"):
        try:
            for path in root.glob(pattern):
                if path.is_file():
                    found.add(path.resolve())
        except OSError:
            continue
    return sorted(found, key=lambda p: str(p))[:MAX_DB_CANDIDATES]


def _column(columns: set[str], names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in columns), None)


def _plan_column_fixes(
    connection: sqlite3.Connection,
    db_path: Path,
    report: ReconcileReport,
    *,
    fix_extended_paths: bool,
    fix_wsl_cwd: bool,
) -> None:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")
    }
    if "threads" not in tables:
        return
    columns = {str(row[1]) for row in connection.execute('PRAGMA table_info("threads")')}
    id_column = _column(columns, ("id", "thread_id", "session_id"))
    path_column = _column(columns, ("rollout_path", "session_path", "path"))
    cwd_column = _column(columns, ("cwd", "workspace", "worktree"))
    if path_column is None and cwd_column is None:
        return

    selected = [name for name in (id_column, path_column, cwd_column) if name]
    if not selected:
        return
    expressions = ", ".join(_quote_identifier(name) for name in selected)
    sql = f'SELECT {expressions} FROM "threads" LIMIT {MAX_ROWS_PER_DB}'
    for row in connection.execute(sql):
        row_values = list(row)
        row_id = str(row_values.pop(0)) if id_column else None
        for offset, column_name in enumerate([c for c in (path_column, cwd_column) if c]):
            raw = row_values[offset] if offset < len(row_values) else None
            value = str(raw).strip() if raw not in (None, "") else None
            if not value:
                continue
            new_value: str | None = None
            kind: str | None = None
            if fix_extended_paths and column_name == path_column:
                # The repair target is the plain display form: the exact string
                # the Codex UI matches on. Only rewrite when the stored value
                # carries the \\?\ namespace prefix AND the stripped plain form
                # points to the same file (EQUIVALENT), never when the two
                # spellings could be different files.
                if value.startswith("\\\\?\\") or value.startswith("//?/"):
                    candidate = normalize_windows_extended_path(value)
                    candidate = candidate.replace("/", "\\")
                    comparison = compare_windows_paths(candidate, value)
                    if comparison.relation == "EQUIVALENT" and not candidate.startswith("\\\\?\\"):
                        new_value = candidate
                        kind = "extended_path"
            elif (
                fix_wsl_cwd
                and column_name == cwd_column
                and _WSL_MNT_RE.match(value.replace("\\", "/"))
            ):
                translated = _translate_wsl_to_windows(value)
                if translated:
                    new_value = translated
                    kind = "wsl_cwd"
            if new_value and kind:
                report.changes.append(
                    ReconcileRow(
                        db_path=str(db_path),
                        table="threads",
                        id_column=id_column,
                        row_id=row_id,
                        column=column_name,
                        old_value=value,
                        new_value=new_value,
                        kind=kind,
                    )
                )


def _apply_changes(
    connection: sqlite3.Connection,
    changes: list[ReconcileRow],
) -> int:
    applied = 0
    try:
        for change in changes:
            if change.id_column is None or change.row_id is None:
                continue
            sql = (
                f'UPDATE "threads" SET {_quote_identifier(change.column)}=? '
                f"WHERE {_quote_identifier(change.id_column)}=?"
            )
            cursor = connection.execute(sql, (change.new_value, change.row_id))
            applied += max(cursor.rowcount, 0)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return applied


def reconcile_codex_home(
    codex_home: str | Path | None = None,
    *,
    write: bool = False,
    fix_extended_paths: bool = True,
    fix_wsl_cwd: bool = True,
) -> ReconcileReport:
    home = Path(codex_home).resolve() if codex_home else Path.home() / ".codex"
    report = ReconcileReport(codex_home=str(home), write_performed=False)
    if not home.exists():
        report.errors.append(f"codex home does not exist: {home}")
        return report

    dbs = _candidate_dbs(home)
    report.scanned_dbs = len(dbs)

    # Phase 1: plan all changes read-only.
    planned_by_db: dict[Path, list[ReconcileRow]] = {}
    for db_path in dbs:
        connection: sqlite3.Connection | None = None
        try:
            connection = _connect_read_only(db_path)
            _plan_column_fixes(
                connection,
                db_path,
                report,
                fix_extended_paths=fix_extended_paths,
                fix_wsl_cwd=fix_wsl_cwd,
            )
        except (sqlite3.DatabaseError, OSError) as exc:
            report.errors.append(f"{db_path.name}: read failed: {exc}")
        finally:
            if connection is not None:
                connection.close()

    if not write or not report.changes:
        return report

    # Phase 2: backup then apply, per database.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for db_path, _ in planned_by_db.items():
        pass  # placeholder to keep mapping shape stable if extended later

    changes_by_db: dict[str, list[ReconcileRow]] = {}
    for change in report.changes:
        changes_by_db.setdefault(change.db_path, []).append(change)

    for db_str, db_changes in changes_by_db.items():
        db_path = Path(db_str)
        backup_path = db_path.with_name(db_path.name + f".pre-reconcile-{stamp}.bak")
        try:
            shutil.copy2(db_path, backup_path)
        except OSError as exc:
            report.errors.append(f"{db_path.name}: backup failed: {exc}")
            continue
        report.backups.append({"source": str(db_path), "backup": str(backup_path)})

        write_conn: sqlite3.Connection | None = None
        try:
            write_conn = sqlite3.connect(str(db_path))
            applied = _apply_changes(write_conn, db_changes)
            if applied != len(db_changes):
                report.errors.append(
                    f"{db_path.name}: applied {applied}/{len(db_changes)} updates"
                )
        except (sqlite3.DatabaseError, OSError) as exc:
            report.errors.append(f"{db_path.name}: write failed (rolled back): {exc}")
        finally:
            if write_conn is not None:
                write_conn.close()

    report.write_performed = True
    return report
