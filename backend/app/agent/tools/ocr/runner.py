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
from app.agent.tools.ocr.formatter import format_ocr_context
from app.agent.tools.ocr.schema import OcrArguments
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient
from app.schemas.chat import ToolExecutionInfo

logger = logging.getLogger(__name__)


async def run_ocr(args: OcrArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("影像 OCR")
    source_path, imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    results_dir.mkdir(parents=True, exist_ok=True)

    # 灰度模式只用 red_band，RGB 模式校验三波段。
    bands = (
        {"red": args.red_band}
        if args.grayscale
        else {"red": args.red_band, "green": args.green_band, "blue": args.blue_band}
    )
    band_error = validate_band_indices(source_path, bands)
    if band_error:
        return invalid_bands_result("影像 OCR", band_error)

    settings = get_settings()
    if not settings.rs_doc_mcp_use_docker:
        return _error_result("影像 OCR 失败: RS Doc Docker MCP 未启用。", "mcp_disabled")
    payload = {
        "red_band": args.red_band,
        "green_band": args.green_band,
        "blue_band": args.blue_band,
        "grayscale": args.grayscale,
        "max_dimension": args.max_dimension,
        "min_confidence": args.min_confidence,
    }
    try:
        stats = await _client(settings).call_tool(
            "ocr_recognize",
            source_path=source_path,
            output_dir=results_dir,
            arguments=payload,
        )
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("OCR failed: %s", exc)
        return _error_result(f"影像 OCR 失败: {exc}", "mcp_error")
    except Exception as exc:
        logger.exception("OCR unexpected error: %s", exc)
        return _error_result(f"影像 OCR 失败: {exc}", "unexpected_error")

    max_chars = settings.ai_context_max_tool_chars
    full_text = str(stats.get("full_text") or "")
    block_count = int(stats.get("block_count") or 0)
    execution_info = ToolExecutionInfo(mode="docker_mcp", fallback_used=False)
    geospatial_result = {
        "type": "ocr",
        "imagery_id": args.imagery_id,
        "bounds": read_bounds(imagery_dir / "metadata.json"),
        "stats": {
            "block_count": block_count,
            "char_count": int(stats.get("char_count") or len(full_text)),
            "avg_confidence": stats.get("avg_confidence"),
            "min_confidence_seen": stats.get("min_confidence_seen"),
            "grayscale": bool(stats.get("grayscale")),
        },
        "execution": execution_info.model_dump(exclude_none=True),
    }
    return ToolRunResult(
        tool_context=format_ocr_context(args.imagery_id, stats, max_chars=max_chars),
        result_count=block_count,
        query=f"ocr_recognize({args.imagery_id})",
        geospatial_result=geospatial_result,
        artifacts=[AgentArtifact(type="geospatial", payload=geospatial_result)],
        metadata=execution_metadata("docker_mcp"),
    )


def _client(settings) -> RSToolsMCPClient:
    return RSToolsMCPClient(
        image=settings.rs_doc_mcp_image,
        timeout_seconds=settings.rs_doc_docker_timeout_seconds,
        memory_limit=settings.rs_doc_mcp_memory_limit,
        cpus=settings.rs_doc_mcp_cpus,
        network=settings.rs_doc_mcp_network,
    )


def _error_result(message: str, code: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=message,
        error=code,
        metadata=execution_metadata("failed", error_code=code),
    )
