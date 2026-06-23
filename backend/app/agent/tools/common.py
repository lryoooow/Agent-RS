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
    return None


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
