"""Build the complete request-scoped input consumed by AutoGen teams."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from autogen_core.models import AssistantMessage, LLMMessage, SystemMessage, UserMessage

from app.agent.engine.context import BudgetedChatCompletionContext
from app.agent.prompting.scenarios import latest_user_text
from app.agent.request_builder import build_provider_request_context
from app.agent.imagery_access import user_owns_imagery, get_user_imagery_metadata
from app.agent.imagery_selection import use_current_selection, geo_roi_mismatch
from app.agent.tool_registry import TOOLS
from app.schemas.chat import ChatRequest


@dataclass(frozen=True)
class TurnInput:
    query: str
    initial_messages: tuple[LLMMessage, ...]
    trusted_tool_arguments: dict[str, dict] = field(default_factory=dict)
    # 用户是否持有影像。默认 True 是刻意保守：未标注时宁可多跑一次路由，
    # 也不能让快车道静默关掉 GraphFlow 通道（只有 build_turn_input 会如实设置）。
    has_imagery: bool = True

    def context(self) -> BudgetedChatCompletionContext:
        # Every Agent and the group manager need their own mutable context.
        return BudgetedChatCompletionContext(list(self.initial_messages))


async def build_turn_input(request: ChatRequest, *, user_id: str | None) -> TurnInput:
    """Load history and trusted context once, leaving RAG/memory to AutoGen Memory.

    ``build_provider_request_context`` remains the single implementation for history
    ownership, prompt modules, map context, inventories, prior analysis and budgets.
    Retrieval is deliberately skipped here because RagMemory/PgVectorMemory inject it
    immediately before every Agent model call.
    """
    provider = await build_provider_request_context(
        request,
        user_id=user_id,
        skip_retrieval=True,
    )
    query = latest_user_text(request.messages)
    messages = list(provider.messages)

    # The latest user message is the AutoGen task.  Keeping it in initial context as
    # well would duplicate the instruction and distort retrieval queries.
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            messages.pop(index)
            break

    initial: list[LLMMessage] = []
    for message in messages:
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        role = message.get("role")
        if role == "system":
            initial.append(SystemMessage(content=content))
        elif role == "assistant":
            initial.append(AssistantMessage(content=content, source="assistant_history"))
        else:
            initial.append(UserMessage(content=content, source="user"))
    trusted_tool_arguments: dict[str, dict] = {}
    active_id = (request.metadata or {}).get("active_imagery_id")
    source = (request.metadata or {}).get("analysis_source")
    map_source = bool(request.analysis_roi and request.analysis_roi.kind == "geo"
                      and (source == "current_map" or (not active_id and source != "selected_imagery"))
                      and not re.search(r"当前影像|这张影像|\b[a-f0-9]{12}\b|\.tiff?\b", query, re.I))
    if map_source:
        initial.append(SystemMessage(content="用户已框选地图卫星底图区域。若要求对该选区提取、分类或检测，先调用 prepare_map_roi 获取选区影像，再用其 imagery_id 执行适用分析；无需上传、选择或搜索已有影像。用户只问概念时不取图；用户要求检索其他时相/传感器影像时使用 search_imagery。底图只有 RGB，没有 NIR/SWIR，原始分辨率和日期未知。"))
        trusted_tool_arguments["prepare_map_roi"] = {"bbox": list(request.analysis_roi.bbox)}
        if use_current_selection(query):
            for name, tool in TOOLS.items():
                if "imagery_id" in tool.argument_model.model_fields and name != "generate_report":
                    trusted_tool_arguments[name] = {"imagery_id": "map_roi_pending"}
    if not map_source and "active_imagery_id" in (request.metadata or {}) and active_id is None:
        initial.append(SystemMessage(content="界面当前未选中分析影像。用户未指定明确影像 ID 或名称时，应提示使用当前分析影像选择器；不要把历史结果或地图中心当作当前选中影像。"))
    if not map_source and isinstance(active_id, str) and await user_owns_imagery(active_id, user_id):
        initial.append(SystemMessage(content=f"当前选中影像 ID: {active_id}（已核实归属）。用户说当前影像时使用此 ID；位置以影像清单或质检的 WGS84 四至为准，不能用地图视角替代。"))
        meta = await get_user_imagery_metadata(active_id, user_id)
        if use_current_selection(query):
            for name, tool in TOOLS.items():
                if "imagery_id" in tool.argument_model.model_fields and name != "generate_report":
                    trusted_tool_arguments[name] = {"imagery_id": active_id}
                    for role, index in ((meta or {}).get("band_roles") or {}).items():
                        field_name = role + "_band"
                        if field_name in tool.argument_model.model_fields:
                            trusted_tool_arguments[name][field_name] = index
        if meta and request.analysis_roi and request.analysis_roi.kind == "geo" and geo_roi_mismatch(meta.get("bounds"), request.analysis_roi.bbox):
            initial.append(SystemMessage(content="当前框选与选中影像不相交。不能在此影像执行该选区提取；应使用覆盖选区的可用影像或检索新场景。重复提交相同影像和选区不会成功，不要自行改选区。"))
    if request.analysis_roi is not None:
        initial.append(SystemMessage(content=f"用户当前选区: {request.analysis_roi.model_dump_json(exclude_none=True)}。分割工具将按该选区实际裁切计算。"))
        if request.analysis_roi.kind == "geo":
            trusted_tool_arguments["segment_instances"] = {
                **trusted_tool_arguments.get("segment_instances", {}),
                "bbox": list(request.analysis_roi.bbox or ()),
                "bbox_crs": "EPSG:4326",
                "pixel_bbox": None,
            }
        else:
            trusted_tool_arguments["segment_instances"] = {
                **trusted_tool_arguments.get("segment_instances", {}),
                "pixel_bbox": list(request.analysis_roi.rel or ()),
                "bbox": None,
                "bbox_crs": None,
            }
    return TurnInput(
        query=query,
        initial_messages=tuple(initial),
        trusted_tool_arguments=trusted_tool_arguments,
        # getattr 而非直接取属性：测试用 SimpleNamespace 伪造 provider；
        # 缺标注时按"可能有影像"处理（与 TurnInput.has_imagery 的保守默认一致）。
        has_imagery=bool(getattr(provider, "has_imagery", True)),
    )
