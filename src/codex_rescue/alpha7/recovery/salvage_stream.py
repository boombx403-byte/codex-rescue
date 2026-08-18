from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple


class RecordClassification:
    VALID = "VALID"
    VALID_BUT_OVERSIZED = "VALID_BUT_OVERSIZED"
    MALFORMED_RECORD = "MALFORMED_RECORD"
    TRUNCATED_TRANSCRIPT = "TRUNCATED_TRANSCRIPT"
    UNCLASSIFIED_BYTES = "UNCLASSIFIED_BYTES"


@dataclass
class StreamSalvageResult:
    total_bytes: int = 0
    scanned_bytes: int = 0
    valid_records_count: int = 0
    oversized_records_count: int = 0
    malformed_records_count: int = 0
    unclassified_bytes: int = 0
    has_truncated_tail: bool = False
    valid_prefix_bytes: int = 0
    largest_record_bytes: int = 0
    source_status: str = "HEALTHY"  # HEALTHY, RECOVERABLE_WITH_TAIL_TRUNCATION, CORRUPTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_bytes": self.total_bytes,
            "scanned_bytes": self.scanned_bytes,
            "valid_records_count": self.valid_records_count,
            "oversized_records_count": self.oversized_records_count,
            "malformed_records_count": self.malformed_records_count,
            "unclassified_bytes": self.unclassified_bytes,
            "has_truncated_tail": self.has_truncated_tail,
            "valid_prefix_bytes": self.valid_prefix_bytes,
            "largest_record_bytes": self.largest_record_bytes,
            "source_status": self.source_status,
        }


class StreamSalvageEngine:
    """Bounded, memory-efficient JSONL salvage scanner for Alpha7."""

    def __init__(self, oversized_threshold: int = 1_000_000, chunk_size: int = 65536):
        self.oversized_threshold = oversized_threshold
        self.chunk_size = chunk_size

    def scan_file(self, file_path: Path) -> StreamSalvageResult:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        total_size = file_path.stat().st_size
        with open(file_path, "rb") as f:
            return self.scan_stream(f, total_size=total_size)

    def scan_stream(self, stream: Any, total_size: Optional[int] = None) -> StreamSalvageResult:
        result = StreamSalvageResult(total_bytes=total_size or 0)
        valid_prefix_offset = 0
        is_still_clean_prefix = True
        line_no = 0

        while True:
            line = stream.readline()
            if not line:
                break

            line_len = len(line)
            result.scanned_bytes += line_len
            line_no += 1

            if line_len > result.largest_record_bytes:
                result.largest_record_bytes = line_len

            stripped = line.strip()
            if not stripped:
                if is_still_clean_prefix:
                    valid_prefix_offset = result.scanned_bytes
                continue

            if b"\x00" in line:
                result.malformed_records_count += 1
                is_still_clean_prefix = False
                continue

            try:
                parsed = json.loads(stripped.decode("utf-8"))
                if line_len > self.oversized_threshold:
                    result.oversized_records_count += 1
                else:
                    result.valid_records_count += 1

                if is_still_clean_prefix:
                    valid_prefix_offset = result.scanned_bytes

            except Exception:
                is_at_eof = (total_size is not None and result.scanned_bytes == total_size)
                if is_at_eof:
                    result.has_truncated_tail = True
                else:
                    result.malformed_records_count += 1
                is_still_clean_prefix = False

        result.valid_prefix_bytes = valid_prefix_offset
        if total_size is not None:
            result.unclassified_bytes = max(0, total_size - result.scanned_bytes)
        else:
            result.total_bytes = result.scanned_bytes

        if result.malformed_records_count > 0:
            result.source_status = "CORRUPTED"
        elif result.has_truncated_tail:
            result.source_status = "RECOVERABLE_WITH_TAIL_TRUNCATION"
        else:
            result.source_status = "HEALTHY"

        return result
