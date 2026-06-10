from __future__ import annotations

import asyncio
import logging

from app.agent.tools.clip_reproject.formatter import format_clip_reproject_context
from app.agent.tools.clip_reproject.schema import ClipReprojectArguments
from app.agent.tools.common import (
    IMAGERY_ID_PATTERN,
    execution_metadata,
    imagery_not_found_result,
    invalid_imagery_id_result,
    resolve_imagery_paths,
)
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient
from app.schemas.chat import ToolExecutionInfo

logger = logging.getLogger(__name__)


async def run_clip_reproject(args: ClipReprojectArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("裁剪/重投影")
    source_path, _imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    results_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    if not settings.rs_tools_mcp_use_docker:
        return _error_result("裁剪/重投影失败: RS Tools Docker MCP 未启用。", "mcp_disabled")
    payload = {
        "dst_crs": args.dst_crs,
        "bbox": args.bbox,
        "bbox_crs": args.bbox_crs,
        "resampling": args.resampling,
        "max_dimension": settings.imagery_preview_max_dimension,
    }
    try:
        stats = await _client(settings).call_tool(
            "clip_reproject_raster",
            source_path=source_path,
            output_dir=results_dir,
            arguments=payload,
        )
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("Clip/reproject failed: %s", exc)
        return _error_result(f"裁剪/重投影失败: {exc}", "mcp_error")
    except Exception as exc:
        logger.exception("Clip/reproject unexpected error: %s", exc)
        return _error_result(f"裁剪/重投影失败: {exc}", "unexpected_error")

    result_filename = str(stats.get("output_png") or "clip_reproject_colored.png")
    bounds = stats.get("bounds_wgs84")
    bounds_tuple = tuple(bounds) if isinstance(bounds, list) and len(bounds) == 4 else None
    execution_info = ToolExecutionInfo(mode="docker_mcp", fallback_used=False)
    geospatial_result = {
        "type": "clip_reproject",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": bounds_tuple,
        "stats": {
            "src_crs": stats.get("src_crs"),
            "dst_crs": stats.get("dst_crs"),
            "width": stats.get("width"),
            "height": stats.get("height"),
            "band_count": stats.get("band_count"),
            "clipped": stats.get("clipped"),
            "reprojected": stats.get("reprojected"),
        },
        "execution": execution_info.model_dump(exclude_none=True),
        "download_url": f"/api/imagery/{args.imagery_id}/results/{stats.get('output_tif', 'clip_reproject.tif')}",
    }
    return ToolRunResult(
        tool_context=format_clip_reproject_context(args.imagery_id, stats, result_filename),
        result_count=1,
        query=f"clip_reproject_raster({args.imagery_id})",
        geospatial_result=geospatial_result,
        artifacts=[AgentArtifact(type="geospatial", payload=geospatial_result)],
        metadata=execution_metadata("docker_mcp"),
    )


def _client(settings) -> RSToolsMCPClient:
    return RSToolsMCPClient(
        image=settings.rs_tools_mcp_image,
        timeout_seconds=settings.rs_tools_docker_timeout_seconds,
        memory_limit=settings.rs_tools_mcp_memory_limit,
        cpus=settings.rs_tools_mcp_cpus,
        network=settings.rs_tools_mcp_network,
    )


def _error_result(message: str, code: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=message,
        error=code,
        metadata=execution_metadata("failed", error_code=code),
    )
