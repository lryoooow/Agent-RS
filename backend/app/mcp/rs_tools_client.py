"""One-shot MCP client for the remote-sensing tools Docker container."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.mcp.client import StdioMCPClient
from app.mcp.concurrency import tool_semaphore

logger = logging.getLogger(__name__)

CLIENT_NAME = "agent-rs-tools-client"
CLIENT_VERSION = "0.1.0"


class RSToolsMCPClient:
    def __init__(
        self,
        image: str,
        *,
        container_imagery_root: str = "/data",
        timeout_seconds: int = 120,
        memory_limit: str = "2g",
        cpus: float = 2.0,
        network: str = "none",
        gpus: str | None = None,
    ) -> None:
        self.image = image
        self.container_imagery_root = container_imagery_root.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.memory_limit = memory_limit
        self.cpus = cpus
        self.network = network
        self.gpus = gpus

    def host_to_container(self, host_path: Path, *, mount_root: Path) -> str:
        rel = host_path.resolve().relative_to(mount_root.resolve())
        return f"{self.container_imagery_root}/{rel.as_posix()}"

    async def call_tool(
        self,
        tool_name: str,
        *,
        source_path: Path,
        output_dir: Path | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mount_root = source_path.resolve().parent
        payload = dict(arguments or {})
        payload["input_path"] = self.host_to_container(source_path, mount_root=mount_root)
        if output_dir is not None:
            output_dir.resolve().relative_to(mount_root)
            payload["output_dir"] = self.host_to_container(output_dir, mount_root=mount_root)

        command = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            self.network,
            "--memory",
            self.memory_limit,
            "--cpus",
            str(self.cpus),
        ]
        if self.gpus:
            command.extend(["--gpus", self.gpus])
        command.extend(
            [
                "-v",
                f"{mount_root}:{self.container_imagery_root}",
                self.image,
            ]
        )
        logger.info("[RS Tools MCP] launch image=%s tool=%s mount_root=%s", self.image, tool_name, mount_root)
        # 并发总闸：只包住实际 `docker run` 执行，不包前面的路径拼装（不占资源）。
        # acquire 排在 StdioMCPClient 的 wait_for 计时之前，故排队等待不蚕食工具 timeout。
        # async with 确保异常路径也释放槽位，杜绝"异常吞槽"导致后续任务永久饿死。
        async with tool_semaphore():
            return await StdioMCPClient(
                command=command,
                timeout_seconds=self.timeout_seconds,
                client_name=CLIENT_NAME,
                client_version=CLIENT_VERSION,
            ).call_tool(tool_name, payload)
