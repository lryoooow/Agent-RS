from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.agent.config import ResolvedAIConfig
from app.agent.intent_policy import decision_cache_scope, read_value
from app.agent.request_builder import build_planning_context
from app.agent.search.cache import CachedDecision, get_decision_cache
from app.agent.types import AgentEvent, AgentTrace, RuntimeAgentCall
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


logger = logging.getLogger(__name__)
AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]


class SearchPlanner:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def plan(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        query: str,
        user_id: str | None,
        web_search_available: bool,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        add_event: Callable[..., Awaitable[AgentEvent]],
    ) -> RuntimeAgentCall | None:
        if not web_search_available:
            await add_event(trace, on_event, "tool_unavailable", "联网搜索不可用，跳过")
            return None

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

        cache_scope = decision_cache_scope(
            request=request,
            user_id=user_id,
            config=config,
            web_search_available=web_search_available,
        )
        answer = extract_text(response).strip().upper()
        if answer.startswith("YES"):
            get_decision_cache().put_decision(query, CachedDecision.SEARCH, scope=cache_scope)
            return self._web_search_call(query, "模型判断需要搜索")

        get_decision_cache().put_decision(query, CachedDecision.NO_SEARCH, scope=cache_scope)
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


def extract_text(response: Any) -> str:
    choices = read_value(response, "choices", []) or []
    if not choices:
        return ""
    message = read_value(choices[0], "message", {})
    return read_value(message, "content", "") or ""
