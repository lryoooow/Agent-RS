from __future__ import annotations

import asyncio
import logging

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
from app.agent.tools.detect.formatter import format_detect_context
from app.agent.tools.detect.schema import DetectArguments
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient
from app.schemas.chat import ToolExecutionInfo

logger = logging.getLogger(__name__)


async def run_detect(args: DetectArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("目标检测")
    source_path, imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    results_dir.mkdir(parents=True, exist_ok=True)

    band_error = validate_band_indices(
        source_path,
        {"red": args.red_band, "green": args.green_band, "blue": args.blue_band},
    )
    if band_error:
        return invalid_bands_result("目标检测", band_error)

    settings = get_settings()
    if not settings.rs_detect_mcp_use_docker:
        return _error_result("目标检测失败: RS Tools Docker MCP 未启用。", "mcp_disabled")
    payload = {
        "red_band": args.red_band,
        "green_band": args.green_band,
        "blue_band": args.blue_band,
        "score_threshold": args.score_threshold,
    }
    try:
        result = await _client(settings).call_tool(
            "detect_objects",
            source_path=source_path,
            output_dir=results_dir,
            arguments=payload,
        )
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("Object detection failed: %s", exc)
        return _error_result(f"目标检测失败: {exc}", "mcp_error")
    except Exception as exc:
        logger.exception("Object detection unexpected error: %s", exc)
        return _error_result(f"目标检测失败: {exc}", "unexpected_error")

    result_filename = str(result.get("output_png") or "detection_overlay.png")
    execution_info = ToolExecutionInfo(mode="docker_mcp", fallback_used=False)
    geospatial_result = {
        "type": "detection",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": read_bounds(imagery_dir / "metadata.json"),
        "detection_count": int(result.get("detection_count", 0)),
        "score_threshold": float(result.get("score_threshold", args.score_threshold)),
        "classes": result.get("classes") or [],
        "execution": execution_info.model_dump(exclude_none=True),
    }
    return ToolRunResult(
        tool_context=format_detect_context(args.imagery_id, result, result_filename),
        result_count=int(result.get("detection_count", 0)),
        query=f"detect_objects({args.imagery_id})",
        geospatial_result=geospatial_result,
        artifacts=[AgentArtifact(type="geospatial", payload=geospatial_result)],
        metadata=execution_metadata("docker_mcp"),
    )


def _client(settings) -> RSToolsMCPClient:
    return RSToolsMCPClient(
        image=settings.rs_detect_mcp_image,
        timeout_seconds=settings.rs_detect_docker_timeout_seconds,
        memory_limit=settings.rs_detect_mcp_memory_limit,
        cpus=settings.rs_detect_mcp_cpus,
        network=settings.rs_detect_mcp_network,
        gpus=settings.rs_detect_mcp_gpus or None,
    )


def _error_result(message: str, code: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=message,
        error=code,
        metadata=execution_metadata("failed", error_code=code),
    )
