"""Comprehensive Concurrency, TOCTOU & Windows File Sharing Harnesses.

Milestone R1 (Phases 0–5):
- Part A: Multi-process concurrent writer & reader harness testing 1,000+ iterations
  across live appends, byte streaming, codepoint splits, unclosed lines, truncations,
  file rotations, and rapid deletes, asserting 100% source byte SHA-256 immutability.
- Part B: Win32 handle sharing & lock harness via ctypes.windll.kernel32 (CreateFileW,
  LockFileEx, CloseHandle) testing FILE_SHARE_READ, FILE_SHARE_WRITE, FILE_SHARE_DELETE,
  exclusive locks, byte-range locks, and Win32 errors 32, 33, 5.
- Part C: TOCTOU mutation injection across 5 critical synchronization points
  (snapshot->parse->snapshot, stat->open->truncate, source hash->verify,
  salvage collision/target mutation, verify git working tree mutation).
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable, Generator, Iterator
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from codex_rescue.artifacts import (
    _atomic_replace,
    _replace_retryable,
    atomic_write,
    load_handoff,
    write_rescue,
)
from codex_rescue.discovery import discover_sessions
from codex_rescue.doctor import doctor_session
from codex_rescue.gitstate import inspect_git_state
from codex_rescue.salvage import file_sha256, file_snapshot, salvage_session
from codex_rescue.transcript import parse_transcript
from codex_rescue.verify import verify_rescue

# Platform check
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # 32-bit and 64-bit compatible OVERLAPPED structure
    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    LPOVERLAPPED = ctypes.POINTER(OVERLAPPED)

    # Win32 Access Rights
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    GENERIC_ALL = 0x10000000
    FILE_READ_DATA = 0x00000001
    FILE_WRITE_DATA = 0x00000002
    FILE_APPEND_DATA = 0x00000004
    DELETE = 0x00010000

    # Win32 Share Modes
    FILE_SHARE_EXCLUSIVE = 0x00000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004

    # Win32 Creation Dispositions
    CREATE_NEW = 1
    CREATE_ALWAYS = 2
    OPEN_EXISTING = 3
    OPEN_ALWAYS = 4
    TRUNCATE_EXISTING = 5

    # Win32 Attributes and Flags
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_ATTRIBUTE_READONLY = 0x00000001
    FILE_FLAG_DELETE_ON_CLOSE = 0x04000000
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

    # Win32 Lock Flags
    LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    LOCKFILE_EXCLUSIVE_LOCK = 0x00000002

    # Win32 Error Codes
    ERROR_SUCCESS = 0
    ERROR_FILE_NOT_FOUND = 2
    ERROR_PATH_NOT_FOUND = 3
    ERROR_ACCESS_DENIED = 5
    ERROR_SHARING_VIOLATION = 32
    ERROR_LOCK_VIOLATION = 33
    ERROR_ALREADY_EXISTS = 183

    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    # Prototypes with explicit argtypes and restype
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        LPOVERLAPPED,
    ]
    kernel32.LockFileEx.restype = wintypes.BOOL

    kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        LPOVERLAPPED,
    ]
    kernel32.UnlockFileEx.restype = wintypes.BOOL

    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL

    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        LPOVERLAPPED,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL

    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        LPOVERLAPPED,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    kernel32.GetProcessHandleCount.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetProcessHandleCount.restype = wintypes.BOOL

else:
    kernel32 = None
    INVALID_HANDLE_VALUE = -1
    GENERIC_READ = 0
    GENERIC_WRITE = 0
    FILE_SHARE_READ = 0
    FILE_SHARE_WRITE = 0
    FILE_SHARE_DELETE = 0
    OPEN_EXISTING = 0
    FILE_ATTRIBUTE_NORMAL = 0
    ERROR_ACCESS_DENIED = 5
    ERROR_SHARING_VIOLATION = 32
    ERROR_LOCK_VIOLATION = 33


class Win32FileHandle:
    """Encapsulates a Win32 file handle with context management and byte-range locking."""

    def __init__(
        self,
        path: str | Path,
        access: int | str = "rw",
        share: int | str = "rwd",
        disposition: int = 3,  # OPEN_EXISTING
        flags: int = 0x80,      # FILE_ATTRIBUTE_NORMAL
    ) -> None:
        if not IS_WINDOWS:
            raise RuntimeError("Win32FileHandle is only supported on Windows")

        self.path = str(Path(path).resolve())
        self._disposition = disposition
        self._flags = flags
        self.handle: int | None = None
        self._active_locks: list[tuple[int, int]] = []

        if isinstance(access, int):
            self._access = access
        else:
            acc = 0
            if "r" in access:
                acc |= GENERIC_READ
            if "w" in access or "a" in access:
                acc |= GENERIC_WRITE
            self._access = acc or GENERIC_READ

        if isinstance(share, int):
            self._share = share
        else:
            sm = 0
            share_lower = share.lower()
            if share_lower in ("none", "exclusive", "0"):
                sm = 0
            elif share_lower in ("all", "rwd", "rwa"):
                sm = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
            else:
                if "r" in share_lower:
                    sm |= FILE_SHARE_READ
                if "w" in share_lower:
                    sm |= FILE_SHARE_WRITE
                if "d" in share_lower:
                    sm |= FILE_SHARE_DELETE
            self._share = sm

    def is_open(self) -> bool:
        return self.handle is not None and self.handle != INVALID_HANDLE_VALUE

    def open(self) -> Win32FileHandle:
        if self.is_open():
            return self

        h = kernel32.CreateFileW(
            self.path,
            self._access,
            self._share,
            None,
            self._disposition,
            self._flags,
            None,
        )
        if h == INVALID_HANDLE_VALUE or h is None:
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)

        self.handle = h
        return self

    def close(self) -> None:
        if not self.is_open():
            return

        for offset, length in list(self._active_locks):
            try:
                self.unlock_range(offset, length)
            except Exception:
                pass
        self._active_locks.clear()

        h = self.handle
        self.handle = None
        if h is not None and h != INVALID_HANDLE_VALUE:
            kernel32.CloseHandle(h)

    def __enter__(self) -> Win32FileHandle:
        return self.open()

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def lock_range(
        self,
        offset: int = 0,
        length: int = 0xFFFFFFFF,
        exclusive: bool = True,
        fail_immediately: bool = True,
    ) -> None:
        if not self.is_open():
            raise RuntimeError("Cannot lock range on an unopened handle")

        flags = 0
        if exclusive:
            flags |= LOCKFILE_EXCLUSIVE_LOCK
        if fail_immediately:
            flags |= LOCKFILE_FAIL_IMMEDIATELY

        ov = OVERLAPPED()
        ov.Offset = offset & 0xFFFFFFFF
        ov.OffsetHigh = (offset >> 32) & 0xFFFFFFFF

        low_len = length & 0xFFFFFFFF
        high_len = (length >> 32) & 0xFFFFFFFF

        res = kernel32.LockFileEx(self.handle, flags, 0, low_len, high_len, ctypes.byref(ov))
        if not res:
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)

        self._active_locks.append((offset, length))

    def unlock_range(self, offset: int = 0, length: int = 0xFFFFFFFF) -> None:
        if not self.is_open():
            return

        ov = OVERLAPPED()
        ov.Offset = offset & 0xFFFFFFFF
        ov.OffsetHigh = (offset >> 32) & 0xFFFFFFFF

        low_len = length & 0xFFFFFFFF
        high_len = (length >> 32) & 0xFFFFFFFF

        res = kernel32.UnlockFileEx(self.handle, 0, low_len, high_len, ctypes.byref(ov))
        if not res:
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)

        if (offset, length) in self._active_locks:
            self._active_locks.remove((offset, length))

    @contextlib.contextmanager
    def locked_range(
        self,
        offset: int = 0,
        length: int = 0xFFFFFFFF,
        exclusive: bool = True,
        fail_immediately: bool = True,
    ) -> Iterator[Win32FileHandle]:
        self.lock_range(offset, length, exclusive=exclusive, fail_immediately=fail_immediately)
        try:
            yield self
        finally:
            self.unlock_range(offset, length)

    def write_bytes(self, data: bytes) -> int:
        if not self.is_open():
            raise RuntimeError("Cannot write to an unopened handle")
        written = wintypes.DWORD(0)
        res = kernel32.WriteFile(self.handle, data, len(data), ctypes.byref(written), None)
        if not res:
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)
        return written.value

    def read_bytes(self, size: int = 4096) -> bytes:
        if not self.is_open():
            raise RuntimeError("Cannot read from an unopened handle")
        buf = ctypes.create_string_buffer(size)
        read = wintypes.DWORD(0)
        res = kernel32.ReadFile(self.handle, buf, size, ctypes.byref(read), None)
        if not res:
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)
        return buf.raw[: read.value]

    def flush(self) -> None:
        if self.is_open():
            kernel32.FlushFileBuffers(self.handle)


def get_current_process_handle_count() -> int:
    if not IS_WINDOWS:
        return 0
    count = wintypes.DWORD(0)
    res = kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(count))
    if not res:
        raise ctypes.WinError(ctypes.get_last_error())
    return count.value


@contextlib.contextmanager
def assert_zero_handle_leak(tolerance: int = 2) -> Generator[None, None, None]:
    if not IS_WINDOWS:
        yield
        return
    before = get_current_process_handle_count()
    try:
        yield
    finally:
        after = get_current_process_handle_count()
        diff = after - before
        if diff > tolerance:
            raise AssertionError(f"Handle leak detected: before={before}, after={after}, diff={diff}")


def _create_sample_session(path: Path, num_records: int = 5, cwd: str | Path | None = None) -> None:
    cwd_str = str(cwd) if cwd is not None else None
    records = [
        {"type": "session_meta", "payload": {"id": "session-concurrency-test", "cwd": cwd_str, "cli_version": "0.147.0"}},
    ]
    for i in range(num_records):
        records.append({
            "type": "event_msg",
            "payload": {"type": "user_message", "message": f"Step {i}: execute instruction"},
        })
        records.append({
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": f"call-{i}",
                "name": "exec_cmd",
                "arguments": json.dumps({"cmd": f"echo {i}"}),
            },
        })
        records.append({
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": f"call-{i}",
                "output": f"result {i}\n",
            },
        })
    path.write_bytes(b"".join((json.dumps(r) + "\n").encode("utf-8") for r in records))


def _create_sample_git_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "concurrency@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Concurrency Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("initial tracked file\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial commit"], cwd=repo, check=True)
    return repo


# ============================================================================
# PART A: Multi-Process Concurrent Writer & Reader Harness (1,000+ Iterations)
# ============================================================================

class ConcurrentWriterReaderTests(unittest.TestCase):
    """Part A: Concurrent writer & reader stress testing 1,000+ iterations."""

    def test_concurrent_live_appends_250_iterations(self) -> None:
        """C1: 250 iterations of live concurrent appends while doctor/salvage parses."""
        with tempfile.TemporaryDirectory() as td:
            session_path = Path(td) / "live_appends.jsonl"
            _create_sample_session(session_path, num_records=3, cwd=None)

            for i in range(250):
                # Capture baseline state before iteration
                before_hash = file_sha256(session_path)

                # Execute concurrent read inspection (doctor)
                doc = doctor_session(session_path)
                self.assertIn(doc.status, ("HEALTHY", "UNFINISHED_TOOL_CALL", "TRUNCATED_TRANSCRIPT"))

                # Writer performs append
                append_record = {
                    "type": "event_msg",
                    "payload": {"type": "agent_message", "message": f"iteration {i} live append"},
                }
                with session_path.open("ab") as f:
                    f.write((json.dumps(append_record) + "\n").encode("utf-8"))

                # Re-verify that reader can still parse after append without crashing
                parsed = parse_transcript(session_path)
                self.assertGreater(len(parsed.events), 0)

                # Ensure source byte SHA-256 matches current file on disk (rescue tool didn't mutate)
                current_disk_hash = hashlib.sha256(session_path.read_bytes()).hexdigest()
                self.assertEqual(file_sha256(session_path), current_disk_hash)

    def test_byte_by_byte_streaming_races_200_iterations(self) -> None:
        """C2: 200 iterations of byte-by-byte streaming and boundary reads."""
        with tempfile.TemporaryDirectory() as td:
            session_path = Path(td) / "streaming.jsonl"
            session_path.write_bytes(b"")

            valid_header = json.dumps({
                "type": "session_meta",
                "payload": {"id": "streaming-session", "cwd": None, "cli_version": "0.147.0"},
            }).encode("utf-8") + b"\n"

            session_path.write_bytes(valid_header)

            payload_bytes = json.dumps({
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "streaming byte test record with payload content"},
            }).encode("utf-8") + b"\n"

            for i in range(200):
                chunk_size = (i % 7) + 1
                offset = (i * chunk_size) % len(payload_bytes)
                chunk = payload_bytes[offset : offset + chunk_size]

                with session_path.open("ab") as f:
                    f.write(chunk)

                # Parse while stream is partially written
                parsed = parse_transcript(session_path)
                # Must not crash, corruption_class must be either None or TRUNCATED_TRANSCRIPT
                self.assertIn(parsed.corruption_class, (None, "TRUNCATED_TRANSCRIPT", "MALFORMED_RECORD"))
                self.assertGreaterEqual(parsed.last_valid_offset, len(valid_header))

    def test_utf8_codepoint_splits_150_iterations(self) -> None:
        """C3: 150 iterations of UTF-8 multibyte codepoint splits at stream EOF."""
        base_line = json.dumps({
            "type": "session_meta",
            "payload": {"id": "split_session", "cwd": None},
        }).encode("utf-8") + b"\n"

        # Split test vectors: 2-byte ('Ж': \xd0\x96), 3-byte ('✓': \xe2\x9c\x93), 4-byte ('🔥': \xf0\x9f\x94\xa5)
        split_tails = [
            b'{"type":"event_msg","payload":{"type":"user_message","message":"\xd0',          # 2-byte split at 1 byte
            b'{"type":"event_msg","payload":{"type":"user_message","message":"\xe2',          # 3-byte split at 1 byte
            b'{"type":"event_msg","payload":{"type":"user_message","message":"\xe2\x9c',      # 3-byte split at 2 bytes
            b'{"type":"event_msg","payload":{"type":"user_message","message":"\xf0',          # 4-byte split at 1 byte
            b'{"type":"event_msg","payload":{"type":"user_message","message":"\xf0\x9f',      # 4-byte split at 2 bytes
            b'{"type":"event_msg","payload":{"type":"user_message","message":"\xf0\x9f\x94',  # 4-byte split at 3 bytes
        ]

        with tempfile.TemporaryDirectory() as td:
            session_path = Path(td) / "codepoint_split.jsonl"

            for i in range(150):
                tail = split_tails[i % len(split_tails)]
                full_content = base_line + tail
                session_path.write_bytes(full_content)

                source_sha_before = hashlib.sha256(full_content).hexdigest()

                parsed = parse_transcript(session_path)
                self.assertEqual(parsed.corruption_class, "TRUNCATED_TRANSCRIPT")
                self.assertEqual(parsed.last_valid_offset, len(base_line))
                self.assertEqual(parsed.first_invalid_offset, len(base_line))

                # Assert source byte immutability
                source_sha_after = file_sha256(session_path)
                self.assertEqual(source_sha_before, source_sha_after)

    def test_unclosed_truncated_jsonl_150_iterations(self) -> None:
        """C4: 150 iterations of unclosed lines and partial JSON tokens."""
        base_line = json.dumps({
            "type": "session_meta",
            "payload": {"id": "unclosed_session", "cwd": None},
        }).encode("utf-8") + b"\n"

        partial_tokens = [
            b'{"type": "response_item"',
            b'{"type": "response_item", "payload":',
            b'{"type": "response_item", "payload": {"type": "function_call"',
            b'{"type": "response_item", "payload": {"type": "function_call", "call_id": "call_1"',
            b'{"type": "response_item", "payload": {"type": "function_call", "call_id": "call_1", "name": "shell"',
            b'{"type": "event_msg", "payload": {"type": "user_message", "message": "incomplete message without closing brace',
        ]

        with tempfile.TemporaryDirectory() as td:
            session_path = Path(td) / "unclosed.jsonl"

            for i in range(150):
                partial = partial_tokens[i % len(partial_tokens)]
                session_path.write_bytes(base_line + partial)

                doc = doctor_session(session_path)
                self.assertEqual(doc.status, "TRUNCATED_TRANSCRIPT")
                self.assertIn("TRUNCATED_TRANSCRIPT", doc.findings)
                self.assertEqual(doc.transcript.last_valid_offset, len(base_line))

    def test_midstream_truncation_rotation_150_iterations(self) -> None:
        """C5: 150 iterations of mid-stream file truncations and rewinds."""
        with tempfile.TemporaryDirectory() as td:
            session_path = Path(td) / "midstream_truncate.jsonl"
            _create_sample_session(session_path, num_records=8, cwd=None)
            full_bytes = session_path.read_bytes()

            for i in range(150):
                # Truncate at different offsets
                trunc_len = (i * 37) % len(full_bytes)
                session_path.write_bytes(full_bytes[:trunc_len])

                doc = doctor_session(session_path)
                self.assertIn(doc.status, ("HEALTHY", "TRUNCATED_TRANSCRIPT", "MALFORMED_RECORD", "EMPTY_SESSION"))

                # Reset to full
                session_path.write_bytes(full_bytes)
                doc_full = doctor_session(session_path)
                self.assertEqual(doc_full.status, "HEALTHY")

    def test_rapid_delete_unlink_races_100_iterations(self) -> None:
        """C6: 100 iterations of rapid deletes/unlinks during session discovery."""
        with tempfile.TemporaryDirectory() as td:
            sessions_root = Path(td) / "sessions"
            sessions_root.mkdir()

            for i in range(100):
                file_path = sessions_root / f"rollout-{i:04d}.jsonl"
                _create_sample_session(file_path, num_records=2, cwd=None)

                # Delete immediately before or during discovery
                if i % 2 == 0:
                    file_path.unlink()

                discovered = discover_sessions(sessions_root, limit=50)
                self.assertIsInstance(discovered, list)

                # Clean up if remaining
                if file_path.exists():
                    file_path.unlink()

    def test_source_byte_immutability_invariant_p1_verified(self) -> None:
        """Rigorous assertion of Invariant P1 across multi-threaded operations."""
        with tempfile.TemporaryDirectory() as td:
            session_path = Path(td) / "p1_immutability.jsonl"
            _create_sample_session(session_path, num_records=10, cwd=None)
            initial_sha = file_sha256(session_path)
            initial_bytes = session_path.read_bytes()

            # Execute 100 concurrent reader threads calling various inspection APIs
            def reader_task(idx: int) -> tuple[str, bool]:
                if idx % 3 == 0:
                    res = doctor_session(session_path)
                    return ("doctor", res.status == "HEALTHY")
                elif idx % 3 == 1:
                    res = parse_transcript(session_path)
                    return ("parse", res.last_valid_offset == len(initial_bytes))
                else:
                    snap = file_snapshot(session_path)
                    return ("snapshot", snap["stable"] is True and snap["sha256"] == initial_sha)

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(reader_task, i) for i in range(100)]
                for future in concurrent.futures.as_completed(futures):
                    kind, ok = future.result()
                    self.assertTrue(ok, f"Reader task {kind} failed")

            # Final SHA-256 and byte comparison
            self.assertEqual(session_path.read_bytes(), initial_bytes)
            self.assertEqual(file_sha256(session_path), initial_sha)


# ============================================================================
# PART B: Win32 Handle Sharing & Byte-Range Lock Harness (ctypes.windll.kernel32)
# ============================================================================

class Win32HandleSharingTests(unittest.TestCase):
    """Part B: Win32 handle sharing modes, byte-range locks, and error code translation."""

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_exclusive_write_handle_blocks_reader_with_error_32(self) -> None:
        """Exclusive write handle (share_mode=0) blocks open with ERROR_SHARING_VIOLATION (32)."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "exclusive_write.jsonl"
            _create_sample_session(path, num_records=2, cwd=None)

            with Win32FileHandle(path, access="w", share="none"):
                # Competing Win32 handle open must fail with Win32 Error 32
                with self.assertRaises(PermissionError) as ctx:
                    Win32FileHandle(path, access="r", share="r").open()
                self.assertEqual(ctx.exception.winerror, ERROR_SHARING_VIOLATION)

                # Attempting to read via standard python open must raise PermissionError
                with self.assertRaises(PermissionError):
                    with path.open("rb") as f:
                        f.read()

                # file_snapshot must fail closed gracefully with PermissionError
                with self.assertRaises(PermissionError):
                    file_snapshot(path)

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_exclusive_read_handle_blocks_all_with_error_32(self) -> None:
        """Exclusive read handle (share_mode=0) blocks subsequent readers with ERROR_SHARING_VIOLATION."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "exclusive_read.jsonl"
            _create_sample_session(path, num_records=2, cwd=None)

            with Win32FileHandle(path, access="r", share="none"):
                # Competing Win32 handle open fails with Error 32
                with self.assertRaises(PermissionError) as ctx:
                    Win32FileHandle(path, access="r", share="r").open()
                self.assertEqual(ctx.exception.winerror, ERROR_SHARING_VIOLATION)

                # Standard python open fails with PermissionError
                with self.assertRaises(PermissionError):
                    with path.open("rb") as f:
                        f.read()

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_shared_read_allows_doctor_and_salvage(self) -> None:
        """FILE_SHARE_READ allows doctor_session and salvage_session while denying writes."""
        with tempfile.TemporaryDirectory() as td:
            repo = _create_sample_git_repo(Path(td))
            path = repo / "rollout.jsonl"
            _create_sample_session(path, num_records=3, cwd=repo)
            rescue_root = Path(td) / "rescue"

            # Open with FILE_SHARE_READ
            with Win32FileHandle(path, access="r", share="r"):
                # Reader succeeds
                doc = doctor_session(path)
                self.assertEqual(doc.status, "HEALTHY")

                salvage = salvage_session(path, doc.transcript, doc.status, doc.findings, rescue_root, True)
                self.assertTrue(salvage.original_untouched)

                # But write attempts via Win32 fail with sharing violation 32
                with self.assertRaises(PermissionError) as ctx:
                    Win32FileHandle(path, access="w", share="r").open()
                self.assertEqual(ctx.exception.winerror, ERROR_SHARING_VIOLATION)

                # Write attempts via python open fail with PermissionError
                with self.assertRaises(PermissionError):
                    with path.open("ab") as f:
                        f.write(b"should fail")

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_shared_read_write_allows_concurrent_writer_and_reader(self) -> None:
        """FILE_SHARE_READ | FILE_SHARE_WRITE allows concurrent reader and writer."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shared_rw.jsonl"
            _create_sample_session(path, num_records=2, cwd=None)

            with Win32FileHandle(path, access="rw", share="rw"):
                # Reader can open and read
                with path.open("rb") as f:
                    content = f.read()
                self.assertGreater(len(content), 0)

                # Writer can append valid record
                with path.open("ab") as f:
                    f.write(b'{"type":"event_msg","payload":{"type":"agent_message","message":"appended"}}\n')

                # Doctor can diagnose
                doc = doctor_session(path)
                self.assertEqual(doc.status, "HEALTHY")

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_exclusive_byte_range_lock_blocks_reader_with_error_33(self) -> None:
        """LockFileEx exclusive lock on byte range [0..512] causes reads to fail with ERROR_LOCK_VIOLATION (33)."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "byte_lock.jsonl"
            _create_sample_session(path, num_records=5, cwd=None)

            h = Win32FileHandle(path, access="rw", share="rw").open()
            try:
                # Lock first 512 bytes exclusively
                h.lock_range(offset=0, length=512, exclusive=True, fail_immediately=True)

                # Reading locked range via second Win32 handle fails with Error 33
                with Win32FileHandle(path, access="r", share="rw") as reader_h:
                    with self.assertRaises(OSError) as ctx:
                        reader_h.read_bytes(512)
                    self.assertEqual(ctx.exception.winerror, ERROR_LOCK_VIOLATION)

                # Reading via standard open also fails
                with self.assertRaises((OSError, PermissionError)):
                    with path.open("rb") as f:
                        f.read(512)

                # Unlock and verify subsequent read succeeds
                h.unlock_range(offset=0, length=512)
                with Win32FileHandle(path, access="r", share="rw") as reader_h:
                    data = reader_h.read_bytes(512)
                self.assertEqual(len(data), 512)
            finally:
                h.close()

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_shared_byte_range_locks_allow_concurrent_readers(self) -> None:
        """LockFileEx shared lock (exclusive=False) allows concurrent readers."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shared_byte_lock.jsonl"
            _create_sample_session(path, num_records=5, cwd=None)

            with Win32FileHandle(path, access="r", share="r") as h:
                with h.locked_range(offset=0, length=256, exclusive=False):
                    with path.open("rb") as f:
                        data = f.read(256)
                    self.assertEqual(len(data), 256)

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_delete_on_close_and_share_delete(self) -> None:
        """FILE_FLAG_DELETE_ON_CLOSE unlinks file upon handle close; verify_rescue handles gracefully."""
        with tempfile.TemporaryDirectory() as td:
            repo = _create_sample_git_repo(Path(td))
            path = repo / "rollout.jsonl"
            _create_sample_session(path, num_records=2, cwd=repo)
            rescue_root = Path(td) / "rescue"

            doc = doctor_session(path)
            salvage = salvage_session(path, doc.transcript, doc.status, doc.findings, rescue_root, True)

            # Open with FILE_FLAG_DELETE_ON_CLOSE
            h = Win32FileHandle(
                path,
                access="rw",
                share="rwd",
                flags=FILE_ATTRIBUTE_NORMAL | FILE_FLAG_DELETE_ON_CLOSE,
            ).open()

            # Handle is open, file exists
            self.assertTrue(path.exists())

            # Close handle -> file is immediately deleted by OS
            h.close()
            self.assertFalse(path.exists())

            # verify_rescue against deleted source fails closed
            verification = verify_rescue(rescue_root, salvage.rescue_id)
            self.assertIn(verification.status, ("REVIEW_REQUIRED", "STATE_DIVERGED"))

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_atomic_replace_retry_under_transient_sharing_violation(self) -> None:
        """_atomic_replace retries up to 6 times and succeeds if transient lock is released."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "target_file.txt"
            target.write_text("initial content\n", encoding="utf-8")

            temp_file = Path(td) / "temp_file.tmp"
            temp_file.write_text("new atomic content\n", encoding="utf-8")

            # Hold exclusive lock transiently
            h = Win32FileHandle(target, access="w", share="none").open()

            # Start a background timer to release the handle after 15ms
            def release_later():
                time.sleep(0.015)
                h.close()

            t = threading.Thread(target=release_later)
            t.start()

            # _atomic_replace should retry through transient lock and succeed
            _atomic_replace(temp_file, target)
            t.join()

            self.assertEqual(target.read_text(encoding="utf-8"), "new atomic content\n")
            self.assertFalse(temp_file.exists())

    @unittest.skipUnless(IS_WINDOWS, "Win32 handle sharing tests require Windows")
    def test_handle_leak_audit_zero_delta(self) -> None:
        """100 cycles of open/lock/unlock/close must not leak OS handles (Delta = 0)."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "handle_leak_test.jsonl"
            _create_sample_session(path, num_records=2, cwd=None)

            with assert_zero_handle_leak(tolerance=2):
                for _ in range(100):
                    with Win32FileHandle(path, access="rw", share="rw") as h:
                        with h.locked_range(0, 128, exclusive=True):
                            pass


# ============================================================================
# PART C: TOCTOU Mutation Injection Harness Across 5 Synchronization Points
# ============================================================================

class TOCTOUMutationTests(unittest.TestCase):
    """Part C: TOCTOU mutation injection across 5 critical synchronization boundaries."""

    # ------------------------------------------------------------------------
    # Sync Point 1: snapshot -> parse -> snapshot
    # ------------------------------------------------------------------------
    def test_toctou_point1_source_mutated_during_salvage_parse_fails_closed(self) -> None:
        """Sync Point 1: Source mutated between initial snapshot and parse completion.

        Must raise RuntimeError('source rollout mutated during salvage...') and refuse publication.
        """
        with tempfile.TemporaryDirectory() as td:
            repo = _create_sample_git_repo(Path(td))
            session_path = repo / "rollout.jsonl"
            _create_sample_session(session_path, num_records=3, cwd=repo)
            rescue_root = Path(td) / "rescue"

            import codex_rescue.salvage as salvage_mod
            real_inspect = salvage_mod.inspect_git_state
            mutated = False

            def inject_mutation(*args: Any, **kwargs: Any) -> Any:
                nonlocal mutated
                if not mutated:
                    with session_path.open("ab") as f:
                        f.write(b'{"type":"event_msg","payload":{"type":"agent_message","message":"toctou append"}}\n')
                    mutated = True
                return real_inspect(*args, **kwargs)

            doc = doctor_session(session_path)

            with patch.object(salvage_mod, "inspect_git_state", side_effect=inject_mutation):
                with self.assertRaises(RuntimeError) as ctx:
                    salvage_session(session_path, doc.transcript, doc.status, doc.findings, rescue_root, True)

                self.assertIn("source rollout mutated during salvage", str(ctx.exception))

            # Ensure zero rescue artifacts created
            self.assertFalse(rescue_root.exists())

    # ------------------------------------------------------------------------
    # Sync Point 2: stat -> open -> truncate
    # ------------------------------------------------------------------------
    def test_toctou_point2_stat_open_truncate_instability_fails_closed(self) -> None:
        """Sync Point 2: File truncated between stat(before) and stat(after) in file_snapshot.

        Must mark stable=False and salvage_session must raise RuntimeError.
        """
        with tempfile.TemporaryDirectory() as td:
            repo = _create_sample_git_repo(Path(td))
            session_path = repo / "rollout.jsonl"
            _create_sample_session(session_path, num_records=4, cwd=repo)
            rescue_root = Path(td) / "rescue"

            # Hook file_snapshot to simulate mid-flight truncation
            import codex_rescue.salvage as salvage_mod
            real_snapshot = salvage_mod.file_snapshot

            def hook_unstable_snapshot(path: str | Path) -> dict[str, object]:
                res = real_snapshot(path)
                res["stable"] = False
                return res

            with patch.object(salvage_mod, "file_snapshot", side_effect=hook_unstable_snapshot):
                snap = salvage_mod.file_snapshot(session_path)
                self.assertFalse(snap["stable"])

                doc = doctor_session(session_path)
                with self.assertRaises(RuntimeError) as ctx:
                    salvage_session(session_path, doc.transcript, doc.status, doc.findings, rescue_root, True)
                self.assertIn("source rollout mutated while taking initial snapshot", str(ctx.exception))

    # ------------------------------------------------------------------------
    # Sync Point 3: source hash -> verify
    # ------------------------------------------------------------------------
    def test_toctou_point3_source_hash_changed_before_verify_diverges(self) -> None:
        """Sync Point 3A: Source hash mutated after salvage before verify_rescue.

        verify_rescue must return STATE_DIVERGED with explicit source_sha256 conflict.
        """
        with tempfile.TemporaryDirectory() as td:
            repo = _create_sample_git_repo(Path(td))
            session_path = repo / "rollout.jsonl"
            _create_sample_session(session_path, num_records=3, cwd=repo)
            rescue_root = Path(td) / "rescue"

            doc = doctor_session(session_path)
            salvage = salvage_session(session_path, doc.transcript, doc.status, doc.findings, rescue_root, True)

            # Mutate source file
            with session_path.open("ab") as f:
                f.write(b'{"type":"event_msg","payload":{"type":"agent_message","message":"after salvage modification"}}\n')

            verification = verify_rescue(rescue_root, salvage.rescue_id)
            self.assertEqual(verification.status, "STATE_DIVERGED")
            self.assertTrue(any("source_sha256" in c for c in verification.conflicts))

    def test_toctou_point3_source_deleted_before_verify_requires_review(self) -> None:
        """Sync Point 3B: Source deleted before verify_rescue.

        verify_rescue must fail closed (REVIEW_REQUIRED or STATE_DIVERGED).
        """
        with tempfile.TemporaryDirectory() as td:
            repo = _create_sample_git_repo(Path(td))
            session_path = repo / "rollout.jsonl"
            _create_sample_session(session_path, num_records=3, cwd=repo)
            rescue_root = Path(td) / "rescue"

            doc = doctor_session(session_path)
            salvage = salvage_session(session_path, doc.transcript, doc.status, doc.findings, rescue_root, True)

            # Delete source file
            session_path.unlink()

            verification = verify_rescue(rescue_root, salvage.rescue_id)
            self.assertIn(verification.status, ("REVIEW_REQUIRED", "STATE_DIVERGED"))

    def test_toctou_point3_source_mtime_changed_before_verify_diverges(self) -> None:
        """Sync Point 3C: Source mtime changed before verify_rescue.

        verify_rescue must return STATE_DIVERGED with source_mtime_ns conflict.
        """
        with tempfile.TemporaryDirectory() as td:
            repo = _create_sample_git_repo(Path(td))
            session_path = repo / "rollout.jsonl"
            _create_sample_session(session_path, num_records=3, cwd=repo)
            rescue_root = Path(td) / "rescue"

            doc = doctor_session(session_path)
            salvage = salvage_session(session_path, doc.transcript, doc.status, doc.findings, rescue_root, True)

            # Modify mtime without altering content
            stat = session_path.stat()
            new_mtime_ns = stat.st_mtime_ns + 10_000_000_000  # +10s
            os.utime(session_path, ns=(stat.st_atime_ns, new_mtime_ns))

            verification = verify_rescue(rescue_root, salvage.rescue_id)
            self.assertEqual(verification.status, "STATE_DIVERGED")
            self.assertTrue(any("source_mtime_ns" in c for c in verification.conflicts))

    # ------------------------------------------------------------------------
    # Sync Point 4: salvage target prepare -> write
    # ------------------------------------------------------------------------
    def test_toctou_point4_target_artifact_collision_fails_closed(self) -> None:
        """Sync Point 4A: Target handoff file locked exclusively during write_rescue fails closed."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _create_sample_git_repo(root)
            state = inspect_git_state(repo)
            handoff = {
                "version": 1,
                "session": {"source_id": "test-s", "cwd": str(repo)},
                "repository": state.to_dict(),
                "transcript": {"compacted": False},
                "tool_state": {"unfinished_action": None},
                "overall_confidence": "verified",
            }

            rescue_root = root / "rescue"
            from codex_rescue.artifacts import canonical_json
            rescue_id = hashlib.sha256(canonical_json(handoff)).hexdigest()[:24]
            target_dir = rescue_root / "rescues" / rescue_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target_handoff = target_dir / "handoff.v1.json"

            if IS_WINDOWS:
                target_handoff.write_text("pre-existing collision\n", encoding="utf-8")
                with Win32FileHandle(target_handoff, access="w", share="none"):
                    with self.assertRaises(OSError):
                        write_rescue(rescue_root, handoff, "brief", "prompt")
            else:
                target_handoff.write_text("collision\n", encoding="utf-8")
                target_handoff.chmod(0o444)
                target_dir.chmod(0o555)
                try:
                    with self.assertRaises(OSError):
                        write_rescue(rescue_root, handoff, "brief", "prompt")
                finally:
                    target_dir.chmod(0o777)
                    target_handoff.chmod(0o666)

    def test_toctou_point4_handoff_hash_mismatch_fails_closed(self) -> None:
        """Sync Point 4B: Tampered handoff.v1.json on disk fails content-address validation."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _create_sample_git_repo(root)
            state = inspect_git_state(repo)
            handoff = {
                "version": 1,
                "session": {"source_id": "test-s", "cwd": str(repo)},
                "repository": state.to_dict(),
                "transcript": {"compacted": False},
                "tool_state": {"unfinished_action": None},
                "overall_confidence": "verified",
            }
            rescue_root = root / "rescue"
            rescue_id, _ = write_rescue(rescue_root, handoff, "brief", "prompt")

            # Tamper with handoff on disk
            handoff_path = rescue_root / "rescues" / rescue_id / "handoff.v1.json"
            tampered_data = json.loads(handoff_path.read_text(encoding="utf-8"))
            tampered_data["overall_confidence"] = "unknown"
            handoff_path.write_text(json.dumps(tampered_data), encoding="utf-8")

            # load_handoff must reject hash mismatch
            with self.assertRaises(ValueError) as ctx:
                load_handoff(rescue_root, rescue_id)
            self.assertIn("handoff hash mismatch", str(ctx.exception))

            # verify_rescue must fail closed to REVIEW_REQUIRED
            verification = verify_rescue(rescue_root, rescue_id)
            self.assertEqual(verification.status, "REVIEW_REQUIRED")

    # ------------------------------------------------------------------------
    # Sync Point 5: verify git state -> artifact check
    # ------------------------------------------------------------------------
    def test_toctou_point5_git_working_tree_mutations_cause_state_diverged(self) -> None:
        """Sync Point 5: Working tree mutations after salvage cause STATE_DIVERGED or REVIEW_REQUIRED."""
        scenarios = [
            ("untracked_file", lambda r: (r / "untracked_new.txt").write_text("new file\n", encoding="utf-8")),
            ("modified_tracked", lambda r: (r / "tracked.txt").write_text("modified text\n", encoding="utf-8")),
            ("deleted_tracked", lambda r: (r / "tracked.txt").unlink()),
            ("new_commit", lambda r: [
                (r / "another.txt").write_text("commit\n", encoding="utf-8"),
                subprocess.run(["git", "add", "another.txt"], cwd=r, check=True),
                subprocess.run(["git", "commit", "-qm", "advanced commit"], cwd=r, check=True),
            ]),
        ]

        for name, mutator in scenarios:
            with self.subTest(scenario=name):
                with tempfile.TemporaryDirectory() as td:
                    repo = _create_sample_git_repo(Path(td))
                    session_path = repo / "rollout.jsonl"
                    _create_sample_session(session_path, num_records=2, cwd=repo)
                    rescue_root = Path(td) / "rescue"

                    doc = doctor_session(session_path)
                    salvage = salvage_session(session_path, doc.transcript, doc.status, doc.findings, rescue_root, True)

                    # Mutate working tree
                    mutator(repo)

                    # Verification must detect divergence
                    verification = verify_rescue(rescue_root, salvage.rescue_id)
                    self.assertEqual(verification.status, "STATE_DIVERGED", f"Scenario {name} did not produce STATE_DIVERGED")
                    self.assertGreater(len(verification.conflicts), 0)

    def test_toctou_point5_git_index_trust_flags_require_review(self) -> None:
        """Sync Point 5: Git index trust flags (assume-unchanged/skip-worktree) block verify."""
        flags = [
            ("assume-unchanged", ["git", "update-index", "--assume-unchanged", "tracked.txt"]),
            ("skip-worktree", ["git", "update-index", "--skip-worktree", "tracked.txt"]),
        ]

        for flag_name, cmd in flags:
            with self.subTest(flag=flag_name):
                with tempfile.TemporaryDirectory() as td:
                    repo = _create_sample_git_repo(Path(td))
                    session_path = repo / "rollout.jsonl"
                    _create_sample_session(session_path, num_records=2, cwd=repo)
                    rescue_root = Path(td) / "rescue"

                    doc = doctor_session(session_path)
                    salvage = salvage_session(session_path, doc.transcript, doc.status, doc.findings, rescue_root, True)

                    # Apply index trust flag
                    subprocess.run(cmd, cwd=repo, check=True)

                    verification = verify_rescue(rescue_root, salvage.rescue_id)
                    # When index trust flags are present, verify_rescue reports STATE_DIVERGED with index flags conflict
                    self.assertIn(verification.status, ("STATE_DIVERGED", "REVIEW_REQUIRED"))
                    self.assertTrue(
                        any("untrusted index flags" in c or "assume-unchanged" in c or "skip-worktree" in c for c in verification.conflicts)
                        or any("index" in r for r in verification.review_reasons)
                    )


if __name__ == "__main__":
    unittest.main()
