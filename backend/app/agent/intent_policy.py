from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agent.config import ResolvedAIConfig
from app.agent.imagery_access import known_imagery_ids_for_user
from app.agent.prompting.scenarios import NDVI_EXPLANATION_TERMS, wants_ndvi_calculation
from app.agent.search.cache import CachedDecision, get_decision_cache
from app.agent.search.classifier import (
    SearchIntent,
    classify_search_intent,
    has_force_search_signal,
)
from app.agent.types import RuntimeAgentCall, RuntimeToolCall
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


IntentAction = Literal["force", "skip", "ask_planner"]
IntentCapabilityKind = Literal["tool", "agent"]

_IMAGERY_ID_PATTERN = re.compile(r"[a-f0-9]{12}")
_TRUSTED_IMAGERY_ID_PATTERN = re.compile(r"(?:ID|id)\s*[:=：]\s*([a-f0-9]{12})")


@dataclass(frozen=True)
class IntentDecision:
    action: IntentAction
    reason: str
    capability_name: str | None = None
    capability_kind: IntentCapabilityKind | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    tool_call: RuntimeToolCall | None = None
    agent_call: RuntimeAgentCall | None = None
    trace_stage: str | None = None
    trace_label: str | None = None


class IntentPolicy:
    def __init__(self) -> None:
        self.settings = get_settings()

    def decide(
        self,
        *,
        request: ChatRequest,
        query: str,
        user_id: str | None,
        config: ResolvedAIConfig,
        web_search_available: bool,
    ) -> IntentDecision:
        ndvi_call = detect_ndvi_intent(query, request.messages, user_id=user_id)
        if ndvi_call:
            return IntentDecision(
                action="force",
                reason="ndvi_intent",
                capability_name=ndvi_call.name,
                capability_kind="tool",
                arguments=ndvi_call.arguments,
                tool_call=ndvi_call,
            )

        rs_call = detect_rs_tools_intent(query, request.messages, user_id=user_id)
        if rs_call:
            return IntentDecision(
                action="force",
                reason="rs_tools_intent",
                capability_name=rs_call.name,
                capability_kind="tool",
                arguments=rs_call.arguments,
                tool_call=rs_call,
            )

        intent = classify_search_intent(query, request.messages)
        if intent == SearchIntent.FORCE or (
            _is_ndvi_explanation(query) and has_force_search_signal(query)
        ):
            agent_call = self._web_search_call(query, "规则预判触发")
            return IntentDecision(
                action="force",
                reason="classifier_force",
                capability_name=agent_call.name,
                capability_kind="agent",
                arguments=agent_call.arguments,
                agent_call=agent_call,
                trace_stage="classifier_force",
                trace_label="规则预判：直接执行联网搜索",
            )

        if intent == SearchIntent.SKIP:
            return IntentDecision(
                action="skip",
                reason="classifier_skip",
                trace_stage="classifier_skip",
                trace_label="规则预判：无需联网搜索",
            )

        if _is_ndvi_explanation(query):
            return IntentDecision(
                action="skip",
                reason="classifier_skip",
                trace_stage="classifier_skip",
                trace_label="规则预判：无需联网搜索",
            )

        cache_scope = decision_cache_scope(
            request=request,
            user_id=user_id,
            config=config,
            web_search_available=web_search_available,
        )
        cached = get_decision_cache().get_decision(query, scope=cache_scope)
        if cached == CachedDecision.NO_SEARCH:
            return IntentDecision(
                action="skip",
                reason="cache_hit_skip",
                trace_stage="cache_hit_skip",
                trace_label="决策缓存命中：无需联网搜索",
            )
        if cached == CachedDecision.SEARCH:
            agent_call = self._web_search_call(query, "缓存决策触发")
            return IntentDecision(
                action="force",
                reason="planner",
                capability_name=agent_call.name,
                capability_kind="agent",
                arguments=agent_call.arguments,
                agent_call=agent_call,
                trace_stage="cache_hit_search",
                trace_label="决策缓存命中：需要联网搜索",
            )

        return IntentDecision(action="ask_planner", reason="planner")

    def _web_search_call(self, query: str, reason: str) -> RuntimeAgentCall:
        return RuntimeAgentCall(
            name="web_search",
            arguments={
                "query": query[: self.settings.agent_web_search_input_max_chars],
                "reason": reason,
            },
            call_id=None,
        )


def detect_ndvi_intent(
    query: str,
    messages: list[Any] | None = None,
    *,
    user_id: str | None,
) -> RuntimeToolCall | None:
    if not wants_ndvi_calculation(query):
        return None
    context_text = _recent_context_text(query, messages)
    known_ids = known_imagery_ids_for_user(user_id)
    imagery_id = trusted_imagery_id(context_text, known_ids) or known_imagery_id_in_text(context_text, known_ids)
    if not imagery_id:
        return None
    return RuntimeToolCall(
        name="calculate_ndvi",
        arguments={
            "imagery_id": imagery_id,
            "reason": "User requested NDVI calculation",
        },
        call_id=None,
    )


def detect_rs_tools_intent(
    query: str,
    messages: list[Any] | None = None,
    *,
    user_id: str | None,
) -> RuntimeToolCall | None:
    context_text = _recent_context_text(query, messages)
    known_ids = known_imagery_ids_for_user(user_id)
    imagery_id = trusted_imagery_id(context_text, known_ids) or known_imagery_id_in_text(context_text, known_ids)
    if not imagery_id:
        return None

    lowered = query.lower()
    if _wants_raster_inspect(lowered):
        return RuntimeToolCall(
            name="raster_inspect",
            arguments={"imagery_id": imagery_id, "reason": "User requested imagery inspection"},
            call_id=None,
        )

    index_type = _requested_index_type(lowered)
    if index_type:
        return RuntimeToolCall(
            name="calculate_spectral_index",
            arguments={
                "imagery_id": imagery_id,
                "index_type": index_type,
                "reason": "User requested spectral index calculation",
            },
            call_id=None,
        )

    composite_mode = _requested_composite_mode(lowered)
    if composite_mode:
        return RuntimeToolCall(
            name="render_band_composite",
            arguments={
                "imagery_id": imagery_id,
                "mode": composite_mode,
                "reason": "User requested band composite rendering",
            },
            call_id=None,
        )
    return None


def trusted_imagery_id(text: str, known_ids: set[str]) -> str | None:
    trusted_markers = ("当前上传影像", "已上传影像", "可用影像", "上传影像")
    if not any(marker in text for marker in trusted_markers):
        return None
    match = _TRUSTED_IMAGERY_ID_PATTERN.search(text)
    if not match:
        return None
    imagery_id = match.group(1)
    return imagery_id if imagery_id in known_ids else None


def known_imagery_id_in_text(text: str, known_ids: set[str]) -> str | None:
    if not known_ids:
        return None
    for match in _IMAGERY_ID_PATTERN.finditer(text):
        if match.group() in known_ids:
            return match.group()
    return None


def decision_cache_scope(
    *,
    request: ChatRequest,
    user_id: str | None,
    config: ResolvedAIConfig,
    web_search_available: bool,
) -> str:
    return "|".join(
        [
            user_id or "anonymous",
            request.conversation_id or "no-conversation",
            config.model,
            "web:on" if web_search_available else "web:off",
            f"rag:{int(request.use_rag)}",
            f"memory:{int(request.use_memory)}",
        ]
    )


def _recent_context_text(query: str, messages: list[Any] | None) -> str:
    if not messages:
        return query
    return "\n".join(
        str(read_value(message, "content", "") or "")
        for message in messages[-6:]
    )


def _wants_raster_inspect(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "检查影像",
            "影像信息",
            "波段信息",
            "crs",
            "分辨率",
            "metadata",
            "元数据",
            "像元大小",
        )
    )


def _requested_index_type(text: str) -> str | None:
    for index_type in ("mndwi", "ndwi", "ndbi", "evi", "savi"):
        if index_type in text:
            return index_type
    if "水体指数" in text:
        return "ndwi"
    if "建筑指数" in text or "建成区指数" in text:
        return "ndbi"
    return None


def _requested_composite_mode(text: str) -> str | None:
    if "真彩色" in text or "true color" in text:
        return "true_color"
    if "假彩色" in text or "false color" in text or "432组合" in text:
        return "false_color"
    if "波段组合" in text or "rgb" in text or "composite" in text:
        return "custom" if "自定义" in text else "false_color"
    return None


def _is_ndvi_explanation(text: str) -> bool:
    lowered = text.lower()
    if "ndvi" not in lowered and "植被指数" not in text:
        return False
    return any(term in lowered for term in NDVI_EXPLANATION_TERMS)


def read_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
