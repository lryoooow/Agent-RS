from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.agent.config import ResolvedAIConfig
from app.agent.imagery_access import known_imagery_ids_for_user
from app.agent.prompting.scenarios import wants_ndvi_calculation
from app.agent.request_builder import build_planning_context
from app.agent.routing import AgentRoute
from app.agent.search.cache import CachedDecision, get_decision_cache
from app.agent.search.classifier import SearchIntent, classify_search_intent
from app.agent.types import AgentEvent, AgentTrace, RuntimeAgentCall, RuntimeToolCall
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]

_IMAGERY_ID_PATTERN = re.compile(r"[a-f0-9]{12}")
_TRUSTED_IMAGERY_ID_PATTERN = re.compile(r"(?:ID|id)\s*[:=：]\s*([a-f0-9]{12})")


@dataclass(frozen=True)
class TaskSelection:
    tool_call: RuntimeToolCall | None = None
    agent_call: RuntimeAgentCall | None = None
    reason: str = "no_tool"


class TaskSelector:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def web_search_available(self) -> bool:
        return bool(
            self.settings.tavily_api_key.strip()
            and self.settings.agent_web_search_max_calls > 0
        )

    async def select(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        query: str,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        add_event: Callable[..., Awaitable[AgentEvent]],
        route: AgentRoute | None = None,
    ) -> TaskSelection:
        allowed_tools = set(route.candidate_tools) if route else {"calculate_ndvi"}
        allowed_agents = set(route.candidate_agents) if route else {"web_search"}

        ndvi_call = detect_ndvi_intent(query, request.messages, user_id=user_id)
        if ndvi_call:
            if ndvi_call.name not in allowed_tools:
                return TaskSelection(reason="ndvi_not_allowed_by_route")
            return TaskSelection(tool_call=ndvi_call, reason="ndvi_intent")

        intent = classify_search_intent(query, request.messages)
        if intent == SearchIntent.SKIP:
            await add_event(trace, on_event, "classifier_skip", "规则预判：无需联网搜索")
            return TaskSelection(reason="classifier_skip")

        if "web_search" not in allowed_agents:
            await add_event(trace, on_event, "tool_unavailable", "当前路由不允许联网搜索")
            return TaskSelection(reason="search_not_allowed_by_route")

        if intent == SearchIntent.FORCE:
            if not self.web_search_available:
                await add_event(trace, on_event, "tool_unavailable", "联网搜索不可用，跳过")
                return TaskSelection(reason="force_but_unavailable")
            await add_event(trace, on_event, "classifier_force", "规则预判：直接执行联网搜索")
            return TaskSelection(
                agent_call=self._web_search_call(query, "规则预判触发"),
                reason="classifier_force",
            )

        agent_call = await self._plan_search_call(
            client=client,
            config=config,
            request=request,
            query=query,
            user_id=user_id,
            trace=trace,
            on_event=on_event,
            add_event=add_event,
        )
        return TaskSelection(agent_call=agent_call, reason="planner" if agent_call else "planner_no_tool")

    async def _plan_search_call(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        query: str,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        add_event: Callable[..., Awaitable[AgentEvent]],
    ) -> RuntimeAgentCall | None:
        if not self.web_search_available:
            await add_event(trace, on_event, "tool_unavailable", "联网搜索不可用，跳过")
            return None

        decision_cache = get_decision_cache()
        cache_scope = decision_cache_scope(
            request=request,
            user_id=user_id,
            config=config,
            web_search_available=self.web_search_available,
        )
        cached = decision_cache.get_decision(query, scope=cache_scope)
        if cached == CachedDecision.NO_SEARCH:
            await add_event(trace, on_event, "cache_hit_skip", "决策缓存命中：无需联网搜索")
            return None
        if cached == CachedDecision.SEARCH:
            await add_event(trace, on_event, "cache_hit_search", "决策缓存命中：需要联网搜索")
            return self._web_search_call(query, "缓存决策触发")

        await add_event(trace, on_event, "planning", "正在判断是否需要联网搜索")
        planning_messages = await build_planning_context(request)
        planning_model = self.settings.agent_planning_model.strip() or config.model
        try:
            response = await client.chat.completions.create(
                model=planning_model,
                messages=planning_messages,
                stream=False,
                max_tokens=3,
                extra_body={"enable_thinking": False},
            )
        except Exception:
            logger.warning("Planning model failed; trying main model as fallback.")
            await add_event(trace, on_event, "planning_fallback", "规划模型失败，尝试主模型兜底")
            try:
                response = await client.chat.completions.create(
                    model=config.model,
                    messages=planning_messages,
                    stream=False,
                    max_tokens=3,
                    extra_body={"enable_thinking": False},
                )
            except Exception:
                logger.exception("Fallback model also failed.")
                await add_event(trace, on_event, "tool_unavailable", "模型接口不可用，降级为普通回答")
                return None

        answer = extract_text(response).strip().upper()
        if answer.startswith("YES"):
            decision_cache.put_decision(query, CachedDecision.SEARCH, scope=cache_scope)
            return self._web_search_call(query, "模型判断需要搜索")

        decision_cache.put_decision(query, CachedDecision.NO_SEARCH, scope=cache_scope)
        await add_event(trace, on_event, "direct_answer", "无需联网搜索，直接回答")
        return None

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
    context_text = query
    if messages:
        context_text = "\n".join(
            str(read_value(message, "content", "") or "")
            for message in messages[-6:]
        )
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


def read_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def extract_text(response: Any) -> str:
    choices = read_value(response, "choices", []) or []
    if not choices:
        return ""
    message = read_value(choices[0], "message", {})
    return read_value(message, "content", "") or ""
