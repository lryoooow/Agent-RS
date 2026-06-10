from __future__ import annotations

import asyncio
import logging

from app.agent.tools.cloud_mask.formatter import format_cloud_mask_context
from app.agent.tools.cloud_mask.schema import CloudMaskArguments
from app.agent.tools.common import (
    IMAGERY_ID_PATTERN,
    execution_metadata,
    imagery_not_found_result,
    invalid_bands_result,
    invalid_imagery_id_result,
    read_bounds,
    resolve_imagery_paths,
    validate_band_indices,
)
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient
from app.schemas.chat import ToolExecutionInfo

logger = logging.getLogger(__name__)


async def run_cloud_mask(args: CloudMaskArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("云/阴影掩膜")
    source_path, imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    results_dir.mkdir(parents=True, exist_ok=True)

    band_error = validate_band_indices(
        source_path,
        {
            "red": args.red_band,
            "green": args.green_band,
            "blue": args.blue_band,
            "nir": args.nir_band,
        },
    )
    if band_error:
        return invalid_bands_result("云/阴影掩膜", band_error)

    settings = get_settings()
    if not settings.rs_tools_mcp_use_docker:
        return _error_result("云/阴影掩膜失败: RS Tools Docker MCP 未启用。", "mcp_disabled")
    payload = {
        "red_band": args.red_band,
        "green_band": args.green_band,
        "blue_band": args.blue_band,
        "nir_band": args.nir_band,
    }
    try:
        stats = await _client(settings).call_tool(
            "cloud_shadow_mask",
            source_path=source_path,
            output_dir=results_dir,
            arguments=payload,
        )
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("Cloud/shadow mask failed: %s", exc)
        return _error_result(f"云/阴影掩膜失败: {exc}", "mcp_error")
    except Exception as exc:
        logger.exception("Cloud/shadow mask unexpected error: %s", exc)
        return _error_result(f"云/阴影掩膜失败: {exc}", "unexpected_error")

    result_filename = str(stats.get("output_png") or "cloud_mask_colored.png")
    execution_info = ToolExecutionInfo(mode="docker_mcp", fallback_used=False)
    geospatial_result = {
        "type": "cloud_mask",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": read_bounds(imagery_dir / "metadata.json"),
        "stats": {
            "cloud_pct": stats.get("cloud_pct"),
            "shadow_pct": stats.get("shadow_pct"),
            "clear_pct": stats.get("clear_pct"),
            "nodata_pct": stats.get("nodata_pct"),
        },
        "execution": execution_info.model_dump(exclude_none=True),
        "legend": {
            "label": "云/阴影掩膜",
            "classes": [
                {"code": 0, "name": "晴空"},
                {"code": 1, "name": "云"},
                {"code": 2, "name": "阴影"},
                {"code": 3, "name": "无效"},
            ],
        },
    }
    return ToolRunResult(
        tool_context=format_cloud_mask_context(args.imagery_id, stats, result_filename),
        result_count=1,
        query=f"cloud_shadow_mask({args.imagery_id})",
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
