from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .evidence import collect_session_evidence
from .redact import sanitize_path


@dataclass
class GraphNode:
    session_id: str
    session_path: str
    depth: int = 0
    parent_id: str | None = None
    children: list[GraphNode] = field(default_factory=list)
    size_bytes: int = 0
    turn_count: int = 0
    lifecycle_status: str = "unknown"
    is_orphan: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_path": self.session_path,
            "depth": self.depth,
            "parent_id": self.parent_id,
            "size_bytes": self.size_bytes,
            "turn_count": self.turn_count,
            "lifecycle_status": self.lifecycle_status,
            "is_orphan": self.is_orphan,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class SessionGraph:
    root_session_id: str
    family_sessions_count: int = 1
    max_depth: int = 0
    aggregate_family_bytes: int = 0
    root_node: GraphNode | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_session_id": self.root_session_id,
            "family_sessions_count": self.family_sessions_count,
            "max_depth": self.max_depth,
            "aggregate_family_bytes": self.aggregate_family_bytes,
            "tree": self.root_node.to_dict() if self.root_node else None,
        }

    def render_text(self) -> str:
        lines: list[str] = []
        lines.append(f"Session Family Graph: {self.root_session_id}")
        lines.append(f"Family sessions: {self.family_sessions_count} | Aggregate bytes: {self.aggregate_family_bytes} | Max depth: {self.max_depth}\n")

        def _render_node(node: GraphNode, indent: str = ""):
            status_flag = f"[{node.lifecycle_status}]"
            orphan_flag = " (ORPHAN)" if node.is_orphan else ""
            lines.append(f"{indent}├── {node.session_id} {status_flag}{orphan_flag} ({node.size_bytes} bytes, {node.turn_count} turns)")
            for child in node.children:
                _render_node(child, indent + "│   ")

        if self.root_node:
            _render_node(self.root_node)
        return "\n".join(lines)


def build_session_graph(
    session_path: Path | str,
    codex_home: Path | str | None = None,
    max_depth: int = 10,
) -> SessionGraph:
    path = Path(session_path).resolve()
    ev = collect_session_evidence(path, codex_home=codex_home)

    def _determine_lifecycle(evidence) -> str:
        events = [e.get("event") for e in evidence.rollout.lifecycle_events]
        if "task_complete" in events:
            return "completed"
        if "abort_interruption" in events:
            return "interrupted"
        if evidence.writer.lock_present and evidence.writer.is_alive:
            return "active"
        return "unknown"

    root_node = GraphNode(
        session_id=ev.session_id,
        session_path=ev.session_path,
        depth=0,
        parent_id=ev.rollout.parent_id,
        size_bytes=ev.size_bytes,
        turn_count=ev.rollout.turn_count,
        lifecycle_status=_determine_lifecycle(ev),
        is_orphan=bool(ev.rollout.parent_id and not list(Path(ev.session_path).parent.glob(f"*{ev.rollout.parent_id}*"))),
    )

    graph = SessionGraph(
        root_session_id=ev.session_id,
        family_sessions_count=1,
        max_depth=0,
        aggregate_family_bytes=ev.size_bytes,
        root_node=root_node,
    )

    subagent_dir = path.parent / "subagents" if (path.parent / "subagents").exists() else path.parent
    for child_id in ev.rollout.subagent_ids:
        matches = list(subagent_dir.glob(f"*{child_id}*.jsonl"))
        if matches:
            child_path = matches[0]
            child_ev = collect_session_evidence(child_path, codex_home=codex_home)
            child_node = GraphNode(
                session_id=child_id,
                session_path=child_ev.session_path,
                depth=1,
                parent_id=ev.session_id,
                size_bytes=child_ev.size_bytes,
                turn_count=child_ev.rollout.turn_count,
                lifecycle_status=_determine_lifecycle(child_ev),
            )
            root_node.children.append(child_node)
            graph.family_sessions_count += 1
            graph.aggregate_family_bytes += child_ev.size_bytes
            graph.max_depth = max(graph.max_depth, 1)

    return graph
