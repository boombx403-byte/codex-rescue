from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .salvage import salvage_session
from .verify import verify_rescue


def _json(data: object) -> None:
    print(json.dumps({"schema_version": 1, "data": data}, indent=2, ensure_ascii=False, sort_keys=True))


def _doctor(path: Path, oversized_threshold: int = 1_000_000):
    from .doctor import doctor_session

    result = doctor_session(path, oversized_threshold=oversized_threshold)
    return result


def _to_dict(value: object) -> dict[str, object]:
    if hasattr(value, "to_dict"):
        return value.to_dict()  # type: ignore[no-any-return,attr-defined]
    if isinstance(value, dict):
        return value
    return value.__dict__.copy()  # type: ignore[attr-defined]


def _parsed_from_doctor(result: object):
    for name in ("transcript", "parse_result", "parsed"):
        parsed = getattr(result, name, None)
        if parsed is not None:
            return parsed
    if isinstance(result, dict):
        for name in ("transcript", "parse_result", "parsed"):
            if result.get(name) is not None:
                return result[name]
    raise RuntimeError("doctor result does not expose transcript parse result")


def _print_doctor(result: object) -> None:
    data = _to_dict(result)
    print(f"Doctor: {data.get('status', 'UNKNOWN_CORRUPTION')}")
    session = data.get("session")
    if session:
        print(f"Session: {session}")
    findings = list(data.get("findings") or [])
    if findings:
        print(f"Findings: {', '.join(str(item) for item in findings)}")
    repository = data.get("repository")
    if isinstance(repository, dict):
        cwd = repository.get("cwd")
        head = repository.get("head_sha")
        if cwd or head:
            print(f"Repository: {cwd or 'unknown'} (HEAD {head or 'unknown'})")


def _print_salvage(result: object) -> None:
    data = _to_dict(result)
    print(f"Salvage: {data.get('rescue_id', 'unknown')}")
    untouched = data.get("original_untouched")
    print(f"Original session untouched: {'yes' if untouched else 'no'}")
    if data.get("rescue_dir"):
        print(f"Rescue directory: {data['rescue_dir']}")
    if data.get("continuation_command"):
        print(f"Continue: {data['continuation_command']}")


def _print_verify(result: object) -> None:
    data = _to_dict(result)
    print(f"Verify: {data.get('status', 'REVIEW_REQUIRED')}")
    conflicts = list(data.get("conflicts") or [])
    reasons = list(data.get("review_reasons") or [])
    for label, values in (("Conflict", conflicts), ("Review", reasons)):
        for value in values:
            print(f"{label}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-rescue")
    parser.add_argument("--version", action="version", version=f"codex-rescue {__version__}")
    subs = parser.add_subparsers(dest="command")

    sessions = subs.add_parser("sessions")
    sessions.add_argument("--codex-home", type=Path)
    sessions.add_argument("--limit", type=int, default=20)
    sessions.add_argument("--latest", action="store_true")
    sessions.add_argument("--json", action="store_true")

    doctor = subs.add_parser("doctor")
    doctor.add_argument("session", nargs="?", type=Path)
    doctor.add_argument("--latest", action="store_true")
    doctor.add_argument("--codex-home", type=Path)
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--oversized-threshold", type=int, default=1_000_000)

    salvage = subs.add_parser("salvage")
    salvage.add_argument("session", nargs="?", type=Path)
    salvage.add_argument("--latest", action="store_true")
    salvage.add_argument("--codex-home", type=Path)
    salvage.add_argument("--json", action="store_true")
    salvage.add_argument("--oversized-threshold", type=int, default=1_000_000)
    salvage.add_argument("--fork", action="store_true", required=True)
    salvage.add_argument("--rescue-root", type=Path, default=Path(".codex-rescue"))

    verify = subs.add_parser("verify")
    verify.add_argument("rescue_id")
    verify.add_argument("--rescue-root", type=Path, default=Path(".codex-rescue"))
    verify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command in (None, "sessions"):
        from .discovery import discover_sessions

        limit = 1 if getattr(args, "latest", False) else getattr(args, "limit", 20)
        summaries = discover_sessions(getattr(args, "codex_home", None), limit=limit)
        data = [item.to_dict() for item in summaries]
        if getattr(args, "json", False):
            _json(data)
        else:
            print("Recent Codex sessions\n")
            for index, item in enumerate(summaries, 1):
                print(f"{index}. {item.modified_at}  {item.status}")
                print(f"   repo: {item.repo or item.cwd or 'unknown'}")
                print(f"   prompt: {item.prompt_preview or 'unavailable'}")
                if item.reason:
                    print(f"   reason: {item.reason}")
        return 0
    if args.command == "doctor":
        if args.latest:
            from .discovery import resolve_latest
            args.session = resolve_latest(args.codex_home)
        if args.session is None:
            parser.error("doctor requires SESSION or --latest (no session discovered)")
        result = _doctor(args.session, args.oversized_threshold)
        if args.json:
            _json(_to_dict(result))
        else:
            _print_doctor(result)
        return 0
    if args.command == "salvage":
        if args.latest:
            from .discovery import resolve_latest
            args.session = resolve_latest(args.codex_home)
        if args.session is None:
            parser.error("salvage requires SESSION or --latest (no session discovered)")
        result = _doctor(args.session, args.oversized_threshold)
        data = _to_dict(result)
        status = str(data.get("status", "UNKNOWN_CORRUPTION"))
        findings = list(data.get("findings") or [status])
        salvage_result = salvage_session(
            args.session,
            _parsed_from_doctor(result),
            status,
            findings,
            args.rescue_root,
            args.fork,
        )
        if args.json:
            _json(salvage_result.to_dict())
        else:
            _print_salvage(salvage_result)
        return 0 if salvage_result.original_untouched else 2
    if args.command == "verify":
        result = verify_rescue(args.rescue_root, args.rescue_id)
        if args.json:
            _json(result.to_dict())
        else:
            _print_verify(result)
        return 0 if result.status == "SAFE_TO_CONTINUE" else 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
