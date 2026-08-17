"""Shared E2E test utilities, fixture generators, and mock environments.

Provides:
- SyntheticRolloutGenerator: Deterministic JSONL generation for standard and adversarial events.
- TempSessionWorkspace: Isolated scratch workspaces mimicking ~/.codex/sessions.
- MockGitRepo: Isolated Git repositories with branch, staged/unstaged, index-flag, and detached-head control.
- Win32LockContext: Platform-aware Win32 handle sharing and byte-range locking.
- AsyncRolloutWriter: Concurrent background streaming / mutation injector.
- Cryptographic tree hashing and CLI runners.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Ensure src/ is in sys.path
_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


def _safe_rmtree(path: Path | str) -> None:
    """Remove a directory tree safely on Windows even if read-only files exist."""
    p = Path(path)
    if not p.exists():
        return

    def _onerror(func: Callable[..., Any], file_path: str, excinfo: Any) -> None:
        try:
            os.chmod(file_path, stat.S_IWRITE)
            func(file_path)
        except Exception:
            pass

    shutil.rmtree(p, onerror=_onerror)


def compute_tree_sha256(root_dir: Path | str) -> str:
    """Compute a deterministic SHA-256 tree digest across all files in a directory."""
    root = Path(root_dir).resolve()
    if not root.exists():
        return ""
    hasher = hashlib.sha256()
    for dirpath, _, filenames in sorted(os.walk(root)):
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            rel_path = fpath.relative_to(root).as_posix()
            hasher.update(rel_path.encode("utf-8"))
            try:
                content = fpath.read_bytes()
                hasher.update(hashlib.sha256(content).digest())
            except OSError:
                pass
    return hasher.hexdigest()


class SyntheticRolloutGenerator:
    """Generator for syntactically valid and adversarial Codex JSONL streams."""

    @staticmethod
    def make_session_meta(
        session_id: str = "sess-e2e-001",
        cwd: str = "C:/test/repo",
        originator: str = "codex_cli",
        cli_version: str = "0.1.0a5",
        timestamp: str = "2026-08-14T20:00:00.000Z",
    ) -> dict[str, Any]:
        return {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "session_id": session_id,
                "cwd": cwd,
                "originator": originator,
                "cli_version": cli_version,
                "timestamp": timestamp,
            },
        }

    @staticmethod
    def make_user_msg(content: str = "Please fix the failing tests.") -> dict[str, Any]:
        return {
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": content,
            },
        }

    @staticmethod
    def make_agent_msg(content: str = "I will inspect the workspace.") -> dict[str, Any]:
        return {
            "type": "response_item",
            "payload": {
                "type": "agent_message",
                "message": content,
            },
        }

    @staticmethod
    def make_func_call(
        call_id: str = "call_001",
        name: str = "shell_command",
        arguments: str | dict[str, Any] = '{"cmd": "pytest"}',
    ) -> dict[str, Any]:
        args_val = json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
        return {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": args_val,
            },
        }

    @staticmethod
    def make_func_output(
        call_id: str = "call_001",
        output: str = "1 passed in 0.05s",
    ) -> dict[str, Any]:
        return {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            },
        }

    @staticmethod
    def make_custom_call(
        call_id: str = "cust_001",
        name: str = "custom_linter",
        arguments: str | dict[str, Any] = '{"rules": ["all"]}',
    ) -> dict[str, Any]:
        args_val = json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
        return {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": call_id,
                "name": name,
                "arguments": args_val,
            },
        }

    @staticmethod
    def make_custom_output(
        call_id: str = "cust_001",
        output: str = "All rules passed.",
    ) -> dict[str, Any]:
        return {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": call_id,
                "output": output,
            },
        }

    @staticmethod
    def make_search_call(
        call_id: str = "srch_001",
        query: str = "def solve",
    ) -> dict[str, Any]:
        return {
            "type": "response_item",
            "payload": {
                "type": "web_search_call",
                "id": call_id,
                "query": query,
            },
        }

    @staticmethod
    def make_search_output(
        call_id: str = "srch_001",
        output: str = "found matches",
    ) -> dict[str, Any]:
        return {
            "type": "response_item",
            "payload": {
                "type": "web_search_call_output",
                "id": call_id,
                "output": output,
            },
        }

    @staticmethod
    def make_reasoning(content: str = "Need inspect state.") -> dict[str, Any]:
        return {"type": "response_item", "payload": {"type": "reasoning", "summary": [{"type": "summary_text", "text": content}]}}

    @staticmethod
    def make_compaction(content: str = "summary") -> dict[str, Any]:
        return {"type": "compacted", "payload": {"message": content}}

    @staticmethod
    def make_turn_context(cwd: str = "C:/test/repo") -> dict[str, Any]:
        return {"type": "turn_context", "payload": {"cwd": cwd, "approval_policy": "never", "sandbox_policy": {"type": "read-only"}}}

    @staticmethod
    def make_event(event_type: str, **payload: Any) -> dict[str, Any]:
        return {"type": "event_msg", "payload": {"type": event_type, **payload}}

    @staticmethod
    def make_response_item(item_type: str, **payload: Any) -> dict[str, Any]:
        return {"type": "response_item", "payload": {"type": item_type, **payload}}

    @staticmethod
    def make_malformed_json() -> str:
        return '{"type":"event_msg","payload":'

    @staticmethod
    def write_jsonl(path: Path, records: list[dict[str, Any] | str], newline: str = "\n") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            for record in records:
                if isinstance(record, str):
                    handle.write(record)
                else:
                    handle.write(json.dumps(record, separators=(",", ":")))
                handle.write(newline)
        return path


class TempSessionWorkspace:
    """Temporary Codex home/session fixture."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> "TempSessionWorkspace":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.cleanup()

    def create_session(
        self,
        session_id: str,
        records: list[dict[str, Any] | str] | None = None,
        *,
        filename: str | None = None,
        newline: str = "\n",
    ) -> Path:
        if filename is None:
            filename = f"rollout-{session_id}.jsonl"
        path = self.sessions / filename
        if records is None:
            records = [SyntheticRolloutGenerator.make_session_meta(session_id=session_id)]
        return SyntheticRolloutGenerator.write_jsonl(path, records, newline=newline)


class MockGitRepo:
    """Minimal real Git repository used by E2E verification/salvage tests."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        subprocess.run(["git", "init"], cwd=self.root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.email", "codex-rescue@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Codex Rescue E2E"], cwd=self.root, check=True)
        (self.root / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "fixture"], cwd=self.root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def cleanup(self) -> None:
        _safe_rmtree(self.root)
        self._tmp.cleanup()

    def __enter__(self) -> "MockGitRepo":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.cleanup()

    def run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.root, text=True, capture_output=True, check=check)

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit_all(self, message: str) -> str:
        self.run_git("add", "-A")
        self.run_git("commit", "-m", message)
        return self.run_git("rev-parse", "HEAD").stdout.strip()


class Win32LockContext:
    """Hold a Windows file handle/lock for sharing-violation tests."""

    def __init__(self, path: Path, *, deny_write: bool = True, byte_lock: bool = False) -> None:
        self.path = Path(path)
        self.deny_write = deny_write
        self.byte_lock = byte_lock
        self.handle: int | None = None

    def __enter__(self) -> "Win32LockContext":
        if os.name != "nt":
            return self
        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        OPEN_EXISTING = 3
        share = FILE_SHARE_READ if self.deny_write else (FILE_SHARE_READ | FILE_SHARE_WRITE)
        CreateFileW = ctypes.windll.kernel32.CreateFileW
        CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        CreateFileW.restype = wintypes.HANDLE
        handle = CreateFileW(str(self.path), GENERIC_READ, share, None, OPEN_EXISTING, 0, None)
        if handle == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "CreateFileW failed")
        self.handle = int(handle)
        if self.byte_lock:
            overlapped = wintypes.OVERLAPPED()
            ok = ctypes.windll.kernel32.LockFileEx(self.handle, 0x00000002, 0, 1, 0, ctypes.byref(overlapped))
            if not ok:
                raise OSError(ctypes.get_last_error(), "LockFileEx failed")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if os.name == "nt" and self.handle is not None:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


class AsyncRolloutWriter:
    """Append records asynchronously to emulate an actively-written rollout."""

    def __init__(self, path: Path, records: list[dict[str, Any]], delay: float = 0.01) -> None:
        self.path = Path(path)
        self.records = records
        self.delay = delay
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        def _write() -> None:
            with self.path.open("a", encoding="utf-8") as handle:
                for record in self.records:
                    time.sleep(self.delay)
                    handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass

        self.thread = threading.Thread(target=_write, daemon=True)
        self.thread.start()

    def join(self, timeout: float = 5.0) -> None:
        if self.thread is not None:
            self.thread.join(timeout)


def run_cli(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    merged_env.setdefault("PYTHONPATH", str(_SRC_DIR))
    return subprocess.run([sys.executable, "-m", "codex_rescue.cli", *args], cwd=cwd, env=merged_env, text=True, capture_output=True)
