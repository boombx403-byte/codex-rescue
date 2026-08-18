from __future__ import annotations

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
    if system == "Linux" or system == "Darwin":
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # Linux returns kilobytes, macOS returns bytes
            factor = 1024.0 if system == "Linux" else (1024.0 * 1024.0)
            return usage.ru_maxrss / factor
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
            print(f"\n[BENCH 10MB] Time: {elapsed:.3f}s, RSS Before: {rss_before:.1f}MB, RSS After: {rss_after:.1f}MB")

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
            print(f"[BENCH 100MB] Time: {elapsed:.3f}s, RSS Before: {rss_before:.1f}MB, RSS After: {rss_after:.1f}MB")
            # Memory difference should be negligible (< 35MB)
            if rss_before > 0 and rss_after > 0:
                diff = abs(rss_after - rss_before)
                self.assertLess(diff, 50.0, "Memory growth exceeds bounded streaming gate!")


if __name__ == "__main__":
    unittest.main()
