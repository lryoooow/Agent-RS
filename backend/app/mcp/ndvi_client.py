"""Async MCP client for the NDVI Docker container.

Launches the container via `docker run --rm -i` and speaks JSON-RPC 2.0
over its stdin/stdout. One container instance per call (no long-lived
session) to keep state isolation simple.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "agent-rs-ndvi-client"
CLIENT_VERSION = "0.1.0"


class MCPCallError(Exception):
    """Raised when the MCP server returns an error or the transport fails."""


class NDVIMCPClient:
    """One-shot MCP client. Build → call_ndvi() → process auto-terminates."""

    def __init__(
        self,
        image: str,
        host_imagery_root: Path,
        container_imagery_root: str = "/data",
        timeout_seconds: int = 120,
        memory_limit: str = "2g",
        cpus: float = 2.0,
        network: str = "none",
    ):
        self.image = image
        self.host_imagery_root = host_imagery_root.resolve()
        self.container_imagery_root = container_imagery_root.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.memory_limit = memory_limit
        self.cpus = cpus
        self.network = network

    def host_to_container(self, host_path: Path) -> str:
        """Map a host path under imagery_root to its container-side path."""
        rel = host_path.resolve().relative_to(self.host_imagery_root)
        return f"{self.container_imagery_root}/{rel.as_posix()}"

    async def call_ndvi(
        self,
        source_path: Path,
        output_dir: Path,
        red_band: int,
        nir_band: int,
    ) -> dict[str, Any]:
        """Execute the calculate_ndvi tool inside the container.

        Returns the parsed stats dict from structuredContent.
        """
        container_input = self.host_to_container(source_path)
        container_output = self.host_to_container(output_dir)

        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", self.network,
            "--memory", self.memory_limit,
            "--cpus", str(self.cpus),
            "-v", f"{self.host_imagery_root}:{self.container_imagery_root}",
            self.image,
        ]
        logger.info("[NDVI MCP] launch image=%s root_exists=%s", self.image, self.host_imagery_root.exists())

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stats = await asyncio.wait_for(
                self._handshake_and_call(
                    proc, container_input, container_output, red_band, nir_band
                ),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        except Exception:
            proc.kill()
            await proc.wait()
            raise
        else:
            try:
                proc.stdin.close()
            except Exception:
                pass
            await proc.wait()

        return stats

    async def _handshake_and_call(
        self,
        proc: asyncio.subprocess.Process,
        container_input: str,
        container_output: str,
        red_band: int,
        nir_band: int,
    ) -> dict[str, Any]:
        await self._send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        })
        init_resp = await self._recv(proc)
        if "error" in init_resp:
            raise MCPCallError(f"initialize failed: {init_resp['error']}")

        await self._send(proc, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        await self._send(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "calculate_ndvi",
                "arguments": {
                    "input_path": container_input,
                    "output_dir": container_output,
                    "red_band": red_band,
                    "nir_band": nir_band,
                },
            },
        })
        call_resp = await self._recv(proc)
        if "error" in call_resp:
            raise MCPCallError(f"tools/call failed: {call_resp['error']}")

        result = call_resp.get("result") or {}
        if result.get("isError"):
            text = ""
            for item in result.get("content", []):
                if item.get("type") == "text":
                    text = item.get("text", "")
                    break
            raise MCPCallError(text or "tool returned isError without message")

        stats = result.get("structuredContent")
        if not isinstance(stats, dict):
            raise MCPCallError("missing structuredContent in tool response")
        return stats

    @staticmethod
    async def _send(proc: asyncio.subprocess.Process, msg: dict) -> None:
        line = (json.dumps(msg) + "\n").encode("utf-8")
        proc.stdin.write(line)
        await proc.stdin.drain()

    @staticmethod
    async def _recv(proc: asyncio.subprocess.Process) -> dict:
        line = await proc.stdout.readline()
        if not line:
            stderr = (await proc.stderr.read()).decode(errors="replace")
            raise MCPCallError(f"MCP server closed stdout. stderr: {stderr[:500]}")
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MCPCallError(f"invalid JSON from server: {exc}: {line!r}")
