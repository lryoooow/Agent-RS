from __future__ import annotations

import asyncio
import logging

from app.agent.tools.band_composite.formatter import format_band_composite_context
from app.agent.tools.band_composite.schema import BandCompositeArguments, required_bands_for_composite
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


async def run_band_composite(args: BandCompositeArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("波段组合")
    source_path, imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    results_dir.mkdir(parents=True, exist_ok=True)

    band_error = validate_band_indices(
        source_path,
        required_bands_for_composite(args.mode, args.bands),
    )
    if band_error:
        return invalid_bands_result("波段组合", band_error)

    settings = get_settings()
    if not settings.rs_tools_mcp_use_docker:
        return _error_result("波段组合失败: RS Tools Docker MCP 未启用。", "mcp_disabled")
    payload = {
        "mode": args.mode,
        "bands": args.bands,
        "max_dimension": settings.imagery_preview_max_dimension,
    }
    try:
        result = await _client(settings).call_tool(
            "render_band_composite",
            source_path=source_path,
            output_dir=results_dir,
            arguments=payload,
        )
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("Band composite failed: %s", exc)
        return _error_result(f"波段组合失败: {exc}", "mcp_error")
    except Exception as exc:
        logger.exception("Band composite unexpected error: %s", exc)
        return _error_result(f"波段组合失败: {exc}", "unexpected_error")

    result_filename = str(result.get("output_png") or f"composite_{args.mode}.png")
    bands_used = [int(item) for item in result.get("bands_used", [])]
    execution_info = ToolExecutionInfo(mode="docker_mcp", fallback_used=False)
    geospatial_result = {
        "type": "composite",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": read_bounds(imagery_dir / "metadata.json"),
        "mode": args.mode,
        "bands_used": bands_used,
        "execution": execution_info.model_dump(exclude_none=True),
    }
    return ToolRunResult(
        tool_context=format_band_composite_context(args.imagery_id, args.mode, bands_used, result_filename),
        result_count=1,
        query=f"Composite({args.imagery_id}, {args.mode})",
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
