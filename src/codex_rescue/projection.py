"""Read-only parity check between a rollout and its thread-history projection.

The projection database (``thread_history_*.sqlite``) tracks where upstream
ingestion stopped reading the rollout JSONL: a byte offset plus the next
expected ordinal.  A cursor past EOF, inside a line, or pointing at a record
whose ordinal disagrees with the projection means the projection is wedged and
UI surfaces can show a stale subset of the session.  Everything here is
strictly read-only and evidence-bound: no payload text is ever copied into the
report.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .discovery import codex_home_path

CHUNK = 4 * 1024 * 1024
META_HEAD_BYTES = 4096
STATE_COLUMNS = ("thread_id", "next_rollout_byte_offset", "next_rollout_ordinal")


def _report(status: str, thread_id: str | None, db: str | None, details: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": status, "thread_id": thread_id, "db": db, "details": details}


def _find_projection_db(codex_home: str | Path | None) -> Path | None:
    root = codex_home_path(codex_home)
    try:
        candidates = sorted(root.glob("thread_history_*.sqlite"))
    except OSError:
        return None
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _open_ro(db_path: Path) -> sqlite3.Connection:
    # mode=ro refuses writes at the SQLite level; the rollout and databases
    # must remain byte-identical after analysis.  as_posix keeps Windows
    # drive letters legal inside the URI form.
    return sqlite3.connect("file:%s?mode=ro" % db_path.as_posix(), uri=True)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    quoted = table.replace('"', '""')
    rows = conn.execute('PRAGMA table_info("%s")' % quoted).fetchall()
    return {str(row[1]) for row in rows if row[1] is not None}


def _meta_candidates(rollout: Path) -> list[str]:
    try:
        with rollout.open("rb") as stream:
            head = stream.read(META_HEAD_BYTES)
    except OSError:
        return []
    first = head.split(b"\n", 1)[0].rstrip(b"\r")
    if not first:
        return []
    try:
        record = json.loads(first.decode("utf-8", "replace"))
    except (UnicodeDecodeError, ValueError):
        return []
    if not isinstance(record, dict) or record.get("type") != "session_meta":
        return []
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    candidates: list[str] = []
    for key in ("session_id", "id", "thread_id"):
        value = payload.get(key)
        if isinstance(value, str) and value and value not in candidates:
            candidates.append(value)
    return candidates


def _row_matches(row: tuple[Any, ...], rollout: Path) -> bool:
    resolved = str(rollout.as_posix())
    base = rollout.name
    for value in row:
        if not isinstance(value, str):
            continue
        normalized = value.replace("\\", "/")
        if value == resolved or normalized == resolved or normalized.endswith("/" + resolved):
            return True
        if value == base or normalized.endswith("/" + base) or normalized.endswith("\\" + base):
            return True
    return False


def _first_dict_line(data: bytes) -> dict[str, Any] | None:
    for raw in data.splitlines():
        if not raw:
            continue
        try:
            record = json.loads(raw.decode("utf-8", "replace"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(record, dict):
            return record
    return None


def _ordinal_replayed_before(rollout: Path, offset: int, ordinal: int) -> bool:
    start = max(0, offset - CHUNK)
    try:
        with rollout.open("rb") as stream:
            stream.seek(start)
            data = stream.read(offset - start)
    except OSError:
        return False
    if start > 0:
        fragments = data.split(b"\n", 1)
        data = fragments[1] if len(fragments) == 2 else b""
    for raw in data.splitlines():
        if not raw:
            continue
        try:
            record = json.loads(raw.decode("utf-8", "replace"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(record, dict) and record.get("ordinal") == ordinal:
            return True
    return False


def _state_db_thread_id(db_dir: Path, rollout: Path, matched: list[bool]) -> Any:
    """Return the id of the threads row whose rollout_path matches, if any."""

    try:
        conn = _open_ro(db_dir / "state_5.sqlite")
    except sqlite3.Error:
        return None
    try:
        if "threads" not in _table_names(conn):
            return None
        for row in conn.execute("SELECT * FROM threads").fetchall():
            if _row_matches(row, rollout):
                matched.append(True)
                return row[0] if row else None
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    return None


def _projected_row(conn: sqlite3.Connection, thread_key: Any) -> tuple[Any, ...] | None:
    return conn.execute(
        "SELECT thread_id, next_rollout_byte_offset, next_rollout_ordinal "
        "FROM thread_history_projection_state WHERE thread_id = ?",
        (thread_key,),
    ).fetchone()


def _candidate_rows(conn: sqlite3.Connection, candidates: list[str]) -> list[tuple[Any, ...]]:
    placeholders = ",".join("?" for _ in candidates)
    return conn.execute(
        "SELECT thread_id, next_rollout_byte_offset, next_rollout_ordinal "
        "FROM thread_history_projection_state WHERE thread_id IN (%s) LIMIT 5" % placeholders,
        candidates,
    ).fetchall()


def _resolve_row(db_path: Path, rollout: Path, matched: list[bool]) -> tuple[tuple[Any, ...] | None, str | None]:
    """Locate the projection_state row for the rollout.

    sqlite3.Error deliberately propagates: the caller owns the fail-closed
    UNKNOWN/NOT_APPLICABLE split based on whether a thread row matched first.
    """

    conn = _open_ro(db_path)
    try:
        if "thread_history_projection_state" not in _table_names(conn):
            return None, None
        if not set(STATE_COLUMNS).issubset(_table_columns(conn, "thread_history_projection_state")):
            return None, None
        state_id = _state_db_thread_id(db_path.parent, rollout, matched)
        if state_id is not None:
            row = _projected_row(conn, state_id)
            if row is not None:
                return row, str(row[0])
            return None, None
        for row in _candidate_rows(conn, _meta_candidates(rollout)):
            return row, str(row[0])
        return None, None
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def inspect_projection_parity(rollout_path: str | Path, codex_home: str | Path | None = None) -> dict[str, Any]:
    """Compare the projection cursor against the canonical rollout extent.

    Returns a bounded report; never raises.  ``details`` entries contain only
    integers, flags, and short evidence labels -- never payload text.
    """

    thread_id: str | None = None
    db: str | None = None
    details: list[dict[str, Any]] = []
    matched: list[bool] = []
    try:
        rollout = Path(rollout_path).resolve()
        db_path = _find_projection_db(codex_home)
        if db_path is None:
            return _report("NOT_APPLICABLE", None, None, details)
        db = str(db_path)
        try:
            size = int(rollout.stat().st_size)
        except OSError:
            return _report("UNKNOWN", None, db, details + [{"evidence": "rollout_stat_failed"}])
        try:
            row, thread_id = _resolve_row(db_path, rollout, matched)
        except sqlite3.Error:
            status = "UNKNOWN" if matched else "NOT_APPLICABLE"
            return _report(status, thread_id, db, details + [{"evidence": "sqlite_analysis_failed"}])
        if row is None:
            return _report("NOT_APPLICABLE", thread_id, db, details + [{"evidence": "projection_row_not_matched"}])
        offset = row[1]
        next_ordinal = row[2]
        if isinstance(offset, bool) or not isinstance(offset, int):
            return _report("UNKNOWN", thread_id, db, details + [{"evidence": "projection_offset_not_integer"}])
        if offset < 0:
            return _report("WEDGED", thread_id, db, details + [{"evidence": "projection_cursor_negative", "byte_offset": offset}])
        if offset > size:
            return _report(
                "WEDGED",
                thread_id,
                db,
                details + [{"evidence": "projection_cursor_beyond_canonical_extent", "byte_offset": offset, "size": size}],
            )
        if offset == size:
            return _report(
                "MATCH",
                thread_id,
                db,
                details + [{"evidence": "caught_up_at_eof", "byte_offset": offset, "size": size}],
            )
        try:
            with rollout.open("rb") as stream:
                if offset > 0:
                    stream.seek(offset - 1)
                    if stream.read(1) != b"\n":
                        return _report(
                            "WEDGED",
                            thread_id,
                            db,
                            details + [{"evidence": "cursor_midline", "byte_offset": offset, "size": size}],
                        )
                stream.seek(offset)
                data = stream.read(min(CHUNK, size - offset))
        except OSError:
            return _report("UNKNOWN", thread_id, db, details + [{"evidence": "rollout_read_failed"}])
        record = _first_dict_line(data)
        if record is None:
            return _report(
                "UNKNOWN",
                thread_id,
                db,
                details + [{"evidence": "boundary_record_unreadable", "byte_offset": offset}],
            )
        rec_ordinal = record.get("ordinal")
        if not isinstance(rec_ordinal, int) or isinstance(rec_ordinal, bool):
            return _report(
                "MATCH",
                thread_id,
                db,
                details + [{"evidence": "no_ordinal_on_boundary_record", "byte_offset": offset}],
            )
        if rec_ordinal != next_ordinal:
            return _report(
                "WEDGED",
                thread_id,
                db,
                details
                + [
                    {
                        "evidence": "boundary_ordinal_mismatch",
                        "expected": next_ordinal,
                        "actual": rec_ordinal,
                        "byte_offset": offset,
                    }
                ],
            )
        if _ordinal_replayed_before(rollout, offset, rec_ordinal):
            return _report(
                "WEDGED",
                thread_id,
                db,
                details + [{"evidence": "replayed_boundary_ordinal", "ordinal": rec_ordinal, "byte_offset": offset}],
            )
        return _report(
            "MATCH",
            thread_id,
            db,
            details + [{"evidence": "boundary_ordinal_ok", "ordinal": rec_ordinal, "byte_offset": offset}],
        )
    except Exception:
        # Fail closed but quietly: an unreadable environment is never a MATCH.
        status = "UNKNOWN" if matched else "NOT_APPLICABLE"
        return _report(status, None, None, [{"evidence": "analysis_failed"}])
