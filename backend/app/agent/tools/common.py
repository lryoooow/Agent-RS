from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.agent.types import ToolRunResult
from app.core.paths import imagery_root

IMAGERY_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


def resolve_imagery_paths(imagery_id: str) -> tuple[Path | None, Path, Path]:
    # staging 感知：minio 后端下工具调用前已把影像拉到请求级临时目录（见 tools/staging.py），
    # 此时用临时目录；local 后端 staged 为 None，走原逻辑（imagery_root 子目录），行为零变化。
    from app.agent.tools.staging import staged_imagery_dir

    imagery_dir = staged_imagery_dir(imagery_id) or (imagery_root() / imagery_id)
    source_path = imagery_dir / "working.tif"
    if not source_path.exists():
        source_path = imagery_dir / "source.tif"
    return (source_path if source_path.exists() else None), imagery_dir, imagery_dir / "results"


def invalid_imagery_id_result(tool_name: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=f"{tool_name} 参数无效: imagery_id 必须是 12 位十六进制影像 ID。",
        error="invalid_imagery_id",
        metadata={"error_code": "invalid_imagery_id", "execution_mode": "failed"},
    )


def _read_band_count(source_path: Path) -> int:
    """同步读取影像波段数（rasterio.open 阻塞 I/O，供 to_thread 调用）。"""
    import rasterio

    with rasterio.open(source_path) as src:
        return src.count


async def validate_band_indices(source_path: Path, bands: dict[str, int]) -> str | None:
    """Validate 1-based raster band indices against the source image."""
    below_range = {name: index for name, index in bands.items() if index < 1}
    if below_range:
        return f"波段索引必须从 1 开始，当前 {below_range}"

    band_count = await asyncio.to_thread(_read_band_count, source_path)
    over_range = {name: index for name, index in bands.items() if index > band_count}
    if over_range:
        return f"影像只有 {band_count} 个波段，无法使用 {over_range}"
    def semantic_error():
        from app.services.raster_semantics import band_semantics, validate_spectral_selection
        try:
            validate_spectral_selection(band_semantics(source_path), bands)
        except ValueError as exc:
            return str(exc)
        return None
    return await asyncio.to_thread(semantic_error)


def invalid_bands_result(tool_name: str, detail: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=f"{tool_name}参数无效: {detail}",
        error="invalid_bands",
        metadata={"error_code": "invalid_bands", "execution_mode": "failed"},
    )


def imagery_not_found_result(imagery_id: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=f"影像 {imagery_id} 不存在，请先上传影像。",
        error="imagery_not_found",
        metadata={"error_code": "imagery_not_found", "execution_mode": "failed"},
    )


def read_bounds(meta_path: Path) -> tuple[float, float, float, float] | None:
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    bounds = meta.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 4:
        return None
    try:
        return tuple(float(value) for value in bounds)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def execution_metadata(mode: str, *, fallback_used: bool = False, error_code: str | None = None) -> dict[str, Any]:
    return {
        "execution_mode": mode,
        "fallback_used": fallback_used,
        "error_code": error_code,
    }


def classify_rs_tool_failure(exc: Exception) -> tuple[str, str]:
    """把 rs_tools 容器带回的错误文本映射成 (错误码, 面向用户文案)。

    compute 侧在 raster_utils.py 里用 "uncalibrated_input:" /
    "all_pixels_invalid:" / "stale_s2_composite:" 前缀标记确定性输入问题，
    文本经 MCP isError 消息原样带回；不匹配任何前缀时归为通用 mcp_error
    （保留原日志侧详情）。
    """
    text = str(exc)
    if "artifact_publication_failed" in text:
        return "artifact_publication_failed", "分析计算已结束，但产物保存失败；尚未生成可用下载入口，请检查存储状态。"
    if "invalid_calibration" in text:
        return "invalid_calibration", "影像定标参数不完整、非法或存在冲突，本次没有执行可信指数分析；请提供一致的逐波段定标信息。"
    if "stale_s2_composite" in text:
        return (
            "stale_s2_composite",
            "该 Sentinel-2 影像缺少可靠反射率定标来源；成像日期不能证明处理基线，"
            "本次未直接使用原始DN计算。平台导入的场景请重新导入；自行上传的文件请提供反射率单位或逐波段定标参数。",
        )
    if "uncalibrated_input" in text:
        return (
            "uncalibrated_input",
            "影像缺少定标信息（无法换算反射率），该计算需要反射率输入；"
            "请提供明确的反射率单位或逐波段定标参数，传感器名称本身不能证明已定标。",
        )
    if "all_pixels_invalid" in text:
        return (
            "all_pixels_invalid",
            "影像没有数学有效像素（无效掩膜、NaN、零分母或非法计算域），无法提供可信统计；请检查数据和参数。",
        )
    return "mcp_error", ""


PROVENANCE_FIELDS = ("calibration", "calibrated", "method_version", "valid_pixels", "total_pixels",
                     "nodata_pixels", "input_valid_pixels", "math_invalid_pixels", "nodata_pct", "percentage_denominator", "out_of_range_pct")


def provenance_stats(stats: dict[str, Any], resolved_bands: dict[str, int]) -> dict[str, Any]:
    return {**{key: stats[key] for key in PROVENANCE_FIELDS if key in stats},
            "resolved_bands": dict(resolved_bands)}


def format_spectral_provenance(stats: dict[str, Any]) -> list[str]:
    lines = []
    if "calibrated" in stats:
        label = "反射率（已有明确单位或已按来源参数校准）" if stats["calibrated"] else "未校准DN的相对指数；不能作为定量反射率指标"
        lines.append(f"- 输入量纲: {label}")
    if stats.get("resolved_bands"):
        lines.append(f"- 实际波段: {stats['resolved_bands']}")
    if stats.get("method_version"):
        lines.append(f"- 方法版本: {stats['method_version']}")
    if "valid_pixels" in stats:
        lines.append(f"- 数学有效像素: {stats['valid_pixels']} / {stats.get('total_pixels', '未知')}；输入有效但计算无定义: {stats.get('math_invalid_pixels', 0)}")
    calibration = stats.get("calibration") or {}
    for role, record in (calibration.get("bands") or {}).items():
        lines.append(f"- {role} 定标依据: {record}")
    return lines
