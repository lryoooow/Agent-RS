"""把本对话此前持久化的结构化分析结果，整形成一段可注入答复上下文的中文摘要。

数据来自 list_recent_analysis_results（助手消息 metadata 里的 geospatial_result/tool_result，
均为工具 runner 当时返回的原始 dict）。本模块只做"读已有真实数值 → 紧凑文本"，
不重算、不补值、不编造——缺字段就略过该字段，确保注入上下文的全是真实发生过的结果。
"""
from __future__ import annotations

from typing import Any


def _fmt_pct(value: Any) -> str | None:
    return f"{value:.2f}%" if isinstance(value, (int, float)) else None


def _fmt_num(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return f"{value:.4g}"
    return None


def _summarize_segmentation(geo: dict[str, Any]) -> str:
    parts = []
    classes = geo.get("classes") or []
    for item in classes:
        if not isinstance(item, dict):
            continue
        label = item.get("label") or item.get("name") or "未知类别"
        pct = _fmt_pct(item.get("percentage"))
        parts.append(f"{label} {pct}" if pct else str(label))
    body = "；".join(parts) if parts else "未识别到地物类别"
    return f"地物分类（LandCover.ai 四类）：{body}"


def _summarize_detection(geo: dict[str, Any]) -> str:
    total = geo.get("detection_count")
    parts = []
    for item in geo.get("classes") or []:
        if not isinstance(item, dict):
            continue
        label = item.get("label") or item.get("name") or "未知"
        count = item.get("count")
        parts.append(f"{label}×{count}" if count is not None else str(label))
    detail = ("，".join(parts)) if parts else "无类别明细"
    total_text = f"共 {total} 个目标" if total is not None else "目标数未知"
    return f"目标检测（DOTA 15 类）：{total_text}（{detail}）"


def _summarize_index(geo: dict[str, Any], *, default_label: str) -> str:
    stats = geo.get("stats") or {}
    index_type = geo.get("index_type") or stats.get("index_type") or default_label
    pieces = []
    for key in ("min", "max", "mean", "std"):
        num = _fmt_num(stats.get(key))
        if num is not None:
            pieces.append(f"{key}={num}")
    detail = "，".join(pieces) if pieces else "统计缺失"
    return f"{index_type} 指数：{detail}"


def _summarize_raster_inspect(tool: dict[str, Any]) -> str:
    bits = []
    if tool.get("width") and tool.get("height"):
        bits.append(f"{tool['width']}x{tool['height']}px")
    if tool.get("band_count"):
        bits.append(f"{tool['band_count']} 波段")
    if tool.get("crs"):
        bits.append(f"CRS {tool['crs']}")
    detail = "，".join(bits) if bits else "基本信息缺失"
    return f"影像质检：{detail}"


def _summarize_entry(entry: dict[str, Any]) -> str | None:
    """单条持久化结果 → 一行摘要（含影像 ID 前缀）；无法识别则返回 None。"""
    geo = entry.get("geospatial_result")
    tool = entry.get("tool_result")
    imagery_id = None
    summary = None
    if isinstance(geo, dict):
        imagery_id = geo.get("imagery_id")
        geo_type = geo.get("type")
        if geo_type == "segmentation":
            summary = _summarize_segmentation(geo)
        elif geo_type == "detection":
            summary = _summarize_detection(geo)
        elif geo_type == "ndvi":
            summary = _summarize_index(geo, default_label="NDVI")
        elif geo_type == "spectral_index":
            summary = _summarize_index(geo, default_label="光谱")
        elif geo_type == "composite":
            mode = geo.get("mode") or "波段组合"
            summary = f"波段组合渲染：{mode}"
        elif geo_type == "report":
            summary = "已生成分析报告（含下载链接）"
    if summary is None and isinstance(tool, dict):
        imagery_id = imagery_id or tool.get("imagery_id")
        if tool.get("type") == "raster_inspect":
            summary = _summarize_raster_inspect(tool)
    if summary is None:
        return None
    if imagery_id:
        return f"- 影像 {imagery_id}：{summary}"
    return f"- {summary}"


def summarize_persisted_analyses(results: list[dict[str, Any]]) -> str | None:
    """把多条持久化分析结果整形成上下文文本块正文；无可用结果返回 None。"""
    lines = [line for entry in results if (line := _summarize_entry(entry))]
    if not lines:
        return None
    return "\n".join(lines)
