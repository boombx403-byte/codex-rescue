from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_rescue.alpha7.graph import SurfaceObservation, SurfaceVisibility


@dataclass
class AppServerStatus:
    available: bool = False
    port: Optional[int] = None
    socket_path: Optional[str] = None
    protocol_version: Optional[str] = None
    reachable: bool = False
    readable_threads_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "port": self.port,
            "socket_path": self.socket_path,
            "protocol_version": self.protocol_version,
            "reachable": self.reachable,
            "readable_threads_count": self.readable_threads_count,
            "error": self.error,
        }


class AppServerAdapter:
    """Read-only optional App Server adapter. Gracefully handles unreachability."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

    def probe_server(self) -> AppServerStatus:
        info_file = self.codex_home / "app_server.json"
        if not info_file.exists():
            return AppServerStatus(available=False, error="app_server.json not found")

        try:
            data = json.loads(info_file.read_text(encoding="utf-8"))
            port = data.get("port")
            version = data.get("protocol_version", "v1")

            if port:
                # Try cheap ping
                req = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers={"User-Agent": "CodexRescue/0.1.0a7"})
                try:
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        if resp.status == 200:
                            return AppServerStatus(available=True, port=port, protocol_version=version, reachable=True)
                except Exception:
                    return AppServerStatus(available=True, port=port, protocol_version=version, reachable=False, error="Connection refused")

            return AppServerStatus(available=True, port=port, protocol_version=version, reachable=False)
        except Exception as e:
            return AppServerStatus(available=False, error=str(e))

    def observe_thread(self, session_id: str) -> SurfaceObservation:
        """Probes whether App Server can read/serve the specified thread."""
        status = self.probe_server()
        if not status.reachable or not status.port:
            return SurfaceObservation(
                surface="app_server",
                visibility=SurfaceVisibility.UNSUPPORTED if not status.available else SurfaceVisibility.INACCESSIBLE,
                error_code="APP_SERVER_UNREACHABLE",
                notes="App server offline or unreachable",
            )

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{status.port}/threads/{session_id}",
                headers={"User-Agent": "CodexRescue/0.1.0a7"},
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    return SurfaceObservation(
                        surface="app_server",
                        visibility=SurfaceVisibility.VISIBLE,
                        notes="Thread readable via App Server protocol",
                    )
                return SurfaceObservation(
                    surface="app_server",
                    visibility=SurfaceVisibility.HIDDEN,
                    error_code=f"HTTP_{resp.status}",
                )
        except urllib.error.HTTPError as e:
            return SurfaceObservation(
                surface="app_server",
                visibility=SurfaceVisibility.HIDDEN if e.code == 404 else SurfaceVisibility.INACCESSIBLE,
                error_code=f"HTTP_{e.code}",
            )
        except Exception as e:
            return SurfaceObservation(
                surface="app_server",
                visibility=SurfaceVisibility.INACCESSIBLE,
                error_code="PROBE_FAILED",
                notes=str(e),
            )
