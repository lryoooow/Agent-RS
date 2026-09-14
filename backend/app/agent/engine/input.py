"""Build the complete request-scoped input consumed by AutoGen teams."""

from __future__ import annotations

from dataclasses import dataclass, field

from autogen_core.models import AssistantMessage, LLMMessage, SystemMessage, UserMessage

from app.agent.engine.context import BudgetedChatCompletionContext
from app.agent.prompting.scenarios import latest_user_text
from app.agent.request_builder import build_provider_request_context
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
    if request.analysis_roi is not None:
        if request.analysis_roi.kind == "geo":
            trusted_tool_arguments["segment_landcover"] = {
                "bbox": list(request.analysis_roi.bbox or ()),
                "bbox_crs": "EPSG:4326",
                "pixel_bbox": None,
            }
        else:
            trusted_tool_arguments["segment_landcover"] = {
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
