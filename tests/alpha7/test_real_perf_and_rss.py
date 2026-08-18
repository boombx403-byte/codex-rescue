from __future__ import annotations

import io
import os
import platform
import sys
import tempfile
import time
import unittest
from pathlib import Path

from codex_rescue.alpha7.recovery.salvage_stream import StreamSalvageEngine


def get_current_rss_mb() -> float:
    """Returns current process Resident Set Size (RSS) in megabytes."""
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        return float(parts[1]) / 1024.0
        except Exception:
            pass
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return usage.ru_maxrss / 1024.0
        except Exception:
            return 0.0
    elif system == "Darwin":
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return usage.ru_maxrss / (1024.0 * 1024.0)
        except Exception:
            return 0.0
    elif system == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), ctypes.sizeof(counters)
            ):
                return counters.WorkingSetSize / (1024.0 * 1024.0)
        except Exception:
            return 0.0
    return 0.0


class RealPerfAndRSSTests(unittest.TestCase):
    def test_10mb_streaming_rss_measured(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "bench_10mb.jsonl"
            line = '{"turn": 1, "data": "' + ("A" * 1024) + '"}\n'
            target_bytes = 10 * 1024 * 1024
            written = 0
            with open(f, "w", encoding="utf-8") as out:
                while written < target_bytes:
                    out.write(line)
                    written += len(line)

            rss_before = get_current_rss_mb()
            t0 = time.perf_counter()
            engine = StreamSalvageEngine()
            res = engine.scan_file(f)
            t1 = time.perf_counter()
            rss_after = get_current_rss_mb()

            elapsed = t1 - t0
            self.assertEqual(res.source_status, "HEALTHY")
            self.assertEqual(res.unclassified_bytes, 0)
            print(f"\n[BENCH 10MB] Exact Bytes: {written}, Time: {elapsed:.3f}s, RSS Before: {rss_before:.1f}MB, RSS After: {rss_after:.1f}MB, Records: {res.valid_records_count}")

    def test_100mb_streaming_rss_measured(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "bench_100mb.jsonl"
            line = '{"turn": 1, "data": "' + ("B" * 4096) + '"}\n'
            target_bytes = 100 * 1024 * 1024
            written = 0
            with open(f, "w", encoding="utf-8") as out:
                while written < target_bytes:
                    out.write(line)
                    written += len(line)

            rss_before = get_current_rss_mb()
            t0 = time.perf_counter()
            engine = StreamSalvageEngine()
            res = engine.scan_file(f)
            t1 = time.perf_counter()
            rss_after = get_current_rss_mb()

            elapsed = t1 - t0
            self.assertEqual(res.source_status, "HEALTHY")
            self.assertEqual(res.unclassified_bytes, 0)
            print(f"[BENCH 100MB] Exact Bytes: {written}, Time: {elapsed:.3f}s, RSS Before: {rss_before:.1f}MB, RSS After: {rss_after:.1f}MB, Records: {res.valid_records_count}")
            if rss_before > 0 and rss_after > 0:
                diff = abs(rss_after - rss_before)
                self.assertLess(diff, 50.0, "Memory growth exceeds bounded streaming gate!")

    def test_500mb_streaming_rss_measured(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "bench_500mb.jsonl"
            line = '{"turn": 1, "data": "' + ("C" * 16384) + '"}\n'
            target_bytes = 500 * 1024 * 1024
            written = 0
            with open(f, "w", encoding="utf-8") as out:
                while written < target_bytes:
                    out.write(line)
                    written += len(line)

            rss_before = get_current_rss_mb()
            t0 = time.perf_counter()
            engine = StreamSalvageEngine()
            res = engine.scan_file(f)
            t1 = time.perf_counter()
            rss_after = get_current_rss_mb()

            elapsed = t1 - t0
            self.assertEqual(res.source_status, "HEALTHY")
            self.assertEqual(res.unclassified_bytes, 0)
            print(f"[BENCH 500MB] Exact Bytes: {written}, Time: {elapsed:.3f}s, RSS Before: {rss_before:.1f}MB, RSS After: {rss_after:.1f}MB, Records: {res.valid_records_count}")
            if rss_before > 0 and rss_after > 0:
                diff = abs(rss_after - rss_before)
                self.assertLess(diff, 50.0, "Memory growth exceeds bounded streaming gate on 500MB!")

    def test_1gb_streaming_volume_measured(self):
        """Simulates 1GB+ stream scan using chunked stream generator to verify bounded memory."""
        chunk = ('{"turn": 1, "data": "' + ("D" * 65500) + '"}\n').encode("utf-8")
        chunk_len = len(chunk)
        total_records = 16384  # 16384 * ~65KB = ~1.07 GB
        total_bytes = total_records * chunk_len

        class Chunked1GBStream(io.RawIOBase):
            def __init__(self, total_bytes: int, chunk: bytes):
                self.total = total_bytes
                self.delivered = 0
                self.chunk = chunk

            def readable(self) -> bool:
                return True

            def readinto(self, b) -> int:
                if self.delivered >= self.total:
                    return 0
                rem = self.total - self.delivered
                offset = self.delivered % len(self.chunk)
                chunk_rem = len(self.chunk) - offset
                to_copy = min(len(b), chunk_rem, rem)
                b[:to_copy] = self.chunk[offset : offset + to_copy]
                self.delivered += to_copy
                return to_copy

        stream = io.BufferedReader(Chunked1GBStream(total_bytes, chunk))

        rss_before = get_current_rss_mb()
        t0 = time.perf_counter()
        engine = StreamSalvageEngine()
        res = engine.scan_stream(stream, total_size=total_bytes)
        t1 = time.perf_counter()
        rss_after = get_current_rss_mb()

        elapsed = t1 - t0
        self.assertEqual(res.source_status, "HEALTHY")
        self.assertEqual(res.valid_records_count, total_records)
        print(f"[BENCH 1GB] Exact Bytes: {total_bytes}, Time: {elapsed:.3f}s, RSS Before: {rss_before:.1f}MB, RSS After: {rss_after:.1f}MB, Records: {res.valid_records_count}")
        if rss_before > 0 and rss_after > 0:
            diff = abs(rss_after - rss_before)
            self.assertLess(diff, 50.0, "Memory growth exceeds bounded streaming gate on 1GB!")


if __name__ == "__main__":
    unittest.main()
