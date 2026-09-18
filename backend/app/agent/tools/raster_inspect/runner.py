from __future__ import annotations

import asyncio
import logging

from app.agent.tools.common import (
    IMAGERY_ID_PATTERN,
    execution_metadata,
    imagery_not_found_result,
    invalid_imagery_id_result,
    resolve_imagery_paths,
)
from app.agent.tools.raster_inspect.formatter import format_raster_inspect_context
from app.agent.tools.raster_inspect.schema import RasterInspectArguments
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.services.raster_semantics import grid_context, band_semantics
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient

logger = logging.getLogger(__name__)


async def run_raster_inspect(args: RasterInspectArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("影像质检")
    source_path, _imagery_dir, _results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)

    settings = get_settings()
    if not settings.rs_tools_mcp_use_docker:
        return _error_result("影像质检失败: RS Tools Docker MCP 未启用。", "mcp_disabled")
    try:
        result = await _client(settings).call_tool("raster_inspect", source_path=source_path)
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("Raster inspect failed: %s", exc)
        return _error_result("影像质检失败，请稍后重试或检查影像与服务状态。", "mcp_error")
    except Exception as exc:
        logger.exception("Raster inspect unexpected error: %s", exc)
        return _error_result("影像质检失败，请稍后重试或检查影像与服务状态。", "unexpected_error")

    result.update(await asyncio.to_thread(grid_context, source_path))
    semantics = await asyncio.to_thread(band_semantics, source_path)
    result["band_roles"] = semantics.get("band_roles")
    result["band_roles_source"] = semantics.get("band_roles_source")
    # This is the same resolver used by inventory, preview and inference.
    roles = semantics.get("band_roles") or {}
    result["capabilities"] = {f"has_{role}": role in roles for role in ("blue", "green", "red", "nir", "swir")}
    tool_result = _tool_result(args.imagery_id, result)
    return ToolRunResult(
        tool_context=format_raster_inspect_context(args.imagery_id, result),
        result_count=1,
        query=f"RasterInspect({args.imagery_id})",
        tool_result=tool_result,
        artifacts=[AgentArtifact(type="raster_inspect", payload=tool_result)],
        metadata={**execution_metadata("docker_mcp"), "inspect": result},
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


def _tool_result(imagery_id: str, result: dict) -> dict:
    bounds = result.get("bounds")
    pixel_size = result.get("pixel_size")
    return {
        "type": "raster_inspect",
        **{key: result.get(key) for key in ("source_grid", "analysis_grid", "resampled", "band_roles", "band_roles_source", "color_interpretations", "alpha_bands", "alpha_statistics")},
        "imagery_id": imagery_id,
        "width": int(result.get("width") or 0),
        "height": int(result.get("height") or 0),
        "band_count": int(result.get("band_count") or 0),
        "crs": result.get("crs"),
        "bounds": tuple(bounds) if isinstance(bounds, list) and len(bounds) == 4 else None,
        "bounds_wgs84": result.get("bounds_wgs84"),
        "center_wgs84": result.get("center_wgs84"),
        "dtype": result.get("dtype"),
        "pixel_size": tuple(pixel_size) if isinstance(pixel_size, list) and len(pixel_size) == 2 else None,
        "nodata": result.get("nodata"),
        "capabilities": result.get("capabilities") or {},
        "per_band_stats": result.get("per_band_stats") or [],
        "execution": {"mode": "docker_mcp", "fallback_used": False},
    }
