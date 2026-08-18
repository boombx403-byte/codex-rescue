from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from codex_rescue.alpha7.graph import SurfaceObservation, SurfaceVisibility


@dataclass
class AppServerCapabilities:
    protocol_version: str = "v1"
    supported_methods: List[str] = field(default_factory=lambda: ["initialize", "thread/list", "thread/read"])
    server_version: Optional[str] = None
    server_pid: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "supported_methods": self.supported_methods,
            "server_version": self.server_version,
            "server_pid": self.server_pid,
        }


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"JSON-RPC Error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class StdioJsonRpcClient:
    """Real JSON-RPC 2.0 stdio client for Codex App Server."""

    def __init__(self, process: subprocess.Popen, timeout: float = 5.0):
        self.process = process
        self.timeout = timeout
        self._request_id = 0
        self._lock = threading.Lock()
        self.is_initialized = False

    def send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.process.poll() is not None:
            raise RuntimeError(f"App server process terminated with code {self.process.returncode}")

        with self._lock:
            self._request_id += 1
            req_id = self._request_id
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
            msg = json.dumps(payload) + "\n"

            try:
                assert self.process.stdin is not None
                self.process.stdin.write(msg.encode("utf-8"))
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise RuntimeError(f"Failed to write to app server stdio: {e}")

            # Read response line
            assert self.process.stdout is not None
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("App server closed stdout (EOF)")

            try:
                resp = json.loads(line.decode("utf-8").strip())
            except Exception as e:
                raise RuntimeError(f"Failed to parse JSON-RPC response from app server: {e}")

            if "error" in resp and resp["error"]:
                err = resp["error"]
                raise JsonRpcError(
                    code=err.get("code", -32000),
                    message=err.get("message", "Unknown error"),
                    data=err.get("data"),
                )

            return resp.get("result", {})

    def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        if self.process.poll() is not None:
            return

        with self._lock:
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }
            msg = json.dumps(payload) + "\n"
            try:
                assert self.process.stdin is not None
                self.process.stdin.write(msg.encode("utf-8"))
                self.process.stdin.flush()
            except Exception:
                pass


class RealAppServerClient:
    """Production-grade App Server protocol client supporting stdio and IPC."""

    def __init__(self, codex_home: Optional[Path] = None, timeout: float = 5.0):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.timeout = timeout
        self._client: Optional[StdioJsonRpcClient] = None
        self._process: Optional[subprocess.Popen] = None
        self.capabilities = AppServerCapabilities()

    def launch_stdio_server(self, binary_path: Optional[str] = None) -> bool:
        """Launches real `codex app-server` subprocess communicating over stdio."""
        codex_bin = binary_path or os.environ.get("CODEX_BIN", "codex")
        cmd = [codex_bin, "app-server", "--codex-home", str(self.codex_home)]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self._client = StdioJsonRpcClient(self._process, timeout=self.timeout)
            return True
        except FileNotFoundError:
            # Codex binary not installed/available
            return False
        except Exception:
            return False

    def connect_existing_client(self, client: StdioJsonRpcClient) -> None:
        """Connects a pre-spawned or mock transport client."""
        self._client = client

    def initialize(self) -> Dict[str, Any]:
        """Performs JSON-RPC 2.0 initialize -> initialized handshake."""
        if not self._client:
            raise RuntimeError("App server transport not connected")

        res = self._client.send_request(
            "initialize",
            {
                "client_name": "codex-rescue",
                "client_version": "0.1.0a7",
                "capabilities": {"read_only": True},
            },
        )
        self._client.send_notification("initialized", {})
        self._client.is_initialized = True

        self.capabilities.protocol_version = res.get("protocol_version", "v1")
        self.capabilities.server_version = res.get("server_version")
        return res

    def list_threads(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Invokes real `thread/list` JSON-RPC method."""
        if not self._client or not self._client.is_initialized:
            raise RuntimeError("App server not initialized")

        res = self._client.send_request("thread/list", {"limit": limit})
        return res.get("threads", []) if isinstance(res, dict) else []

    def read_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Invokes real `thread/read` JSON-RPC method."""
        if not self._client or not self._client.is_initialized:
            raise RuntimeError("App server not initialized")

        try:
            res = self._client.send_request("thread/read", {"thread_id": thread_id})
            return res if isinstance(res, dict) else None
        except JsonRpcError as e:
            if e.code in (-32600, -32602, 404):
                return None
            raise

    def shutdown(self) -> None:
        """Clean shutdown of client and subprocess."""
        if self._client:
            try:
                self._client.send_notification("shutdown", {})
            except Exception:
                pass

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self._client = None


@dataclass
class ServerProbeResult:
    reachable: bool = False
    has_socket: bool = False
    socket_path: Optional[str] = None
    status: str = "OFFLINE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reachable": self.reachable,
            "has_socket": self.has_socket,
            "socket_path": self.socket_path,
            "status": self.status,
        }


class AppServerAdapter:
    """Read-only adapter for App Server surface discovery and thread visibility."""

    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

    def observe_thread(self, session_id: str, client: Optional[RealAppServerClient] = None) -> SurfaceObservation:
        """Probes thread visibility through real JSON-RPC client or graceful fallback."""
        if client and client._client and client._client.is_initialized:
            try:
                thread_data = client.read_thread(session_id)
                if thread_data is not None:
                    return SurfaceObservation(
                        surface="app_server",
                        visibility=SurfaceVisibility.VISIBLE,
                        notes="Thread verified readable via JSON-RPC 2.0 App Server protocol",
                    )
                return SurfaceObservation(
                    surface="app_server",
                    visibility=SurfaceVisibility.HIDDEN,
                    error_code="NOT_FOUND",
                    notes="Thread not listed in App Server active state",
                )
            except Exception as e:
                return SurfaceObservation(
                    surface="app_server",
                    visibility=SurfaceVisibility.INACCESSIBLE,
                    error_code="RPC_ERROR",
                    notes=str(e),
                )

        # Standalone probe: check if socket / app-server process is active
        socket_path = self.codex_home / "app_server.sock"
        if socket_path.exists():
            return SurfaceObservation(
                surface="app_server",
                visibility=SurfaceVisibility.INACCESSIBLE,
                error_code="SOCKET_PRESENT_UNCONNECTED",
                notes="App server socket found but no active client attached",
            )

        return SurfaceObservation(
            surface="app_server",
            visibility=SurfaceVisibility.UNSUPPORTED,
            error_code="SERVER_OFFLINE",
            notes="No active Codex App Server subprocess found",
        )

    def probe_server(self) -> ServerProbeResult:
        """Probes local App Server presence and connectivity."""
        socket_path = self.codex_home / "app_server.sock"
        has_socket = socket_path.exists()
        return ServerProbeResult(
            reachable=False,
            has_socket=has_socket,
            socket_path=str(socket_path) if has_socket else None,
            status="OFFLINE",
        )
