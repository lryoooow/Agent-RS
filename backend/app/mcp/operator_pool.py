"""Stage one isolated job on the shared volume of a trusted Docker MCP worker."""
import asyncio
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from app.core.settings import get_settings
from app.mcp.http_client import StreamableHTTPMCPClient
from app.mcp.types import MCPCallError


async def _copy_files(files):
    def copy():
        for source, target in files:
            shutil.copyfile(source, target)
    pending = asyncio.create_task(asyncio.to_thread(copy))
    try:
        await asyncio.shield(pending)
    except asyncio.CancelledError:
        # Keep private directories alive until the file handles close.
        await asyncio.gather(pending, return_exceptions=True)
        raise


async def _publish_from_worker(outputs, output_dir, result):
    from app.mcp.rs_tools_client import _publish_outputs
    if outputs.stat().st_dev == output_dir.stat().st_dev:
        _publish_outputs(outputs, output_dir, result)
        return
    with TemporaryDirectory(prefix=".tool-output-", dir=output_dir.parent) as directory:
        staging = Path(directory)
        files = []
        for path in outputs.iterdir():
            if path.is_symlink() or not path.is_file():
                raise MCPCallError("artifact_publication_failed: invalid tool output entry")
            files.append((path, staging / path.name))
        await _copy_files(files)
        _publish_outputs(staging, output_dir, result)


async def call_operator(tool, source_path, output_dir, arguments, *, timeout, on_progress):
    settings = get_settings()
    endpoint = {"ocr_recognize": settings.rs_doc_http_url, "detect_objects": settings.rs_detect_http_url}.get(
        tool, settings.rs_tools_http_url)
    if not endpoint or not settings.rs_tools_http_workspace or not settings.rs_tools_http_token:
        raise MCPCallError("常驻算子需要配置端点、共享工作目录及访问令牌")
    client = StreamableHTTPMCPClient(endpoint, allowed_hosts={urlsplit(endpoint).hostname}, operator=True,
                bearer_token=settings.rs_tools_http_token, timeout_seconds=timeout)
    root = Path(settings.rs_tools_http_workspace)
    if not root.is_absolute():
        raise MCPCallError("常驻算子共享目录需要使用绝对路径")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="job-", dir=root) as dirname:
        job = Path(dirname)
        inputs, outputs = job / "input", job / "output"
        inputs.mkdir()
        outputs.mkdir()
        payload = dict(arguments)
        mount = f"/jobs/{job.name}"
        source = Path(source_path).resolve()
        files = [(source, inputs / "source.tif")]
        payload["input_path"] = mount + "/input/source.tif"
        if "quality_path" in payload:
            if str(payload["quality_path"]) != "/data/quality.tif":
                raise MCPCallError("invalid platform quality sidecar")
            files.append((source.parent / "quality.tif", inputs / "quality.tif"))
            payload["quality_path"] = mount + "/input/quality.tif"
        await _copy_files(files)
        if output_dir is not None:
            output_dir = Path(output_dir).resolve()
            output_dir.relative_to(source.parent)
            output_dir.mkdir(parents=True, exist_ok=True)
            payload["output_dir"] = mount + "/output"
        result = await client.call_tool(tool, payload, on_progress=on_progress)
        if output_dir is not None:
            # The worker volume and the user's artifact directory may be different mounts.
            await _publish_from_worker(outputs, output_dir, result)
        return result
