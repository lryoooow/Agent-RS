from __future__ import annotations

import asyncio
import logging

from app.agent.tools.common import (
    IMAGERY_ID_PATTERN,
    classify_rs_tool_failure,
    execution_metadata,
    provenance_stats,
    imagery_not_found_result,
    invalid_bands_result,
    invalid_imagery_id_result,
    read_bounds,
    resolve_imagery_paths,
    validate_band_indices,
)
from app.agent.tools.spectral_index.formatter import format_spectral_index_context
from app.agent.tools.spectral_index.schema import SpectralIndexArguments, required_bands_for
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient
from app.schemas.chat import ToolExecutionInfo
from app.services.raster_semantics import BandResolutionError, band_semantics, resolve_spectral_bands

logger = logging.getLogger(__name__)


async def run_spectral_index(args: SpectralIndexArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("光谱指数计算")
    source_path, imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    results_dir.mkdir(parents=True, exist_ok=True)

    # 波段角色解析（A4）：模型显式给出的波段参数优先；未显式给出的用影像
    # band_roles 覆盖 GF-2 默认值。当前指数需要的角色缺失且未显式给出才会
    # 报 band_roles_unknown；用不到的角色缺失时保留默认值（不影响计算）。
    requested_defaults = {
        "blue": args.blue_band,
        "green": args.green_band,
        "red": args.red_band,
        "nir": args.nir_band,
        "swir1": args.swir1_band if args.swir1_band is not None else args.swir_band,
        "swir2": args.swir2_band if args.swir2_band is not None else args.swir_band,
    }
    required_roles = required_bands_for(
        args.index_type,
        blue_band=args.blue_band,
        green_band=args.green_band,
        red_band=args.red_band,
        nir_band=args.nir_band,
        swir_band=args.swir_band,
        swir1_band=args.swir1_band,
        swir2_band=args.swir2_band,
    )
    try:
        explicit = {role + "_band" for role in requested_defaults
                    if role + "_band" in args.model_fields_set and getattr(args, role + "_band") is not None}
        if "swir_band" in args.model_fields_set:
            semantics = await asyncio.to_thread(band_semantics, source_path)
            for role in required_roles:
                if role in {"swir1", "swir2"}:
                    if role + "_band" in explicit and requested_defaults[role] != args.swir_band:
                        raise BandResolutionError("invalid_bands", "旧 SWIR 参数与明确波长参数冲突。")
                    if role not in (semantics.get("band_roles") or {}) and role + "_band" not in explicit:
                        raise BandResolutionError("band_roles_unknown", "旧 swir_band 没有波长定义；需要明确 swir1_band 或 swir2_band，不能将 SWIR1/SWIR2 混同。")
                    explicit.add(role + "_band")
        bands = await asyncio.to_thread(
            resolve_spectral_bands,
            source_path,
            requested_defaults,
            explicit=explicit,
            required=set(required_roles),
        )
    except ValueError as exc:
        return _error_result(f"光谱指数计算失败: {exc}", getattr(exc, "code", "band_roles_unknown"))

    # 只校验本指数必需的角色；非必需角色（如 ndwi 不用的 swir）不阻塞。
    band_error = await validate_band_indices(
        source_path, {role: bands[role] for role in required_roles}
    )
    if band_error:
        return invalid_bands_result("光谱指数计算", band_error)

    settings = get_settings()
    if not settings.rs_tools_mcp_use_docker:
        return _error_result("光谱指数计算失败: RS Tools Docker MCP 未启用。", "mcp_disabled")
    payload = {
        "index_type": args.index_type,
        "blue_band": bands["blue"],
        "green_band": bands["green"],
        "red_band": bands["red"],
        "nir_band": bands["nir"],
        "swir_band": bands.get("swir2" if args.index_type == "nbr" else "swir1", args.swir_band),
    }
    try:
        stats = await _client(settings).call_tool(
            "calculate_spectral_index",
            source_path=source_path,
            output_dir=results_dir,
            arguments=payload,
        )
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("Spectral index failed: %s", exc)
        code, classified_message = classify_rs_tool_failure(exc)
        return _error_result(
            classified_message or "光谱指数计算失败，请稍后重试或检查影像与服务状态。", code
        )
    except Exception as exc:
        logger.exception("Spectral index unexpected error: %s", exc)
        return _error_result("光谱指数计算失败，请稍后重试或检查影像与服务状态。", "unexpected_error")

    stats = {**stats, "resolved_bands": {role: bands[role] for role in required_roles}}
    result_filename = str(stats.get("output_png") or f"{args.index_type}_colored.png")
    execution_info = ToolExecutionInfo(mode="docker_mcp", fallback_used=False)
    geospatial_result = {
        "type": "spectral_index",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": read_bounds(imagery_dir / "metadata.json"),
        "index_type": args.index_type,
        "stats": {
            **provenance_stats(stats, {role: bands[role] for role in required_roles}),
            "index_type": args.index_type,
            "min": stats.get("min"),
            "max": stats.get("max"),
            "mean": stats.get("mean"),
            "std": stats.get("std"),
            "nodata_pct": stats.get("nodata_pct", 0.0),
            "calibrated": stats.get("calibrated", False),
            "resolved_bands": {role: bands[role] for role in required_roles},
            "out_of_range_pct": stats.get("out_of_range_pct", 0.0),
        },
        "execution": execution_info.model_dump(exclude_none=True),
        "legend": _legend(args.index_type),
    }
    return ToolRunResult(
        tool_context=format_spectral_index_context(args.imagery_id, args.index_type, stats, result_filename),
        result_count=1,
        query=f"{args.index_type.upper()}({args.imagery_id})",
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


def _legend(index_type: str) -> dict:
    normalized = index_type.lower()
    ranges = {
        "ndwi": (-1.0, 1.0, "water"),
        "mndwi": (-1.0, 1.0, "water"),
        "ndbi": (-1.0, 1.0, "built"),
        "evi": (-1.0, 2.5, "vegetation"),
        "savi": (-1.0, 1.5, "vegetation"),
        "gndvi": (-1.0, 1.0, "vegetation"),
        "msavi": (-1.0, 1.0, "vegetation"),
        "ndmi": (-1.0, 1.0, "water"),
        "nbr": (-1.0, 1.0, "burn"),
        "bsi": (-1.0, 1.0, "built"),
    }
    low, high, palette = ranges.get(normalized, (-1.0, 1.0, "spectral"))
    return {
        "label": normalized.upper(),
        "min": low,
        "max": high,
        "palette": palette,
    }
