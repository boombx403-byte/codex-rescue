from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


class GitStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitState:
    cwd: str
    root: str
    worktree: str
    branch: str | None
    head_sha: str
    staged: tuple[str, ...]
    modified: tuple[str, ...]
    untracked: tuple[str, ...]
    diff_hash: str

    @property
    def changed_files(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.staged + self.modified + self.untracked)))

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["changed_files"] = list(self.changed_files)
        return data


def _git(cwd: Path, *args: str, binary: bool = False, check: bool = True) -> bytes | str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=not binary,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise GitStateError(detail.strip()) from exc
    return result.stdout


def _split_z(raw: str) -> tuple[str, ...]:
    return tuple(sorted(item for item in raw.split("\0") if item))


def _untracked_manifest(root: Path, paths: tuple[str, ...]) -> bytes:
    manifest: list[dict[str, object]] = []
    for rel in paths:
        path = root / rel
        if path.is_symlink():
            content = str(path.readlink()).encode("utf-8", "surrogateescape")
            kind = "symlink"
        elif path.is_file():
            content = path.read_bytes()
            kind = "file"
        else:
            content = b""
            kind = "other"
        manifest.append(
            {
                "path": rel.replace("\\", "/"),
                "kind": kind,
                "size": len(content),
                "mode": path.lstat().st_mode,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


def inspect_git_state(cwd: str | Path) -> GitState:
    cwd_path = Path(cwd).resolve()
    if not cwd_path.exists():
        raise GitStateError(f"cwd does not exist: {cwd_path}")
    root = Path(str(_git(cwd_path, "rev-parse", "--show-toplevel")).strip()).resolve()
    worktree = str(_git(cwd_path, "rev-parse", "--show-toplevel")).strip()
    head = str(_git(root, "rev-parse", "HEAD")).strip()
    branch_raw = str(_git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)).strip()
    branch = branch_raw or None
    staged = _split_z(str(_git(root, "diff", "--cached", "--name-only", "-z")))
    modified = _split_z(str(_git(root, "diff", "--name-only", "-z")))
    untracked = _split_z(str(_git(root, "ls-files", "--others", "--exclude-standard", "-z")))

    digest = hashlib.sha256()
    digest.update(b"codex-rescue-diff-v1\0")
    digest.update(bytes(_git(root, "diff", "--binary", binary=True)))
    digest.update(b"\0cached\0")
    digest.update(bytes(_git(root, "diff", "--cached", "--binary", binary=True)))
    digest.update(b"\0untracked\0")
    digest.update(_untracked_manifest(root, untracked))

    return GitState(
        cwd=str(cwd_path),
        root=str(root),
        worktree=worktree,
        branch=branch,
        head_sha=head,
        staged=staged,
        modified=modified,
        untracked=untracked,
        diff_hash=digest.hexdigest(),
    )


def compare_git_state(expected: dict[str, object], actual: GitState) -> list[str]:
    conflicts: list[str] = []
    comparisons = {
        "root": actual.root,
        "worktree": actual.worktree,
        "head_sha": actual.head_sha,
        "diff_hash": actual.diff_hash,
    }
    for key, actual_value in comparisons.items():
        expected_value = expected.get(key)
        if expected_value and expected_value != actual_value:
            conflicts.append(f"{key}: expected {expected_value}, actual {actual_value}")
    expected_files = set(expected.get("changed_files") or [])
    actual_files = set(actual.changed_files)
    if expected_files and expected_files != actual_files:
        missing = sorted(expected_files - actual_files)
        added = sorted(actual_files - expected_files)
        conflicts.append(f"changed_files differ: missing={missing}, added={added}")
    return conflicts
