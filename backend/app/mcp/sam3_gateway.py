"""Call the Docker MCP gateway using only a server-generated relative job reference."""
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.core.paths import imagery_root
from app.core.settings import get_settings
from app.mcp.client import StdioMCPClient
from app.mcp.http_client import StreamableHTTPMCPClient
from app.mcp.progress import current_progress
from app.mcp.types import MCPCallError


async def infer_via_gateway(job_dir: Path, concepts: list[str]) -> dict:
    settings = get_settings()
    root = imagery_root().resolve()
    job = job_dir.resolve().relative_to(root).as_posix()
    timeout = settings.sam3_inference_timeout_seconds
    # Leave time for the upstream to return its own settled / outcome-unknown signal.
    if settings.sam3_transport == "stdio_docker":
        service_root = settings.sam3_upstream_root or str(root)
        command = ["docker", "run", "--rm", "--pull=never", "--name", f"sam3-gw-{uuid4().hex[:12]}",
                   "-i", "--read-only", "--tmpfs", "/tmp", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                   "--memory", "512m", "--cpus", "1", "--network", settings.sam3_gateway_network,
                   "-e", f"SAM3_UPSTREAM_URL={settings.sam3_service_url}",
                   "-e", f"SAM3_UPSTREAM_ROOT={service_root}", "-e", f"SAM3_INFERENCE_TIMEOUT_SECONDS={timeout}",
                   settings.sam3_gateway_image]
        client = StdioMCPClient(command=command, timeout_seconds=timeout + 10,
                                client_name="agent-rs-sam3", client_version="1")
    else:
        if not settings.sam3_gateway_url or not settings.sam3_gateway_token:
            raise MCPCallError("SAM3 网关需要已配置的 MCP 端点和令牌")
        client = StreamableHTTPMCPClient(settings.sam3_gateway_url,
                allowed_hosts={urlsplit(settings.sam3_gateway_url).hostname}, operator=True,
                timeout_seconds=timeout + 10, bearer_token=settings.sam3_gateway_token)
    return await client.call_tool("segment_instances", {"job": job, "concepts": concepts}, on_progress=current_progress())
