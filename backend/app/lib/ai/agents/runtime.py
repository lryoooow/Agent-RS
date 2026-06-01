import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from app.lib.ai.agents.tool_registry import get_tool, list_tool_definitions
from app.lib.ai.agents.tools.web_search.cache import CachedDecision, get_decision_cache
from app.lib.ai.agents.tools.web_search.classifier import SearchIntent, classify_search_intent
from app.lib.ai.agents.types import AgentEvent, AgentTrace, RuntimeToolCall, ToolRunResult
from app.lib.ai.config import ResolvedAIConfig
from app.lib.ai.request_builder import (
    ProviderRequestContext,
    build_planning_context,
    build_provider_request_context,
)
from app.schemas.chat import ChatRequest
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]


@dataclass(frozen=True)
class AgentPlanResult:
    response: Any | None
    final_context: ProviderRequestContext
    trace: AgentTrace
    used_tool: bool = False


class AgentRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def web_search_available(self) -> bool:
        return bool(
            self.settings.tavily_api_key.strip()
            and self.settings.agent_web_search_max_calls > 0
        )

    def trace(self) -> AgentTrace:
        return AgentTrace(enabled=self.web_search_available)

    def tool_definitions(self) -> list[dict[str, Any]]:
        if not self.web_search_available:
            return []
        return list_tool_definitions()

    async def complete(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        initial_context: ProviderRequestContext,
        user_id: str | None,
    ) -> AgentPlanResult:
        trace = self.trace()
        tools = self.tool_definitions()
        if not tools:
            if self.settings.tavily_api_key.strip():
                trace.add("tool_unavailable", "联网搜索未配置，跳过工具调用")
            response = await self._create_completion(
                client=client,
                config=config,
                messages=initial_context.messages,
                stream=False,
            )
            return AgentPlanResult(response=response, final_context=initial_context, trace=trace)

        query = _latest_user_query(request)
        intent = classify_search_intent(query, request.messages)

        if intent == SearchIntent.SKIP:
            trace.add("classifier_skip", "规则预判：无需联网搜索")
            response = await self._create_completion(
                client=client,
                config=config,
                messages=initial_context.messages,
                stream=False,
            )
            return AgentPlanResult(response=response, final_context=initial_context, trace=trace)

        if intent == SearchIntent.FORCE:
            trace.add("classifier_force", "规则预判：直接执行联网搜索")
            tool_call = RuntimeToolCall(
                name="web_search",
                arguments={"query": query[:self.settings.agent_web_search_input_max_chars], "reason": "规则预判触发"},
                call_id=None,
            )
        else:
            decision_cache = get_decision_cache()
            cached = decision_cache.get_decision(query)
            if cached == CachedDecision.NO_SEARCH:
                trace.add("cache_hit_skip", "决策缓存命中：无需联网搜索")
                response = await self._create_completion(
                    client=client,
                    config=config,
                    messages=initial_context.messages,
                    stream=False,
                )
                return AgentPlanResult(response=response, final_context=initial_context, trace=trace)

            if cached == CachedDecision.SEARCH:
                trace.add("cache_hit_search", "决策缓存命中：需要联网搜索")
                tool_call = RuntimeToolCall(
                    name="web_search",
                    arguments={"query": query[:self.settings.agent_web_search_input_max_chars], "reason": "缓存决策触发"},
                    call_id=None,
                )
            else:
                trace.add("planning", "正在判断是否需要联网搜索")
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
                    trace.add("planning_fallback", "规划模型失败，尝试主模型兜底")
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
                        trace.add("tool_unavailable", "模型接口不支持工具调用，已降级为普通回答")
                        response = await self._create_completion(
                            client=client,
                            config=config,
                            messages=initial_context.messages,
                            stream=False,
                        )
                        return AgentPlanResult(response=response, final_context=initial_context, trace=trace)

                answer = self._extract_text(response).strip().upper()
                if answer.startswith("YES"):
                    decision_cache.put_decision(query, CachedDecision.SEARCH)
                    tool_call = RuntimeToolCall(
                        name="web_search",
                        arguments={"query": query[:self.settings.agent_web_search_input_max_chars], "reason": "模型判断需要搜索"},
                        call_id=None,
                    )
                else:
                    decision_cache.put_decision(query, CachedDecision.NO_SEARCH)
                    trace.add("direct_answer", "无需联网搜索，直接回答")
                    response = await self._create_completion(
                        client=client,
                        config=config,
                        messages=initial_context.messages,
                        stream=False,
                    )
                    return AgentPlanResult(response=response, final_context=initial_context, trace=trace)

        tool_result = await self.run_tool_call(tool_call, request=request, trace=trace)
        final_context = await build_provider_request_context(
            request,
            user_id=user_id,
            tool_context=tool_result.tool_context,
            retrieved_context=initial_context.retrieved_context,
        )
        trace.add(
            "final_answering",
            "正在基于联网搜索结果生成最终回答",
            tool_context_chars=len(tool_result.tool_context),
        )
        final_response = await self._create_completion(
            client=client,
            config=config,
            messages=final_context.messages,
            stream=False,
        )
        return AgentPlanResult(
            response=final_response,
            final_context=final_context,
            trace=trace,
            used_tool=True,
        )

    async def plan_stream(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        initial_context: ProviderRequestContext,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
    ) -> AgentPlanResult:
        tools = self.tool_definitions()
        if not tools:
            if self.settings.tavily_api_key.strip():
                await self._add_event(trace, on_event, "tool_unavailable", "联网搜索未配置，跳过工具调用")
            return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

        query = _latest_user_query(request)
        intent = classify_search_intent(query, request.messages)

        if intent == SearchIntent.SKIP:
            await self._add_event(trace, on_event, "classifier_skip", "规则预判：无需联网搜索")
            return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

        if intent == SearchIntent.FORCE:
            await self._add_event(trace, on_event, "classifier_force", "规则预判：直接执行联网搜索")
            tool_call = RuntimeToolCall(
                name="web_search",
                arguments={"query": query[:self.settings.agent_web_search_input_max_chars], "reason": "规则预判触发"},
                call_id=None,
            )
        else:
            decision_cache = get_decision_cache()
            cached = decision_cache.get_decision(query)
            if cached == CachedDecision.NO_SEARCH:
                await self._add_event(trace, on_event, "cache_hit_skip", "决策缓存命中：无需联网搜索")
                return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

            if cached == CachedDecision.SEARCH:
                await self._add_event(trace, on_event, "cache_hit_search", "决策缓存命中：需要联网搜索")
                tool_call = RuntimeToolCall(
                    name="web_search",
                    arguments={"query": query[:self.settings.agent_web_search_input_max_chars], "reason": "缓存决策触发"},
                    call_id=None,
                )
            else:
                await self._add_event(trace, on_event, "planning", "正在判断是否需要联网搜索")
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
                    await self._add_event(trace, on_event, "planning_fallback", "规划模型失败，尝试主模型兜底")
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
                        await self._add_event(trace, on_event, "tool_unavailable", "模型接口不支持工具调用，已降级为普通回答")
                        return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

                answer = self._extract_text(response).strip().upper()
                if answer.startswith("YES"):
                    decision_cache.put_decision(query, CachedDecision.SEARCH)
                    tool_call = RuntimeToolCall(
                        name="web_search",
                        arguments={"query": query[:self.settings.agent_web_search_input_max_chars], "reason": "模型判断需要搜索"},
                        call_id=None,
                    )
                else:
                    decision_cache.put_decision(query, CachedDecision.NO_SEARCH)
                    await self._add_event(trace, on_event, "direct_answer", "无需联网搜索，直接回答")
                    return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

        tool_result = await self.run_tool_call(
            tool_call,
            request=request,
            trace=trace,
            on_event=on_event,
        )
        final_context = await build_provider_request_context(
            request,
            user_id=user_id,
            tool_context=tool_result.tool_context,
            retrieved_context=initial_context.retrieved_context,
        )
        await self._add_event(
            trace,
            on_event,
            "final_answering",
            "正在基于联网搜索结果生成最终回答",
            tool_context_chars=len(tool_result.tool_context),
        )
        return AgentPlanResult(
            response=None,
            final_context=final_context,
            trace=trace,
            used_tool=True,
        )

    async def run_tool_call(
        self,
        tool_call: RuntimeToolCall,
        *,
        request: ChatRequest,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
    ) -> ToolRunResult:
        await self._add_event(
            trace,
            on_event,
            "tool_requested",
            "模型请求调用联网搜索",
            tool_name=tool_call.name,
            query=tool_call.arguments.get("query"),
            reason=tool_call.arguments.get("reason"),
        )
        tool = get_tool(tool_call.name)
        if tool is None:
            message = f"不允许调用工具：{tool_call.name}"
            await self._add_event(trace, on_event, "tool_context_ready", message)
            return ToolRunResult(tool_context=f"联网搜索未执行：{message}", error=message)

        try:
            args = tool.argument_model.model_validate(tool_call.arguments)
            args = args.clamped(self.settings.agent_web_search_max_results)
        except ValidationError as exc:
            message = "联网搜索参数无效"
            await self._add_event(trace, on_event, "tool_context_ready", message, error=str(exc))
            return ToolRunResult(tool_context=f"{message}，已跳过搜索。", error=str(exc))
        if len(args.query) > self.settings.agent_web_search_input_max_chars:
            message = "联网搜索 query 超过长度限制"
            await self._add_event(trace, on_event, "tool_context_ready", message, query_chars=len(args.query))
            return ToolRunResult(tool_context=f"{message}，已跳过搜索。", error=message)

        await self._add_event(trace, on_event, "child_agent_running", "正在调用联网搜索子 Agent", query=args.query)
        result = await tool.runner(args, request)
        await self._add_event(
            trace,
            on_event,
            "tool_context_ready",
            "联网搜索结果已整理",
            query=result.query,
            result_count=result.result_count,
            error=result.error,
            tool_context_chars=len(result.tool_context),
        )
        return result

    async def _add_event(
        self,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        stage: str,
        label: str,
        **metadata: Any,
    ) -> AgentEvent:
        event = trace.add(stage, label, **metadata)
        if on_event:
            await on_event(event)
        return event

    async def _create_completion(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        messages: list[dict[str, str]],
        stream: bool,
        **kwargs: Any,
    ) -> Any:
        return await client.chat.completions.create(
            model=config.model,
            messages=messages,
            stream=stream,
            extra_body={"enable_thinking": True, "thinking_budget": self.settings.ai_thinking_budget},
            **kwargs,
        )

    def _extract_text(self, response: Any) -> str:
        choices = _read(response, "choices", []) or []
        if not choices:
            return ""
        message = _read(choices[0], "message", {})
        return _read(message, "content", "") or ""

    def _first_tool_call(self, response: Any) -> RuntimeToolCall | None:
        choices = _read(response, "choices", []) or []
        first_choice = choices[0] if choices else None
        message = _read(first_choice, "message", {}) if first_choice else {}
        tool_calls = _read(message, "tool_calls", None) or []
        if not tool_calls:
            return None

        raw = tool_calls[0]
        function = _read(raw, "function", {}) or {}
        name = _read(function, "name", "")
        raw_arguments = _read(function, "arguments", {}) or {}
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            arguments = {}
        return RuntimeToolCall(name=name, arguments=arguments, call_id=_read(raw, "id", None))


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _latest_user_query(request: ChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content.strip()
    return ""
