"""search_imagery 的注册表 runner：检索免账号卫星影像并产出场景卡片。

配额（AGENT_IMAGERY_SEARCH_MAX_CALLS）由 engine/tools.py 的 AutoGen 包装
在执行前 try_reserve 强制；本层只负责检索与卡片组装。
"""

from __future__ import annotations

import logging

from app.agent.geocode import forward_geocode
from app.agent.stac_search import search_scenes
from app.agent.stac_search.cache import put_scenes
from app.agent.stac_search.sources import StacSearchError
from app.agent.tools.imagery_search.schema import ImagerySearchArguments
from app.agent.types import ToolRunResult
from app.auth import peek_current_user_id

logger = logging.getLogger(__name__)


def _card(record) -> dict:
    return {
        "key": record.key,
        "satellite": record.satellite,
        "item_id": record.item_id,
        "datetime": record.datetime,
        "cloud_cover": record.cloud_cover,
        "bbox": record.bbox,
        "resolution_m": record.resolution_m,
        "display_name": record.display_name,
        "preview_url": f"/api/scenes/{record.key}/preview",
        "download_url": f"/api/scenes/{record.key}/download",
    }


async def run_imagery_search(args: ImagerySearchArguments) -> ToolRunResult:
    bbox = args.bbox
    if bbox is None:
        geo = await forward_geocode((args.place or "").strip())
        if geo is None:
            return ToolRunResult(
                tool_context=(
                    f"无法解析地名「{args.place}」。请向用户确认区域名称，或改用范围检索。"
                ),
                query=args.reason,
                error="place_unresolved",
            )
        center = geo["center"]
        bbox = [center[0] - 0.15, center[1] - 0.15, center[0] + 0.15, center[1] + 0.15]

    try:
        records, notes = await search_scenes(
            bbox=bbox,
            start_date=args.start_date,
            end_date=args.end_date,
            cloud_max=args.cloud_max,
            source=args.source,
            limit=args.limit,
        )
    except StacSearchError as exc:
        return ToolRunResult(
            tool_context=f"影像检索暂不可用：{exc}。请如实告知用户，不要编造结果。",
            query=args.reason,
            error="stac_unavailable",
        )

    if not records:
        return ToolRunResult(
            tool_context=(
                "没有找到符合条件 的影像。建议放宽时间范围或提高云量上限后重试；"
                "仍无结果时如实告知用户。"
            ),
            query=args.reason,
            result_count=0,
        )

    # 场景进服务端缓存（user 隔离），预览/下载/导入的 key 从这里取。
    put_scenes(peek_current_user_id(), records)

    lines = [
        f"- {r.key} | {r.display_name} | {r.datetime[:10]} | 云量 {r.cloud_cover}% | {r.resolution_m}m"
        for r in records
    ]
    degrade = f"（注意：{'；'.join(notes)}）" if notes else ""
    return ToolRunResult(
        tool_context=(
            f"找到 {len(records)} 景影像{degrade}：\n" + "\n".join(lines) +
            "\n场景卡片已呈现给用户，可预览/下载（TIF）。要继续分析某一景，"
            "调用 fetch_scene 并传入其 key。"
        ),
        query=args.reason,
        result_count=len(records),
        # 卡片数据走 geospatial_result 通道：SSE → done 载荷 → 落库 metadata，
        # 前端 SceneSearchRow 渲染。URL 只在这里出现（相对路径，无签名令牌）。
        geospatial_result={
            "type": "scene_search",
            "scenes": [_card(r) for r in records],
            "notes": notes,
        },
    )
