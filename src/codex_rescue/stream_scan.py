"""Alpha8: single-pass streaming JSONL scanner with bounded memory.

Complements :mod:`codex_rescue.transcript` (which performs full diagnostic
parsing) with a lightweight one-pass profile focused on what salvage/slim
need: record offsets, byte sizes, payload classes, and media-payload
detection — without retaining parsed records.

Design goals (field evidence #37719, #15411, #33735):

- Exactly one sequential pass; no second read of the file.
- Bounded memory: only per-record metadata and capped aggregates are kept.
- Oversized lines are drained (never materialized in memory) but still
  counted with their true byte length.
- A truncated final line is reported as ``TRUNCATED_TAIL`` rather than
  failing the whole scan, so downstream tools can quarantine just the tail.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_RECORD_BYTES = 16 * 1024 * 1024  # bounded line cap; larger lines are drained
DEFAULT_MAX_RECORDS = 200_000
_MAX_RETAINED_SAMPLES = 20

_MEDIA_KEY_RE = re.compile(
    rb"(image_url|input_image|base64|data:image/[a-z+]+;base64|inline_data)",
    re.IGNORECASE,
)
_MEDIA_DATAURL_RE = re.compile(rb"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]{512,}")


@dataclass
class StreamScanResult:
    path: str
    source_size: int = 0
    sha256_prefix: str | None = None
    records_total: int = 0
    records_ok: int = 0
    oversized_count: int = 0
    malformed_count: int = 0
    non_object_count: int = 0
    truncated_tail: bool = False
    truncated_tail_offset: int | None = None
    media_record_count: int = 0
    media_bytes_total: int = 0
    largest_record_bytes: int = 0
    largest_record_offset: int | None = None
    scanned_complete: bool = True
    samples_oversized: list[dict[str, Any]] = field(default_factory=list)
    samples_media: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source_size": self.source_size,
            "sha256_prefix": self.sha256_prefix,
            "records_total": self.records_total,
            "records_ok": self.records_ok,
            "oversized_count": self.oversized_count,
            "malformed_count": self.malformed_count,
            "non_object_count": self.non_object_count,
            "truncated_tail": self.truncated_tail,
            "truncated_tail_offset": self.truncated_tail_offset,
            "media_record_count": self.media_record_count,
            "media_bytes_total": self.media_bytes_total,
            "largest_record_bytes": self.largest_record_bytes,
            "largest_record_offset": self.largest_record_offset,
            "scanned_complete": self.scanned_complete,
        }

    def render_text(self) -> str:
        lines = [
            f"StreamScan: {self.path}",
            f"size={self.source_size}B sha256[:12]={self.sha256_prefix or '-'}",
            f"records: total={self.records_total} ok={self.records_ok} "
            f"oversized={self.oversized_count} malformed={self.malformed_count} "
            f"non-object={self.non_object_count}",
            f"media payloads: {self.media_record_count} records, "
            f"{self.media_bytes_total}B",
            f"largest record: {self.largest_record_bytes}B "
            f"@offset {self.largest_record_offset}",
        ]
        if self.truncated_tail:
            lines.append(
                f"TRUNCATED_TAIL at offset {self.truncated_tail_offset} "
                "(final line has no newline terminator)"
            )
        if not self.scanned_complete:
            lines.append("WARNING: scan stopped before EOF (max_records cap)")
        return "\n".join(lines)


def _read_line_bounded(
    stream: Any,
    max_record_bytes: int,
    digest: Any,
) -> tuple[bytes | None, bool, bool, int]:
    """Read one newline-terminated line without exceeding bounded memory.

    Returns ``(head, was_drained, ends_with_newline, consumed)`` where
    ``head`` contains at most the first ``max_record_bytes`` bytes of the
    line (None at EOF). When a line exceeds the cap, the remainder is
    drained through the running hash so offsets and digests stay exact.
    """
    head = stream.readline(max_record_bytes)
    if not head:
        return None, False, False, 0
    consumed = len(head)
    digest.update(head)
    ends_with_newline = head.endswith(b"\n")
    if ends_with_newline or consumed < max_record_bytes:
        return head, False, ends_with_newline, consumed

    # Drain the rest of the oversized line in bounded chunks.
    was_drained = True
    while True:
        chunk = stream.readline(max_record_bytes)
        if not chunk:
            break
        consumed += len(chunk)
        digest.update(chunk)
        if chunk.endswith(b"\n"):
            ends_with_newline = True
            break
        # readline returns fewer bytes only at EOF; keep looping otherwise.
    return head, was_drained, ends_with_newline, consumed


def _estimate_media_bytes(head: bytes) -> int:
    """Estimate how many bytes of a (bounded) line are inline media payloads."""
    total = 0
    for match in _MEDIA_DATAURL_RE.finditer(head):
        total += match.end() - match.start()
    return total


def stream_scan_rollout(
    path: str | Path,
    *,
    max_record_bytes: int = MAX_RECORD_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> StreamScanResult:
    """Profile a rollout JSONL in exactly one sequential pass."""
    source = Path(path)
    result = StreamScanResult(path=str(source))
    result.source_size = source.stat().st_size

    digest = hashlib.sha256()
    offset = 0
    index = 0

    with source.open("rb") as stream:
        while True:
            if index >= max_records:
                result.scanned_complete = False
                break
            start = offset
            head, drained, complete, consumed = _read_line_bounded(
                stream, max_record_bytes, digest
            )
            if head is None:
                break
            offset += consumed

            classification = "ok"
            has_media = False
            media_bytes = 0
            record_type: str | None = None

            if drained:
                result.oversized_count += 1
                classification = "oversized"
                if len(result.samples_oversized) < _MAX_RETAINED_SAMPLES:
                    result.samples_oversized.append(
                        {
                            "start_offset": start,
                            "byte_length": consumed,
                            "complete_line": complete,
                        }
                    )
            else:
                stripped = head.strip()
                if not stripped:
                    result.malformed_count += 1
                    classification = "malformed"
                else:
                    try:
                        record = json.loads(stripped)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        if not complete and start + consumed >= result.source_size:
                            result.truncated_tail = True
                            result.truncated_tail_offset = start
                            classification = "truncated_tail"
                        else:
                            result.malformed_count += 1
                            classification = "malformed"
                    except Exception:
                        result.malformed_count += 1
                        classification = "malformed"
                    else:
                        if isinstance(record, dict):
                            result.records_ok += 1
                            raw_type = record.get("type")
                            record_type = (
                                str(raw_type) if raw_type is not None else None
                            )
                            if _MEDIA_KEY_RE.search(head):
                                has_media = True
                                media_bytes = _estimate_media_bytes(head)
                                if media_bytes == 0:
                                    # Media marker without a long base64 body in
                                    # the sampled window: conservative estimate.
                                    media_bytes = min(consumed, 4096)
                                result.media_record_count += 1
                                result.media_bytes_total += media_bytes
                                if len(result.samples_media) < _MAX_RETAINED_SAMPLES:
                                    result.samples_media.append(
                                        {
                                            "start_offset": start,
                                            "byte_length": consumed,
                                            "media_bytes_estimate": media_bytes,
                                        }
                                    )
                        else:
                            result.non_object_count += 1
                            classification = "non_object"

            result.records_total += 1
            if consumed > result.largest_record_bytes:
                result.largest_record_bytes = consumed
                result.largest_record_offset = start
            index += 1

        result.sha256_prefix = digest.hexdigest()[:12]

    return result
