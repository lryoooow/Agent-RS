from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.agent.tools.cloud_mask.formatter import format_cloud_mask_context
from app.agent.tools.cloud_mask.schema import CloudMaskArguments
from app.agent.tools.common import (
    IMAGERY_ID_PATTERN, classify_rs_tool_failure, execution_metadata, imagery_not_found_result,
    invalid_bands_result, invalid_imagery_id_result, read_bounds, resolve_imagery_paths, validate_band_indices,
)
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient
from app.schemas.chat import ToolExecutionInfo
from app.services.raster_semantics import resolve_spectral_bands

logger = logging.getLogger(__name__)
QUALITY_TYPES = {"sentinel2_scl": "sentinel2", "landsat_c2_qa_pixel": "landsat"}


class QualityInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _quality_payload(source_path: Path, imagery_dir: Path) -> dict:
    """Only backend-owned sidecar metadata can select QA. No LLM path/type input."""
    import numpy as np
    import rasterio

    missing = "当前影像没有可信的传感器QA/SCL质量产品，无法提供云/云影统计；请导入附带质量产品的卫星影像。"
    try:
        meta = json.loads((imagery_dir / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise QualityInputError("quality_mask_unavailable", missing) from None
    if not isinstance(meta, dict) or not isinstance(meta.get("quality_mask"), dict):
        raise QualityInputError("quality_mask_unavailable", missing)
    qa_meta = meta["quality_mask"]
    kind = qa_meta.get("type")
    if (meta.get("source_origin") != "stac_composition" or not isinstance(kind, str) or kind not in QUALITY_TYPES
            or qa_meta.get("filename") != "quality.tif" or qa_meta.get("source") != QUALITY_TYPES[kind]
            or not qa_meta.get("item_id") or qa_meta.get("item_id") != meta.get("source_item_id")
            or not qa_meta.get("scene_key") or qa_meta.get("scene_key") != meta.get("source_scene_key")):
        raise QualityInputError("quality_mask_invalid", "QA质量产品的类型、来源或场景归属不一致，未执行云分析。")
    qa_path = imagery_dir / "quality.tif"
    if (qa_path.resolve().parent != source_path.resolve().parent or qa_path.resolve().parent != imagery_dir.resolve()):
        raise QualityInputError("quality_mask_invalid", "QA质量产品不属于当前影像目录，未执行云分析。")
    if not qa_path.is_file():
        raise QualityInputError("quality_mask_unavailable", missing)
    try:
        with rasterio.open(source_path) as src, rasterio.open(qa_path) as qa:
            if (qa.width, qa.height, qa.crs, qa.transform) != (src.width, src.height, src.crs, src.transform):
                raise QualityInputError("quality_mask_invalid", "QA质量产品与分析影像的网格不一致，未执行云分析。")
            if qa.count != 1 or not np.issubdtype(np.dtype(qa.dtypes[0]), np.unsignedinteger):
                raise QualityInputError("quality_mask_invalid", "QA质量产品必须是单通道无符号整数分类栅格。")
            tags = qa.tags()
            if (tags.get("QA_TYPE") != kind or tags.get("QA_SOURCE") != qa_meta["source"]
                    or tags.get("QA_ITEM_ID") != qa_meta["item_id"] or not tags.get("QA_SENSOR")):
                raise QualityInputError("quality_mask_invalid", "QA栅格标签与平台登记的来源不一致，未执行云分析。")
            norm = lambda value: str(value).lower().replace("-", "").replace(" ", "")
            sensor = meta.get("sensor") or src.tags().get("SENSOR")
            if not sensor or norm(sensor) != norm(tags["QA_SENSOR"]):
                raise QualityInputError("quality_mask_invalid", "QA质量产品与分析影像的传感器不一致。")
    except QualityInputError:
        raise
    except Exception:
        raise QualityInputError("quality_mask_invalid", "QA质量产品无法读取，未执行云分析。") from None
    return {"method": "quality", "quality_path": "/data/quality.tif", "quality_type": kind}


async def run_cloud_mask(args: CloudMaskArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("云/阴影掩膜")
    source_path, imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    settings = get_settings()
    if not settings.rs_tools_mcp_use_docker:
        return _error_result("云/阴影掩膜失败: RS Tools Docker MCP 未启用。", "mcp_disabled")
    if args.method == "quality":
        try:
            payload = await asyncio.to_thread(_quality_payload, source_path, imagery_dir)
        except QualityInputError as exc:
            return _error_result(str(exc), exc.code)
        except (OSError, ValueError, TypeError):
            return _error_result("QA质量产品登记内容无法解析，未执行云分析。", "quality_mask_invalid")
    else:
        try:
            bands = await asyncio.to_thread(
                resolve_spectral_bands, source_path,
                {"red": args.red_band, "green": args.green_band, "blue": args.blue_band, "nir": args.nir_band},
                explicit={"red_band", "green_band", "blue_band", "nir_band"} & args.model_fields_set,
            )
        except ValueError as exc:
            return _error_result(f"疑似亮暗区粗筛失败: {exc}", getattr(exc, "code", "band_roles_unknown"))
        band_error = await validate_band_indices(source_path, bands)
        if band_error:
            return invalid_bands_result("疑似亮暗区粗筛", band_error)
        payload = {"method": "heuristic", **{f"{role}_band": index for role, index in bands.items()}}
    results_dir.mkdir(parents=True, exist_ok=True)
    try:
        stats = await _client(settings).call_tool(
            "cloud_shadow_mask", source_path=source_path, output_dir=results_dir, arguments=payload,
        )
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("Cloud quality processing failed: %s", exc)
        code, message = classify_rs_tool_failure(exc)
        if "quality_mask_unavailable" in str(exc):
            code, message = "quality_mask_unavailable", "当前影像缺少QA/SCL质量产品，无法提供云/云影统计。"
        elif "quality_mask_invalid" in str(exc):
            code, message = "quality_mask_invalid", "QA质量产品的类型、网格或来源不匹配，未执行云分析。"
        return _error_result(message or "云/阴影质量产品读取失败，请检查影像与服务状态。", code)
    except Exception:
        logger.exception("Cloud quality processing unexpected failure")
        return _error_result("云/阴影质量产品读取失败，请检查影像与服务状态。", "unexpected_error")
    expected_method = "quality_mask" if args.method == "quality" else "heuristic"
    if not isinstance(stats, dict) or stats.get("method") != expected_method:
        return _error_result("云分析服务返回的方法与请求不一致，请更新工具服务后再执行。", "invalid_tool_result")
    if args.method == "quality" and stats.get("quality_type") != payload["quality_type"]:
        return _error_result("云分析服务返回的QA类型与当前影像不一致。", "invalid_tool_result")
    if args.method == "heuristic" and any(stats.get(key) is not None for key in ("cloud_pct", "shadow_pct", "clear_pct")):
        return _error_result("未验证的亮暗粗筛不能返回确定云量或晴空比例。", "invalid_tool_result")
    result_filename = str(stats.get("output_png") or "")
    if not result_filename or Path(result_filename).name != result_filename:
        return _error_result("云分析服务没有返回有效结果文件。", "invalid_tool_result")
    heuristic = args.method == "heuristic"
    if heuristic:
        stats = {**stats, "resolved_bands": bands}
    names = ["未命中规则", "疑似高亮", "疑似暗区", "无效", "未知", "雪冰", "地形阴影"] if heuristic else [
        "QA未标记云/云影", "云标记", "云影标记", "无效", "未知/未分类", "雪冰", "地形阴影",
    ]
    execution_info = ToolExecutionInfo(mode="docker_mcp", fallback_used=False)
    geospatial_result = {
        "type": "cloud_mask", "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": read_bounds(imagery_dir / "metadata.json"),
        "stats": {key: value for key, value in stats.items() if key not in {"output_tif", "output_png"}},
        "execution": execution_info.model_dump(exclude_none=True),
        "legend": {"label": "未验证疑似亮暗区" if heuristic else "传感器云/云影质量产品",
                   "classes": [{"code": code, "name": name} for code, name in enumerate(names)]},
    }
    return ToolRunResult(
        tool_context=format_cloud_mask_context(args.imagery_id, stats, result_filename), result_count=1,
        query=f"cloud_shadow_mask({args.imagery_id}, method={args.method})", geospatial_result=geospatial_result,
        artifacts=[AgentArtifact(type="geospatial", payload=geospatial_result)], metadata=execution_metadata("docker_mcp"),
    )


def _client(settings) -> RSToolsMCPClient:
    return RSToolsMCPClient(image=settings.rs_tools_mcp_image, timeout_seconds=settings.rs_tools_docker_timeout_seconds,
                            memory_limit=settings.rs_tools_mcp_memory_limit, cpus=settings.rs_tools_mcp_cpus,
                            network=settings.rs_tools_mcp_network)


def _error_result(message: str, code: str) -> ToolRunResult:
    return ToolRunResult(tool_context=message, error=code, metadata=execution_metadata("failed", error_code=code))
