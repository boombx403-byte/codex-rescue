from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.graph import SurfaceVisibility
from codex_rescue.alpha7.invariants import InvariantCheckResult, InvariantEngine, InvariantStatus
from codex_rescue.alpha7.recovery.backup import BackupEngine
from codex_rescue.alpha7.simulation.simulator import RepairSimulator, SimulationResult
from codex_rescue.alpha7.surfaces.desktop import DesktopAdapter
from codex_rescue.alpha7.surfaces.detector import EnvironmentTopology, SurfaceDetector
from codex_rescue.alpha7.surfaces.router import DiagnosticRoute, DiagnosticRouter


@dataclass
class AutopilotResult:
    topology: EnvironmentTopology
    selected_surface: str
    diagnostics: List[DiagnosticRoute] = field(default_factory=list)
    action_taken: str = "INSPECTED"  # INSPECTED, SIMULATED, REPAIRED, BLOCKED
    simulation: Optional[SimulationResult] = None
    invariants: List[InvariantCheckResult] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_surface": self.selected_surface,
            "action_taken": self.action_taken,
            "message": self.message,
            "topology": self.topology.to_dict(),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "simulation": self.simulation.to_dict() if self.simulation else None,
            "invariants": [
                {"id": i.invariant_id.value, "status": i.status.value, "message": i.message}
                for i in self.invariants
            ],
        }


class AutopilotEngine:
    """Alpha7 Unified Autopilot Controller."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.router = DiagnosticRouter(self.codex_home)
        self.desktop_adapter = DesktopAdapter(self.codex_home)

    def run_autopilot(
        self,
        surface: Optional[str] = None,
        yes: bool = False,
        no_prompt: bool = False,
        repair_safe: bool = False,
    ) -> AutopilotResult:
        topology = SurfaceDetector.detect_topology(self.codex_home)

        # Invariant checks: --yes and --no-prompt cannot bypass safety
        inv_flags = InvariantEngine.check_flags_cannot_bypass_safety(yes, no_prompt)

        # 1. Surface Resolution
        active_surfaces = [k for k, v in topology.surfaces.items() if v.available]
        chosen_surface = surface or "all"

        if not surface:
            if len(active_surfaces) == 1:
                chosen_surface = active_surfaces[0]
            elif len(active_surfaces) > 1:
                chosen_surface = "all" if no_prompt else "all"

        # 2. Run diagnostics
        diagnostics = []
        sessions_dir = self.codex_home / "sessions"
        if sessions_dir.exists():
            for p in list(sessions_dir.glob("*.jsonl"))[:20]:
                route = self.router.route_session(p)
                diagnostics.append(route)

        action = "INSPECTED"
        sim_res = None
        msg = f"Autopilot analyzed {len(diagnostics)} sessions across surface '{chosen_surface}'."

        # 3. Safe repair pipeline if requested
        if repair_safe:
            # Check for candidate repairs
            for d in diagnostics:
                if "UNINDEXED_IN_SQLITE" in d.findings:
                    # Simulate repair first
                    sim_res = RepairSimulator.simulate_derived_index_repair(
                        source_rollout=self.codex_home / "sessions" / f"{d.symptom}.jsonl"
                    )
                    if sim_res.safe_to_apply:
                        action = "SIMULATION_PASSED"
                        msg += " Safe repair plan simulated and verified."
                    else:
                        action = "BLOCKED"
                        msg += " Repair blocked: simulation failed safety invariants."
                    break

        return AutopilotResult(
            topology=topology,
            selected_surface=chosen_surface,
            diagnostics=diagnostics,
            action_taken=action,
            simulation=sim_res,
            invariants=[inv_flags],
            message=msg,
        )
