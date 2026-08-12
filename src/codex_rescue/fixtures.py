from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any


def _line(record: dict[str, Any]) -> bytes:
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _base_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "fixture@example.com")
    _git(path, "config", "user.name", "Fixture")
    (path / "app.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "app.txt")
    _git(path, "commit", "-qm", "base")


def _meta(session_id: str, cwd: Path) -> dict[str, Any]:
    return {
        "timestamp": "2026-08-12T00:00:00Z",
        "type": "session_meta",
        "payload": {"id": session_id, "session_id": session_id, "cwd": str(cwd), "cli_version": "0.147.0"},
    }


def generate_fixtures(root: str | Path) -> None:
    root = Path(root)
    if root.exists():
        def remove_readonly(function, path, _excinfo):
            os.chmod(path, stat.S_IWRITE)
            function(path)

        shutil.rmtree(root, onerror=remove_readonly)
    root.mkdir(parents=True)

    specs: list[tuple[str, str]] = [
        ("kill_apply_patch", "UNFINISHED_TOOL_CALL"),
        ("kill_shell_before_result", "UNFINISHED_TOOL_CALL"),
        ("oversized_payload", "OVERSIZED_PAYLOAD"),
        ("malformed_jsonl", "MALFORMED_RECORD"),
        ("lost_tail_after_compaction", "COMPACTION_STATE_LOSS"),
    ]
    for name, expected in specs:
        fixture = root / name
        repo_before = fixture / "repo_before"
        repo_actual = fixture / "repo_actual"
        source_dir = fixture / "source_session"
        _base_repo(repo_before)
        shutil.copytree(repo_before, repo_actual)
        source_dir.mkdir(parents=True)
        session_id = f"fixture-{name}"
        session = source_dir / f"rollout-{session_id}.jsonl"
        records = [
            _meta(session_id, repo_actual),
            {"timestamp": "2026-08-12T00:00:01Z", "type": "event_msg", "payload": {"type": "user_message", "message": f"fixture {name}"}},
        ]
        raw = b"".join(_line(record) for record in records)

        if name == "kill_apply_patch":
            (repo_actual / "app.txt").write_text("base\npartial patch\n", encoding="utf-8")
            raw += _line({"type": "response_item", "payload": {"type": "function_call", "name": "apply_patch", "call_id": "call-patch", "arguments": "*** Begin Patch"}})
        elif name == "kill_shell_before_result":
            (repo_actual / "generated.txt").write_text("side effect exists\n", encoding="utf-8")
            raw += _line({"type": "response_item", "payload": {"type": "function_call", "name": "shell_command", "call_id": "call-shell", "arguments": json.dumps({"command": "python script.py"})}})
        elif name == "oversized_payload":
            raw += _line({"type": "response_item", "payload": {"type": "input_image", "image_url": "data:image/png;base64," + ("A" * 1_200_000)}})
            raw += _line({"type": "event_msg", "payload": {"type": "agent_message", "message": "continue with app.txt"}})
        elif name == "malformed_jsonl":
            raw += _line({"type": "event_msg", "payload": {"type": "agent_message", "message": "valid prefix"}})
            raw += b'{"type":"response_item","payload":{"type":"function_call","arguments":"bad\x00'
        elif name == "lost_tail_after_compaction":
            (repo_actual / "app.txt").write_text("base\nverified post-compact edit\n", encoding="utf-8")
            raw += _line({"type": "response_item", "payload": {"type": "function_call", "name": "shell_command", "call_id": "test-1", "arguments": json.dumps({"command": "pytest"})}})
            raw += _line({"type": "response_item", "payload": {"type": "function_call_output", "call_id": "test-1", "output": {"exit_code": 0, "command": "pytest"}}})
            raw += _line({"type": "compacted", "payload": {"message": "generic summary without operational tail", "replacement_history": [], "window_number": 1, "window_id": "w1"}})

        session.write_bytes(raw)
        (fixture / "expected.json").write_text(json.dumps({"doctor": expected}, indent=2) + "\n", encoding="utf-8")
        (fixture / "README.md").write_text(
            f"# {name}\n\nSynthetic fixture matching the Codex 0.147.0 JSONL envelope. Expected primary class: `{expected}`.\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    generate_fixtures(parser.parse_args().root)
