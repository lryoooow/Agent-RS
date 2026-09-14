from __future__ import annotations

import logging

from app.agent.geocode import forward_geocode
# 对话控图产物经 ToolRunResult.metadata 回流（与 geospatial_result 同款数据通道），
# 由 engine/tools.py 包装层转移到回合状态——业务 runner 不感知编排层。
from app.agent.tools.look_at_location.schema import LookAtLocationArguments
from app.agent.types import ToolRunResult

logger = logging.getLogger(__name__)


async def run_look_at_location(args: LookAtLocationArguments) -> ToolRunResult:
    """地名 → 坐标，写入回合状态供 mid-stream 发 map_control。"""
    geo = await forward_geocode(args.query)
    if geo is None:
        return ToolRunResult(
            tool_context=f"未找到地点「{args.query}」，无法定位。",
            error="location_not_found",
            metadata={"error_code": "location_not_found", "query": args.query},
        )

    center = geo["center"]
    map_target: dict = {"center": center}
    if args.zoom is not None:
        map_target["zoom"] = args.zoom
    elif "zoom" in geo:
        map_target["zoom"] = geo["zoom"]
    if geo.get("bbox"):
        map_target["bbox"] = geo["bbox"]

    label = geo.get("display_name") or args.query
    return ToolRunResult(
        tool_context=f"已定位到「{label}」（中心坐标 [{center[0]:.4f}, {center[1]:.4f}]），地图已跳转。",
        result_count=1,
        query=f"LookAt({args.query})",
        metadata={"map_target": map_target, "display_name": label},
    )
