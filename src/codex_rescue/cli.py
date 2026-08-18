from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .apply_plan import apply_recovery_plan
from .bundle import audit_bundle_file, generate_support_bundle
from .contracts import Envelope, ExitCode
from .diff import diff_session
from .doctor_batch import run_doctor_all, run_doctor_changed
from .explanations import get_explanation
from .graph import build_session_graph
from .plan import generate_recovery_plan
from .redact import sanitize_path
from .report import generate_html_report
from .salvage import salvage_session
from .schema_inspector import inspect_schemas
from .sessions_filter import filter_sessions
from .storage import analyze_storage
from .timeline import build_timeline
from .verify import verify_rescue
from .workspace import analyze_workspace
from .writer_inspector import inspect_writer

HEALTHY_EXPLANATION = (
    "HEALTHY means Codex Rescue found no recognized structural/persistence issue in the analyzed rollout. "
    "It does not validate Codex Desktop sidebar/index/Remote metadata, prove semantic completeness, "
    "or rule out every upstream Codex failure mode. "
    "Projection parity may be not-applicable when no compatible read-only state is available."
)


def _json(data: object, command: str = "", status: str = "SUCCESS", session: str | None = None) -> None:
    env = Envelope(
        tool_version="0.1.0a6.dev",
        command=command,
        status=status,
        session=session,
        data=data,
    )
    print(json.dumps(env.to_dict(), indent=2, ensure_ascii=False, sort_keys=True))


def _resolve_session(session_arg: Path | None, latest: bool, codex_home: Path | None) -> Path | None:
    if latest or session_arg is None:
        from .discovery_alpha5 import resolve_latest
        try:
            return resolve_latest(codex_home)
        except Exception:
            return None
    return session_arg


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-rescue", description="Codex Rescue Alpha6 Diagnostic & Recovery Toolkit")
    parser.add_argument("--version", action="version", version=f"codex-rescue {__version__}")
    subs = parser.add_subparsers(dest="command")

    sessions_p = subs.add_parser("sessions", help="List and filter sessions")
    sessions_p.add_argument("--codex-home", type=Path)
    sessions_p.add_argument("--limit", type=int, default=20)
    sessions_p.add_argument("--latest", action="store_true")
    sessions_p.add_argument("--orphans", action="store_true", help="Filter orphaned subagent sessions")
    sessions_p.add_argument("--unindexed", action="store_true", help="Filter rollouts unindexed in SQLite state DB")
    sessions_p.add_argument("--duplicates", action="store_true", help="Filter duplicate session ID collisions")
    sessions_p.add_argument("--json", action="store_true")

    doctor_p = subs.add_parser("doctor", help="Inspect session health and diagnostics")
    doctor_p.add_argument("session", nargs="?", type=Path)
    doctor_p.add_argument("--all", action="store_true", help="Batch analyze all discoverable sessions")
    doctor_p.add_argument("--changed", action="store_true", help="Incremental changed-only analysis using local cache")
    doctor_p.add_argument("--explain", action="store_true", help="Include structured explanations for findings")
    doctor_p.add_argument("--latest", action="store_true")
    doctor_p.add_argument("--codex-home", type=Path)
    doctor_p.add_argument("--json", action="store_true")
    doctor_p.add_argument("--oversized-threshold", type=int, default=1_000_000)

    explain_p = subs.add_parser("explain", help="Explain diagnostic finding codes")
    explain_p.add_argument("finding_code", help="Diagnostic finding code")
    explain_p.add_argument("--json", action="store_true")

    diff_p = subs.add_parser("diff", help="Compare persisted layers")
    diff_p.add_argument("session", nargs="?", type=Path)
    diff_p.add_argument("--latest", action="store_true")
    diff_p.add_argument("--codex-home", type=Path)
    diff_p.add_argument("--json", action="store_true")

    timeline_p = subs.add_parser("timeline", help="Generate privacy-safe forensic event timeline")
    timeline_p.add_argument("session", nargs="?", type=Path)
    timeline_p.add_argument("--latest", action="store_true")
    timeline_p.add_argument("--max-events", type=int, default=5000)
    timeline_p.add_argument("--json", action="store_true")

    graph_p = subs.add_parser("graph", help="Display subagent and parent-child session hierarchy")
    graph_p.add_argument("session", nargs="?", type=Path)
    graph_p.add_argument("--latest", action="store_true")
    graph_p.add_argument("--codex-home", type=Path)
    graph_p.add_argument("--json", action="store_true")

    storage_p = subs.add_parser("storage", help="Inspect session store storage footprint")
    storage_p.add_argument("--codex-home", type=Path)
    storage_p.add_argument("--limit", type=int, default=1000)
    storage_p.add_argument("--json", action="store_true")

    schema_p = subs.add_parser("schema", help="Inspect persisted schema generations and coverage")
    schema_p.add_argument("--codex-home", type=Path)
    schema_p.add_argument("--json", action="store_true")

    ws_p = subs.add_parser("workspace", help="Inspect saved vs current workspace environment")
    ws_p.add_argument("session", nargs="?", type=Path)
    ws_p.add_argument("--latest", action="store_true")
    ws_p.add_argument("--codex-home", type=Path)
    ws_p.add_argument("--json", action="store_true")

    writer_p = subs.add_parser("writer", help="Inspect active locks and writer ownership")
    writer_p.add_argument("session", nargs="?", type=Path)
    writer_p.add_argument("--latest", action="store_true")
    writer_p.add_argument("--codex-home", type=Path)
    writer_p.add_argument("--json", action="store_true")

    plan_p = subs.add_parser("plan", help="Generate structured recovery plan for session")
    plan_p.add_argument("session", nargs="?", type=Path)
    plan_p.add_argument("--latest", action="store_true")
    plan_p.add_argument("--codex-home", type=Path)
    plan_p.add_argument("--json", action="store_true")

    apply_p = subs.add_parser("apply-plan", help="Safely apply a generated recovery plan")
    apply_p.add_argument("plan", help="Path to recovery plan JSON or session file")
    apply_p.add_argument("--dry-run", action="store_true", help="Validate preconditions without mutating derived state")
    apply_p.add_argument("--backup-root", type=Path, default=Path(".codex-rescue/backups"))
    apply_p.add_argument("--codex-home", type=Path)
    apply_p.add_argument("--json", action="store_true")

    bundle_p = subs.add_parser("bundle", help="Generate sanitized diagnostic support bundle")
    bundle_p.add_argument("session", nargs="?", type=Path)
    bundle_p.add_argument("--latest", action="store_true")
    bundle_p.add_argument("--output", "-o", type=Path)
    bundle_p.add_argument("--codex-home", type=Path)
    bundle_p.add_argument("--json", action="store_true")

    redact_p = subs.add_parser("redact-check", help="Audit an artifact for secrets and privacy leaks")
    redact_p.add_argument("artifact", type=Path)
    redact_p.add_argument("--json", action="store_true")

    report_p = subs.add_parser("report", help="Generate offline HTML diagnostic report")
    report_p.add_argument("session", nargs="?", type=Path)
    report_p.add_argument("--latest", action="store_true")
    report_p.add_argument("--html", action="store_true", default=True)
    report_p.add_argument("--output", "-o", type=Path)
    report_p.add_argument("--codex-home", type=Path)
    report_p.add_argument("--json", action="store_true")

    salvage_p = subs.add_parser("salvage", help="Salvage durable history into clean fork")
    salvage_p.add_argument("session", nargs="?", type=Path)
    salvage_p.add_argument("--latest", action="store_true")
    salvage_p.add_argument("--codex-home", type=Path)
    salvage_p.add_argument("--json", action="store_true")
    salvage_p.add_argument("--oversized-threshold", type=int, default=1_000_000)
    salvage_p.add_argument("--fork", action="store_true", required=True)
    salvage_p.add_argument("--rescue-root", type=Path, default=Path(".codex-rescue"))

    verify_p = subs.add_parser("verify", help="Verify salvaged session before continuation")
    verify_p.add_argument("rescue_id")
    verify_p.add_argument("--rescue-root", type=Path, default=Path(".codex-rescue"))
    verify_p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command in (None, "sessions"):
        if getattr(args, "orphans", False) or getattr(args, "unindexed", False) or getattr(args, "duplicates", False):
            filtered = filter_sessions(
                getattr(args, "codex_home", None),
                orphans=getattr(args, "orphans", False),
                unindexed=getattr(args, "unindexed", False),
                duplicates=getattr(args, "duplicates", False),
            )
            data = [f.to_dict() for f in filtered]
            if getattr(args, "json", False):
                _json(data, command="sessions", status="SUCCESS")
            else:
                print(f"Filtered Sessions ({len(filtered)} matches)\n")
                for f in filtered:
                    print(f"[{f.category.upper()}] {f.session_id} ({f.size_bytes} bytes)")
                    print(f"  path: {f.session_path}")
                    print(f"  reason: {f.reason}")
            return int(ExitCode.SUCCESS)

        from .discovery_alpha5 import discover_sessions
        limit = 1 if getattr(args, "latest", False) else getattr(args, "limit", 20)
        summaries = discover_sessions(getattr(args, "codex_home", None), limit=limit)
        data = [item.to_dict() for item in summaries]
        if getattr(args, "json", False):
            _json(data, command="sessions", status="SUCCESS")
        else:
            print("Recent Codex sessions\n")
            for index, item in enumerate(summaries, 1):
                print(f"{index}. {item.modified_at}  {item.status}")
                print(f"   repo: {item.repo or item.cwd or 'unknown'}")
                print(f"   prompt: {item.prompt_preview or 'unavailable'}")
                if item.inventory_mismatch:
                    print(f"   inventory: {item.inventory_mismatch}")
                if item.reason:
                    print(f"   reason: {item.reason}")
        return int(ExitCode.SUCCESS)

    if args.command == "doctor":
        if args.all:
            summary = run_doctor_all(args.codex_home, oversized_threshold=args.oversized_threshold)
            if args.json:
                _json(summary.to_dict(), command="doctor --all", status="SUCCESS")
            else:
                print(summary.render_text())
            return int(ExitCode.SUCCESS if summary.scan_failures == 0 else ExitCode.WARNINGS_FOUND)

        if args.changed:
            summary = run_doctor_changed(args.codex_home, oversized_threshold=args.oversized_threshold)
            if args.json:
                _json(summary.to_dict(), command="doctor --changed", status="SUCCESS")
            else:
                print(summary.render_text())
            return int(ExitCode.SUCCESS if summary.scan_failures == 0 else ExitCode.WARNINGS_FOUND)

        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: doctor requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)

        from .doctor import doctor_session
        result = doctor_session(session_path, oversized_threshold=args.oversized_threshold)
        data = _to_dict(result)
        status = str(data.get("status", "UNKNOWN"))

        if args.explain:
            findings = list(data.get("findings") or [status])
            data["explanations"] = [get_explanation(f).to_dict() for f in findings]

        if args.json:
            _json(data, command="doctor", status=status, session=str(session_path.stem))
        else:
            print(f"Doctor: {status}")
            if data.get("session"):
                print(f"Session: {data['session']}")
            findings = list(data.get("findings") or [])
            if findings:
                print(f"Findings: {', '.join(str(f) for f in findings)}")
            if args.explain:
                print("\nFinding Explanations:")
                for f in findings:
                    exp = get_explanation(str(f))
                    print(f"\n--- {exp.finding_code} ---")
                    print(f"What happened: {exp.what_happened}")
                    print(f"Safe action:   {exp.safe_next_action}")

        if status == "HEALTHY":
            return int(ExitCode.SUCCESS)
        elif status in ("UNSUPPORTED", "OPAQUE"):
            return int(ExitCode.INCOMPLETE_OR_UNSUPPORTED)
        elif status in ("CORRUPT", "UNKNOWN_CORRUPTION", "UNREADABLE"):
            return int(ExitCode.ACTIONABLE_FINDINGS)
        return int(ExitCode.WARNINGS_FOUND)

    if args.command == "explain":
        exp = get_explanation(args.finding_code)
        if args.json:
            _json(exp.to_dict(), command="explain", status="SUCCESS")
        else:
            print(f"Finding Explanation: {exp.finding_code}\n")
            print(f"WHAT HAPPENED:            {exp.what_happened}")
            print(f"EVIDENCE USED:            {exp.evidence_used}")
            print(f"WHAT IS STILL HEALTHY:    {exp.what_is_still_healthy}")
            print(f"WHAT RESCUE CANNOT KNOW:  {exp.what_rescue_cannot_know}")
            print(f"RISK:                     {exp.risk}")
            print(f"SAFE NEXT ACTION:         {exp.safe_next_action}")
        return int(ExitCode.SUCCESS)

    if args.command == "diff":
        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: diff requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        diff_res = diff_session(session_path, codex_home=args.codex_home)
        if args.json:
            _json(diff_res.to_dict(), command="diff", status="SUCCESS" if diff_res.is_aligned else "WARNINGS", session=diff_res.session_id)
        else:
            print(f"Session State Diff: {diff_res.session_id}")
            print(f"Summary: {diff_res.summary}\n")
            if diff_res.divergences:
                for d in diff_res.divergences:
                    print(f"  * [{d.dimension}] {d.divergence_type}: {d.note}")
            else:
                print("  No divergences detected across persisted layers.")
        return int(ExitCode.SUCCESS if diff_res.is_aligned else ExitCode.WARNINGS_FOUND)

    if args.command == "timeline":
        session_path = _resolve_session(args.session, args.latest, None)
        if session_path is None or not Path(session_path).exists():
            print("Error: timeline requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        tl_res = build_timeline(session_path, max_events=args.max_events)
        if args.json:
            _json(tl_res.to_dict(), command="timeline", status="SUCCESS", session=tl_res.session_id)
        else:
            print(f"Forensic Timeline for Session: {tl_res.session_id} ({tl_res.total_events} events)\n")
            for e in tl_res.events:
                ts_str = f" [{e.timestamp}]" if e.timestamp else ""
                ord_str = f" (ord {e.ordinal})" if e.ordinal is not None else ""
                print(f"  {e.index:>4}. {e.event_type:<26}{ord_str}{ts_str} ({e.record_size}B)")
        return int(ExitCode.SUCCESS)

    if args.command == "graph":
        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: graph requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        g_res = build_session_graph(session_path, codex_home=args.codex_home)
        if args.json:
            _json(g_res.to_dict(), command="graph", status="SUCCESS", session=g_res.root_session_id)
        else:
            print(g_res.render_text())
        return int(ExitCode.SUCCESS)

    if args.command == "storage":
        st_res = analyze_storage(codex_home=args.codex_home, limit_sessions=args.limit)
        if args.json:
            _json(st_res.to_dict(), command="storage", status="SUCCESS")
        else:
            print(st_res.render_text())
        return int(ExitCode.SUCCESS)

    if args.command == "schema":
        sc_res = inspect_schemas(codex_home=args.codex_home)
        if args.json:
            _json(sc_res.to_dict(), command="schema", status=sc_res.status)
        else:
            print(sc_res.render_text())
        return int(ExitCode.SUCCESS if sc_res.status == "SUPPORTED" else ExitCode.INCOMPLETE_OR_UNSUPPORTED)

    if args.command == "workspace":
        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: workspace requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        ws_res = analyze_workspace(session_path, codex_home=args.codex_home)
        if args.json:
            _json(ws_res.to_dict(), command="workspace", status=ws_res.workspace_health, session=ws_res.session_id)
        else:
            print(ws_res.render_text())
        return int(ExitCode.SUCCESS if ws_res.workspace_health == "HEALTHY" else ExitCode.WARNINGS_FOUND)

    if args.command == "writer":
        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: writer requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        wr_res = inspect_writer(session_path, codex_home=args.codex_home)
        if args.json:
            _json(wr_res.to_dict(), command="writer", status="ACTIVE_WRITER" if wr_res.lock_present and wr_res.owner_process_alive else "INACTIVE", session=wr_res.session_id)
        else:
            print(wr_res.render_text())
        return int(ExitCode.SUCCESS if not wr_res.lock_present else ExitCode.WARNINGS_FOUND)

    if args.command == "plan":
        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: plan requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        p_res = generate_recovery_plan(session_path, codex_home=args.codex_home)
        if args.json:
            _json(p_res.to_dict(), command="plan", status="APPLICABLE" if p_res.is_applicable else "REFUSED", session=p_res.session_reference)
        else:
            print(p_res.render_text())
        return int(ExitCode.SUCCESS if p_res.is_applicable else ExitCode.WARNINGS_FOUND)

    if args.command == "apply-plan":
        apply_res = apply_recovery_plan(args.plan, dry_run=args.dry_run, backup_root=args.backup_root, codex_home=args.codex_home)
        if args.json:
            _json(apply_res.to_dict(), command="apply-plan", status="SUCCESS" if apply_res.plan_applied else "REFUSED")
        else:
            if apply_res.plan_applied:
                print(f"Apply Plan: SUCCESS (dry_run={'YES' if apply_res.dry_run else 'NO'})")
                if apply_res.backup_path:
                    print(f"Backup created at: {apply_res.backup_path}")
                print(f"Operations executed: {', '.join(apply_res.operations_executed) or 'None'}")
            else:
                print(f"Apply Plan: REFUSED")
                print(f"Reason: {apply_res.refusal_reason}")
        return int(ExitCode.SUCCESS if apply_res.plan_applied else ExitCode.UNSAFE_TO_MODIFY)

    if args.command == "bundle":
        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: bundle requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        try:
            bundle_obj, bundle_file = generate_support_bundle(session_path, output_bundle_path=args.output, codex_home=args.codex_home)
            if args.json:
                _json(bundle_obj.to_dict(), command="bundle", status="SUCCESS", session=bundle_obj.session_id)
            else:
                print(f"Support Bundle Generated: {bundle_file}")
                print(f"Redaction Audit Passed: {'YES' if bundle_obj.redaction_audit_passed else 'NO'}")
            return int(ExitCode.SUCCESS)
        except Exception as e:
            print(f"Error generating bundle: {e}", file=sys.stderr)
            return int(ExitCode.INTERNAL_FAILURE)

    if args.command == "redact-check":
        violations = audit_bundle_file(args.artifact)
        passed = (len(violations) == 0)
        if args.json:
            _json({"passed": passed, "violations": violations}, command="redact-check", status="PASS" if passed else "FAIL")
        else:
            if passed:
                print(f"Redaction Audit: PASS ({args.artifact})")
            else:
                print(f"Redaction Audit: FAIL ({len(violations)} violations detected in {args.artifact})")
                for v in violations:
                    print(f"  * {v}")
        return int(ExitCode.SUCCESS if passed else ExitCode.WARNINGS_FOUND)

    if args.command == "report":
        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: report requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        report_file = generate_html_report(session_path, output_html_path=args.output, codex_home=args.codex_home)
        if args.json:
            _json({"html_report_path": report_file}, command="report", status="SUCCESS")
        else:
            print(f"Offline HTML Report Generated: {report_file}")
        return int(ExitCode.SUCCESS)

    if args.command == "salvage":
        session_path = _resolve_session(args.session, args.latest, args.codex_home)
        if session_path is None or not Path(session_path).exists():
            print("Error: salvage requires a valid session path or --latest", file=sys.stderr)
            return int(ExitCode.INVALID_INPUT)
        from .doctor import doctor_session
        result = doctor_session(session_path, args.oversized_threshold)
        data = _to_dict(result)
        status = str(data.get("status", "UNKNOWN_CORRUPTION"))
        findings = list(data.get("findings") or [status])
        salvage_result = salvage_session(
            session_path,
            _parsed_from_doctor(result),
            status,
            findings,
            args.rescue_root,
            args.fork,
        )
        if args.json:
            _json(salvage_result.to_dict(), command="salvage", status=status, session=str(session_path.stem))
        else:
            print(f"Salvage: {salvage_result.rescue_id}")
            print(f"Original session untouched: {'yes' if salvage_result.original_untouched else 'no'}")
            if salvage_result.rescue_dir:
                print(f"Rescue directory: {salvage_result.rescue_dir}")
            if salvage_result.continuation_command:
                print(f"Continue: {salvage_result.continuation_command}")
        return int(ExitCode.SUCCESS if salvage_result.original_untouched else ExitCode.ACTIONABLE_FINDINGS)

    if args.command == "verify":
        result = verify_rescue(args.rescue_root, args.rescue_id)
        if args.json:
            _json(result.to_dict(), command="verify", status=result.status)
        else:
            print(f"Verify: {result.status}")
            for value in result.conflicts:
                print(f"Conflict: {value}")
            for value in result.review_reasons:
                print(f"Review: {value}")
        return int(ExitCode.SUCCESS if result.status == "SAFE_TO_CONTINUE" else ExitCode.INCOMPLETE_OR_UNSUPPORTED)

    return int(ExitCode.INVALID_INPUT)


if __name__ == "__main__":
    raise SystemExit(main())
