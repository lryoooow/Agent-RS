"""fetch_scene 的注册表 runner：场景导入影像库（与 API 路由共用 importer）。"""

from __future__ import annotations

import logging

from app.agent.stac_search.cache import get_scene
from app.agent.stac_search.importer import SceneImportError, import_scene_as_imagery
from app.agent.tools.scene_fetch.schema import SceneFetchArguments
from app.agent.types import ToolRunResult
from app.auth import peek_current_user_id

logger = logging.getLogger(__name__)


async def run_scene_fetch(args: SceneFetchArguments) -> ToolRunResult:
    user_id = peek_current_user_id()
    record = get_scene(user_id, args.scene_key)
    if record is None:
        return ToolRunResult(
            tool_context=(
                f"场景 {args.scene_key} 不存在或已过期。请重新调用 search_imagery，"
                "并把新结果里的 key 告知用户。不要假装已导入。"
            ),
            query=args.reason,
            error="scene_not_found",
        )

    try:
        result = await import_scene_as_imagery(record, user_id)
    except SceneImportError as exc:
        return ToolRunResult(
            tool_context=f"场景导入失败：{exc}。请如实告知用户，不要编造结果。",
            query=args.reason,
            error="scene_import_failed",
        )

    roles = result["band_roles"]
    grid = result.get("analysis_grid") or {}
    geospatial = {"type": "preview", "imagery_id": result["imagery_id"],
                  "result_url": result.get("preview_url") or "", "bounds": result.get("bounds")}
    return ToolRunResult(
        tool_context=(
            f"已导入「{result['satellite']} {result['item_id']}」为平台影像 "
            f"（ID: {result['imagery_id']}，波段角色："
            + "，".join(f"{role}=B{index}" for role, index in sorted(roles.items(), key=lambda kv: kv[1]))
            + f"）。当前分析网格 {grid.get('width', '未知')}×{grid.get('height', '未知')}，实际像元 {grid.get('pixel_size', '未知')}（单位依坐标系）。"
            + "已设为当前分析影像。后续分析使用此 ID 与其波段角色；实际像元不能用传感器标称分辨率替代。"
        ),
        query=args.reason,
        result_count=1,
        geospatial_result=geospatial,
        metadata={"band_roles": roles},
    )
