"""One-shot MCP client for the remote-sensing tools Docker container."""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
import os
from hashlib import sha256
from uuid import uuid4
from typing import Any

from app.mcp.client import MCPCallError, StdioMCPClient
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
        accelerator: str = "nvidia",
    ) -> None:
        self.image = image
        self.container_imagery_root = container_imagery_root.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.memory_limit = memory_limit
        self.cpus = cpus
        self.network = network
        self.gpus = gpus
        self.accelerator = accelerator

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
            "--pull=never",
            # G10：命名容器——超时/取消时 StdioMCPClient 按名 docker kill，
            # 否则只杀本地 docker 客户端进程，容器本体继续在引擎上运行。
            "--name",
            f"rs-{uuid4().hex[:12]}",
            "-i",
            "--network",
            self.network,
            "--memory",
            self.memory_limit,
            "--cpus",
            str(self.cpus),
        ]
        # Native Linux bind mounts keep request-private directories at 0700.
        # Use the service process identity so a container's baked-in appuser
        # can read staged inputs and write outputs without opening them to others.
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        if self.accelerator == "hygon":
            command.extend(["--device=/dev/kfd", "--device=/dev/mkfd", "--device=/dev/dri", "-v", "/opt/hyhal:/opt/hyhal:ro"])
        elif self.accelerator == "nvidia" and self.gpus:
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
            client = StdioMCPClient(
                command=command,
                timeout_seconds=self.timeout_seconds,
                client_name=CLIENT_NAME,
                client_version=CLIENT_VERSION,
            )
            if output_dir is None:
                return await client.call_tool(tool_name, payload)
            # Each execution writes outside the public results directory. Only
            # complete, successful outputs are promoted; cancelled/failed calls
            # cannot leave half-files available through result download routes.
            output_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".tool-output-", dir=mount_root) as directory:
                work_dir = Path(directory)
                work_dir.resolve().relative_to(mount_root)
                payload["output_dir"] = self.host_to_container(work_dir, mount_root=mount_root)
                result = await client.call_tool(tool_name, payload)
                _publish_outputs(work_dir, output_dir.resolve(), result)
                return result


def _publish_outputs(work_dir: Path, output_dir: Path, result: dict[str, Any]) -> None:
    """Atomically publish complete files and roll back this call on disk failure.

    Runtime filenames carry execution UUIDs. Existing names are never replaced;
    this also rejects legacy containers that would overwrite a historical result.
    """
    files = sorted(work_dir.iterdir())
    for path in files:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != work_dir.resolve():
            raise MCPCallError("artifact_publication_failed: invalid tool output entry")
        if (output_dir / path.name).exists():
            raise MCPCallError("artifact_publication_failed: output name already exists")
    for key in ("output_png", "output_tif", "output_json", "output_geojson"):
        if key not in result or (key == "output_geojson" and result[key] is None):
            continue
        value = result[key]
        if not isinstance(value, str) or Path(value).name != value or not (work_dir / value).is_file():
            raise MCPCallError("artifact_publication_failed: declared output file is missing or invalid")
    published: list[Path] = []
    # Cooperating server workers reserve each target outside the public folder.
    # A legacy fixed-name output is rejected rather than racing another worker.
    lock_dir = output_dir.parent / ".artifact-locks"
    lock_dir.mkdir(exist_ok=True)
    locks: list[Path] = []
    try:
        for source in files:
            target = output_dir / source.name
            digest = sha256(os.path.normcase(str(target)).encode("utf-8")).hexdigest()
            lock_path = lock_dir / digest
            with lock_path.open("xb"):
                pass
            locks.append(lock_path)
            if target.exists():
                raise FileExistsError("output name already exists")
        for source in files:
            target = output_dir / source.name
            source.replace(target)
            published.append(target)
    except OSError as exc:
        for path in published:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Unable to remove this execution's unreferenced output: %s", path.name)
        raise MCPCallError("artifact_publication_failed: unable to publish tool outputs") from exc
    finally:
        for path in locks:
            path.unlink(missing_ok=True)
        # Keep this single small directory: another process can be between
        # mkdir and acquiring its first lock. Only this call's lock files are removed.
