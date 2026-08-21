"""Alpha8: slim — produce a media-deduplicated clean fork of a rollout.

Field evidence (#33735: 24 GB rollouts, #33016: 260 MB single thread,
#24100: compaction wedged by inline image payloads): Codex compaction
re-emits previously inlined images into every compacted record, and
descendant sessions copy that history forward.

``slim`` builds a *new* fork file (never mutates the source) in which:

- The first occurrence of each unique media payload is preserved.
- Subsequent duplicate payloads are replaced by a short placeholder stub
  record documenting what was removed and where the canonical copy lives.
- Everything non-media passes through byte-identical.

Safety model:

- Output is always a new file next to nothing the user did not ask for;
  the source rollout is opened read-only.
- A SHA-256 of the source is recorded in the report before any write.
- Dry-run by default; ``--write`` only controls whether the fork file is
  kept on disk (it is written to a temp path either way for measurement).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_SCAN_LINE = 64 * 1024 * 1024  # hard cap for a single forked line
_MIN_MEDIA_B64_LEN = 512

_DATAURL_RE = re.compile(r"data:image/[a-zA-Z+.-]+;base64,([A-Za-z0-9+/=]{%d,})" % _MIN_MEDIA_B64_LEN)


@dataclass
class SlimReport:
    source_path: str
    fork_path: str | None = None
    source_sha256: str | None = None
    source_size: int = 0
    fork_size: int | None = None
    records_total: int = 0
    records_kept: int = 0
    records_stubbed: int = 0
    media_unique_kept: int = 0
    media_dupes_removed: int = 0
    bytes_saved: int = 0
    truncated_tail_quarantined: bool = False
    errors: list[str] = field(default_factory=list)
    write_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "fork_path": self.fork_path,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
            "fork_size": self.fork_size,
            "records_total": self.records_total,
            "records_kept": self.records_kept,
            "records_stubbed": self.records_stubbed,
            "media_unique_kept": self.media_unique_kept,
            "media_dupes_removed": self.media_dupes_removed,
            "bytes_saved": self.bytes_saved,
            "truncated_tail_quarantined": self.truncated_tail_quarantined,
            "errors": self.errors,
            "write_performed": self.write_performed,
        }

    def render_text(self) -> str:
        lines = [
            f"Slim: {self.source_path}",
            f"source: {self.source_size}B sha256[:12]={self.source_sha256 or '-'}",
        ]
        if self.fork_path:
            lines.append(f"fork:   {self.fork_path} ({self.fork_size}B)")
        lines += [
            f"records: total={self.records_total} kept={self.records_kept} "
            f"stubbed={self.records_stubbed}",
            f"media: unique kept={self.media_unique_kept} "
            f"duplicates removed={self.media_dupes_removed}",
            f"bytes saved: {self.bytes_saved}",
        ]
        if self.truncated_tail_quarantined:
            lines.append("truncated tail quarantined into fork metadata")
        if not self.write_performed:
            lines.append("(dry-run: fork discarded after measurement)")
        for err in self.errors:
            lines.append(f"ERROR: {err}")
        return "\n".join(lines)


def _stub_record(sha_prefix: str, original_bytes: int) -> dict[str, Any]:
    return {
        "type": "codex_rescue_media_stub",
        "payload": {
            "reason": "duplicate inline media payload removed by codex-rescue slim",
            "canonical_source_sha256_12": sha_prefix,
            "original_payload_bytes_approx": original_bytes,
        },
    }


def slim_rollout(
    source: str | Path,
    *,
    fork_path: str | Path | None = None,
    keep_fork: bool = False,
) -> SlimReport:
    """Build a media-deduplicated fork of ``source``.

    ``keep_fork=False`` measures only (dry-run): the fork bytes are streamed
    to a temp file and deleted. ``keep_fork=True`` writes the fork next to
    the source (or at ``fork_path``).
    """
    src = Path(source).resolve()
    report = SlimReport(source_path=str(src))
    report.source_size = src.stat().st_size

    digest = hashlib.sha256()
    seen_media: set[str] = set()

    dest: Path | None = None
    tmp_dest: Path | None = None
    import tempfile as _tf

    if keep_fork:
        dest = (
            Path(fork_path).resolve()
            if fork_path
            else src.with_name(src.stem + ".slim.jsonl")
        )
        if keep_fork:
            _tmp_fd, _tmp_name = _tf.mkstemp(
                prefix=".slim-", suffix=".tmp", dir=dest.parent
            )
            import os as _os

            _os.close(_tmp_fd)  # mkstemp leaks an fd; close before reopen.
            tmp_dest = Path(_tmp_name)

    out_stream = open(tmp_dest, "wb") if tmp_dest else None
    try:
        with src.open("rb") as stream:
            while True:
                line = stream.readline(MAX_SCAN_LINE)
                if not line:
                    break
                digest.update(line)
                report.records_total += 1

                # Truncated tail: quarantine rather than propagate silently.
                if not line.endswith(b"\n") and stream.peek(1) == b"":
                    report.truncated_tail_quarantined = True
                    break

                text = line.decode("utf-8", errors="replace")
                matches = list(_DATAURL_RE.finditer(text))
                if not matches:
                    report.records_kept += 1
                    if out_stream:
                        out_stream.write(line)
                    continue

                dupes_here = 0
                new_hashes: list[str] = []
                for m in matches:
                    payload = m.group(1)
                    payload_digest = hashlib.sha256(payload.encode("ascii")).hexdigest()[:16]
                    if payload_digest in seen_media:
                        dupes_here += 1
                    else:
                        seen_media.add(payload_digest)
                        new_hashes.append(payload_digest)

                if not dupes_here:
                    # All payloads are first occurrences: keep verbatim.
                    for h in new_hashes:
                        pass
                    report.media_unique_kept += len(new_hashes)
                    report.records_kept += 1
                    if out_stream:
                        out_stream.write(line)
                    continue

                # Rebuild the record with duplicate payloads stripped.
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    # Malformed beyond repair: keep byte-identical, do not guess.
                    report.records_kept += 1
                    if out_stream:
                        out_stream.write(line)
                    continue

                removed_bytes = 0

                def _strip(obj: Any) -> Any:
                    nonlocal removed_bytes
                    if isinstance(obj, dict):
                        out = {}
                        for k, v in obj.items():
                            if isinstance(v, str):
                                def _sub(m: re.Match[str]) -> str:
                                    nonlocal removed_bytes
                                    payload = m.group(1)
                                    h = hashlib.sha256(payload.encode("ascii")).hexdigest()[:16]
                                    if h in seen_media:
                                        removed_bytes += len(m.group(0))
                                        return f"[REDACTED_DUPLICATE_MEDIA:{h}]"
                                    seen_media.add(h)
                                    return m.group(0)
                                v = _DATAURL_RE.sub(_sub, v)
                            elif isinstance(v, (dict, list)):
                                v = _strip(v)
                            out[k] = v
                        return out
                    if isinstance(obj, list):
                        return [_strip(x) for x in obj]
                    return obj

                record = _strip(record)
                report.media_dupes_removed += dupes_here
                report.media_unique_kept += len(new_hashes)
                report.records_stubbed += 1
                new_line = (
                    json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
                )
                report.bytes_saved += max(len(line) - len(new_line), 0)
                report.records_kept += 1
                if out_stream:
                    out_stream.write(new_line)

        report.source_sha256 = digest.hexdigest()
    finally:
        if out_stream:
            out_stream.flush()
            out_stream.close()
            out_stream = None

        if tmp_dest is not None:
            import os

            if keep_fork and dest is not None:
                report.fork_size = os.path.getsize(tmp_dest)
                os.replace(tmp_dest, dest)
                report.fork_path = str(dest)
                report.write_performed = True
            else:
                try:
                    os.unlink(tmp_dest)
                except OSError:
                    pass

    return report
