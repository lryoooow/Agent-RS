"""跨轮分析结果抽取：把助手消息 metadata 里持久化的结构化工具结果挑出来。

_pg 的 list_recent_analysis_results 复用此纯函数（与仓储 SQL 解耦，便于单测）。
metadata 经 parse_jsonb 归一为 dict|None（损坏/缺失 → None，自然跳过，不抛错）。
"""
from __future__ import annotations

from typing import Any

from app.db.sanitize import parse_jsonb


def collect_analysis_results(raw_metadatas: list[Any], *, limit: int) -> list[dict[str, Any]]:
    """从（按时间倒序的）metadata 列表里抽出含分析结果的条目，返回按时间正序的 limit 条。

    入参 raw_metadatas 为 DB 读回的 metadata_json 原值（字符串/已解析 dict/None 皆可），
    倒序排列（最近的在前）。只保留含 geospatial_result 或 tool_result 的条目，
    每条归一成 {"geospatial_result": ..., "tool_result": ...}（缺失键不带）。
    取最近 limit 条后反转为正序，便于上层按对话时间顺序叙述。
    """
    collected: list[dict[str, Any]] = []
    for raw in raw_metadatas:
        if len(collected) >= limit:
            break
        metadata = parse_jsonb(raw)
        if not metadata:
            continue
        entry: dict[str, Any] = {}
        geospatial = metadata.get("geospatial_result")
        tool = metadata.get("tool_result")
        if isinstance(geospatial, dict) and geospatial:
            entry["geospatial_result"] = geospatial
        if isinstance(tool, dict) and tool:
            entry["tool_result"] = tool
        if entry:
            collected.append(entry)
    collected.reverse()
    return collected
