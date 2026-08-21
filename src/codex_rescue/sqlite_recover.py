"""Alpha8: read-only SQLite recovery for corrupted Codex thread stores.

Field evidence (#39209 follow-ups, 'database disk image is malformed'):
``state_N.sqlite`` files can be truncated or internally corrupted by
crashes mid-write. Codex itself then refuses to start.

``sqlite_recover`` implements the sqbrite-style approach:

- Never writes to the source database.
- Attempts ``RECOVER INTO`` (SQLite >= 3.29 with recovery extension) when
  available; otherwise falls back to a page-level salvage: reads every
  readable row from every readable table via ``.recover``-equivalent
  semantics (best-effort SELECT sweep) and replays them into a fresh DB.
- The recovered copy is written next to the source as
  ``<name>.recovered.sqlite``; the original is left byte-identical and a
  SHA-256 of the damaged source is recorded for the report.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_TABLES = 64
MAX_ROWS_PER_TABLE = 500_000


@dataclass
class RecoveredTable:
    name: str
    rows_recovered: int = 0
    error: str | None = None


@dataclass
class SqliteRecoverReport:
    source_path: str
    source_sha256: str | None = None
    method: str = "none"  # "recover_into" | "select_sweep" | "none"
    recovered_path: str | None = None
    integrity_before: str = "unknown"  # quick_check result
    tables: list[RecoveredTable] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    write_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "method": self.method,
            "recovered_path": self.recovered_path,
            "integrity_before": self.integrity_before,
            "tables": [t.__dict__ for t in self.tables],
            "errors": self.errors,
            "write_performed": self.write_performed,
        }

    def render_text(self) -> str:
        lines = [
            f"SQLite recover: {self.source_path}",
            f"integrity before: {self.integrity_before}",
            f"method: {self.method}",
        ]
        if self.recovered_path:
            total = sum(t.rows_recovered for t in self.tables)
            lines.append(f"recovered: {self.recovered_path} ({total} rows)")
        for t in self.tables:
            status = f"{t.rows_recovered} rows" if t.error is None else f"ERROR: {t.error}"
            lines.append(f"  {t.name}: {status}")
        for e in self.errors:
            lines.append(f"ERROR: {e}")
        if not self.write_performed:
            lines.append("(dry-run)")
        return "\n".join(lines)


def _quick_check(db: Path) -> str:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return str(row[0]) if row else "unknown"
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return f"malformed ({exc})"


def _try_recover_into(source: Path, target: Path) -> bool:
    """Use SQLite's built-in RECOVER extension when present."""
    try:
        conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            available = conn.execute(
                "SELECT count(*) FROM pragma_compile_options "
                "WHERE compile_options LIKE '%RECOVERY%'"
            ).fetchone()
            if not available or not available[0]:
                return False
            conn.execute(
                f"RECOVER INTO ?",
                (str(target),),
            )
            return True
        finally:
            conn.close()
    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        return False


def _select_sweep(source: Path, target: Path, report: SqliteRecoverReport) -> None:
    """Best-effort row-by-row salvage into a fresh database."""
    out = sqlite3.connect(str(target))
    src: sqlite3.Connection | None = None
    try:
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            tables = [
                str(r[0])
                for r in src.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
        except sqlite3.DatabaseError as exc:
            report.errors.append(f"cannot enumerate schema: {exc}")
            return

        for table in tables[:MAX_TABLES]:
            entry = RecoveredTable(name=table)
            try:
                cols = [
                    str(r[1])
                    for r in src.execute(f'PRAGMA table_info("{table}")').fetchall()
                ]
                if not cols:
                    entry.error = "no columns readable"
                    report.tables.append(entry)
                    continue
                col_list = ", ".join(f'"{c}"' for c in cols)
                out.execute(
                    f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(chr(34) + c + chr(34) + " TEXT" for c in cols)})'
                )
                rows = src.execute(
                    f"SELECT {col_list} FROM \"{table}\" LIMIT {MAX_ROWS_PER_TABLE}"
                )
                count = 0
                while True:
                    batch = rows.fetchmany(1000)
                    if not batch:
                        break
                    placeholders = ", ".join("?" for _ in cols)
                    out.executemany(
                        f'INSERT OR IGNORE INTO "{table}" VALUES ({placeholders})',
                        [tuple(str(v) if v is not None else None for v in row) for row in batch],
                    )
                    count += len(batch)
                out.commit()
                entry.rows_recovered = count
            except sqlite3.DatabaseError as exc:
                entry.error = str(exc)
            report.tables.append(entry)
    finally:
        if src is not None:
            src.close()
        out.close()


def recover_sqlite(
    db_path: str | Path,
    *,
    write: bool = False,
    recovered_path: str | Path | None = None,
) -> SqliteRecoverReport:
    source = Path(db_path).resolve()
    report = SqliteRecoverReport(source_path=str(source))
    if not source.exists():
        report.errors.append("database file does not exist")
        return report

    digest = hashlib.sha256()
    with source.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    report.source_sha256 = digest.hexdigest()
    report.integrity_before = _quick_check(source)

    if report.integrity_before == "ok":
        report.errors.append("database passes quick_check; nothing to recover")
        return report

    dest = (
        Path(recovered_path).resolve()
        if recovered_path
        else source.with_name(source.name + ".recovered.sqlite")
    )

    if not write:
        report.method = "none"
        report.errors.append(
            f"dry-run: would write recovered copy to {dest.name}"
        )
        return report

    # Method 1: native RECOVER INTO.
    if _try_recover_into(source, dest):
        report.method = "recover_into"
        report.recovered_path = str(dest)
        report.write_performed = True
        verify = _quick_check(dest)
        if verify != "ok":
            report.errors.append(f"recovered copy still fails quick_check: {verify}")
        return report

    # Method 2: best-effort SELECT sweep.
    try:
        dest.unlink()
    except OSError:
        pass
    _select_sweep(source, dest, report)
    report.method = "select_sweep"
    report.recovered_path = str(dest)
    report.write_performed = True
    return report
