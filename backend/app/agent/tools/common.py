from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.agent.types import ToolRunResult
from app.core.paths import imagery_root

IMAGERY_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


def resolve_imagery_paths(imagery_id: str) -> tuple[Path | None, Path, Path]:
    imagery_dir = imagery_root() / imagery_id
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
