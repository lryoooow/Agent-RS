"""Async MCP client for the NDVI Docker container.

Launches the container via `docker run --rm -i` and speaks JSON-RPC 2.0
over its stdin/stdout. One container instance per call (no long-lived
session) to keep state isolation simple.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.mcp.client import MCPCallError, StdioMCPClient

logger = logging.getLogger(__name__)

CLIENT_NAME = "agent-rs-ndvi-client"
CLIENT_VERSION = "0.1.0"


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

    def host_to_container(self, host_path: Path, *, mount_root: Path | None = None) -> str:
        """Map a host path under the active mount root to its container-side path."""
        root = (mount_root or self.host_imagery_root).resolve()
        rel = host_path.resolve().relative_to(root)
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
        mount_root = source_path.resolve().parent
        output_dir.resolve().relative_to(mount_root)
        container_input = self.host_to_container(source_path, mount_root=mount_root)
        container_output = self.host_to_container(output_dir, mount_root=mount_root)

        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", self.network,
            "--memory", self.memory_limit,
            "--cpus", str(self.cpus),
            "-v", f"{mount_root}:{self.container_imagery_root}",
            self.image,
        ]
        logger.info("[NDVI MCP] launch image=%s mount_root=%s", self.image, mount_root)

        return await StdioMCPClient(
            command=cmd,
            timeout_seconds=self.timeout_seconds,
            client_name=CLIENT_NAME,
            client_version=CLIENT_VERSION,
        ).call_tool(
            "calculate_ndvi",
            {
                "input_path": container_input,
                "output_dir": container_output,
                "red_band": red_band,
                "nir_band": nir_band,
            },
        )
