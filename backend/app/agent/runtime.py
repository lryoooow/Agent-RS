import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from app.agent.tool_registry import get_tool, list_tool_definitions
from app.agent.tools.web_search.cache import CachedDecision, get_decision_cache
from app.agent.tools.web_search.classifier import SearchIntent, classify_search_intent
from app.agent.types import AgentEvent, AgentTrace, RuntimeToolCall, ToolRunResult
from app.agent.config import ResolvedAIConfig
from app.agent.prompting.scenarios import (
    tool_final_label,
    tool_ready_label,
    tool_request_label,
    wants_ndvi_calculation,
)
from app.agent.request_builder import (
    ProviderRequestContext,
    build_planning_context,
    build_provider_request_context,
)
from app.schemas.chat import ChatRequest, GeospatialResult
from app.core.paths import imagery_root
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]


@dataclass(frozen=True)
class AgentPlanResult:
    response: Any | None
    final_context: ProviderRequestContext
    trace: AgentTrace
    used_tool: bool = False
    geospatial_result: GeospatialResult | None = None


class AgentRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def web_search_available(self) -> bool:
        return bool(
            self.settings.tavily_api_key.strip()
            and self.settings.agent_web_search_max_calls > 0
        )

    @property
    def tools_available(self) -> bool:
        return True

    def trace(self) -> AgentTrace:
        return AgentTrace(enabled=self.tools_available)

    def tool_definitions(self) -> list[dict[str, Any]]:
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
        plan = await self.plan(
            client=client,
            config=config,
            request=request,
            initial_context=initial_context,
            user_id=user_id,
            trace=trace,
        )
        final_response = await self._create_completion(
            client=client,
            config=config,
            messages=plan.final_context.messages,
            stream=False,
        )
        return AgentPlanResult(
            response=final_response,
            final_context=plan.final_context,
            trace=plan.trace,
            used_tool=plan.used_tool,
            geospatial_result=plan.geospatial_result,
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
        return await self.plan(
            client=client,
            config=config,
            request=request,
            initial_context=initial_context,
            user_id=user_id,
            trace=trace,
            on_event=on_event,
        )

    async def plan(
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
        await self._add_event(
            trace,
            on_event,
            "context_assembled",
            "上下文已装配",
            retrieved_chunks=initial_context.retrieved_chunks,
            rag_trace=initial_context.rag_trace,
        )

        tools = self.tool_definitions()
        if not tools:
            if self.settings.tavily_api_key.strip():
                await self._add_event(trace, on_event, "tool_unavailable", "工具未配置，跳过工具调用")
            return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

        query = _latest_user_query(request)

        ndvi_call = _detect_ndvi_intent(query, request.messages)
        if ndvi_call:
            await self._add_event(
                trace,
                on_event,
                "tool_requested",
                tool_request_label("calculate_ndvi"),
                tool="calculate_ndvi",
            )
            tool_result = await self.run_tool_call(ndvi_call, trace=trace, on_event=on_event)
            final_context = await build_provider_request_context(
                request,
                user_id=user_id,
                tool_context=tool_result.tool_context,
                retrieved_context=initial_context.retrieved_context,
            )
            await self._add_event(trace, on_event, "final_answering", tool_final_label("calculate_ndvi"))
            return AgentPlanResult(
                response=None,
                final_context=final_context,
                trace=trace,
                used_tool=True,
                geospatial_result=tool_result.geospatial_result,
            )

        intent = classify_search_intent(query, request.messages)
        if intent == SearchIntent.SKIP:
            await self._add_event(trace, on_event, "classifier_skip", "规则预判：无需联网搜索")
            return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

        if intent == SearchIntent.FORCE:
            await self._add_event(trace, on_event, "classifier_force", "规则预判：直接执行联网搜索")
            tool_call = RuntimeToolCall(
                name="web_search",
                arguments={
                    "query": query[: self.settings.agent_web_search_input_max_chars],
                    "reason": "规则预判触发",
                },
                call_id=None,
            )
        else:
            tool_call = await self._plan_search_call(
                client=client,
                config=config,
                request=request,
                query=query,
                user_id=user_id,
                trace=trace,
                on_event=on_event,
            )
            if tool_call is None:
                return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

        tool_result = await self.run_tool_call(tool_call, trace=trace, on_event=on_event)
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
            tool_final_label(tool_call.name),
            tool_context_chars=len(tool_result.tool_context),
        )
        return AgentPlanResult(
            response=None,
            final_context=final_context,
            trace=trace,
            used_tool=True,
            geospatial_result=tool_result.geospatial_result,
        )

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
    ) -> RuntimeToolCall | None:
        decision_cache = get_decision_cache()
        cache_scope = _decision_cache_scope(
            request=request,
            user_id=user_id,
            config=config,
            web_search_available=self.web_search_available,
        )
        cached = decision_cache.get_decision(query, scope=cache_scope)
        if cached == CachedDecision.NO_SEARCH:
            await self._add_event(trace, on_event, "cache_hit_skip", "决策缓存命中：无需联网搜索")
            return None
        if cached == CachedDecision.SEARCH:
            await self._add_event(trace, on_event, "cache_hit_search", "决策缓存命中：需要联网搜索")
            return RuntimeToolCall(
                name="web_search",
                arguments={
                    "query": query[: self.settings.agent_web_search_input_max_chars],
                    "reason": "缓存决策触发",
                },
                call_id=None,
            )

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
                await self._add_event(trace, on_event, "tool_unavailable", "模型接口不可用，降级为普通回答")
                return None

        answer = self._extract_text(response).strip().upper()
        if answer.startswith("YES"):
            decision_cache.put_decision(query, CachedDecision.SEARCH, scope=cache_scope)
            return RuntimeToolCall(
                name="web_search",
                arguments={
                    "query": query[: self.settings.agent_web_search_input_max_chars],
                    "reason": "模型判断需要搜索",
                },
                call_id=None,
            )

        decision_cache.put_decision(query, CachedDecision.NO_SEARCH, scope=cache_scope)
        await self._add_event(trace, on_event, "direct_answer", "无需联网搜索，直接回答")
        return None

    async def run_tool_call(
        self,
        tool_call: RuntimeToolCall,
        *,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
    ) -> ToolRunResult:
        await self._add_event(
            trace,
            on_event,
            "tool_requested",
            tool_request_label(tool_call.name),
            tool_name=tool_call.name,
            query=tool_call.arguments.get("query"),
            reason=tool_call.arguments.get("reason"),
        )
        tool = get_tool(tool_call.name)
        if tool is None:
            message = f"不允许调用工具：{tool_call.name}"
            await self._add_event(trace, on_event, "tool_context_ready", message)
            return ToolRunResult(tool_context=f"工具未执行：{message}", error=message)

        try:
            args = tool.argument_model.model_validate(tool_call.arguments)
        except ValidationError as exc:
            message = "工具参数无效"
            await self._add_event(trace, on_event, "tool_context_ready", message, error=str(exc))
            return ToolRunResult(tool_context=f"{message}，已跳过执行。", error=str(exc))

        await self._add_event(trace, on_event, "child_agent_running", f"正在执行工具: {tool_call.name}", tool_name=tool_call.name)
        await self._add_event(trace, on_event, "tool_execution_started", "工具执行已开始", tool_name=tool_call.name)
        result = await tool.runner(args)

        if result.metadata.get("fallback_used"):
            await self._add_event(
                trace,
                on_event,
                "tool_fallback_used",
                "工具使用了本地回退",
                tool_name=tool_call.name,
                **result.metadata,
            )
        await self._add_event(
            trace,
            on_event,
            "tool_execution_failed" if result.error else "tool_execution_completed",
            "工具执行失败" if result.error else "工具执行完成",
            tool_name=tool_call.name,
            **result.metadata,
        )
        if result.geospatial_result:
            result_type = result.geospatial_result.get("type") if isinstance(result.geospatial_result, dict) else result.geospatial_result.type
            await self._add_event(
                trace,
                on_event,
                "geospatial_result_ready",
                "地图图层结果已生成",
                tool_name=tool_call.name,
                result_type=result_type,
            )
        await self._add_event(
            trace,
            on_event,
            "tool_context_ready",
            tool_ready_label(tool_call.name),
            query=result.query,
            result_count=result.result_count,
            error=result.error,
            tool_context_chars=len(result.tool_context),
            **result.metadata,
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


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _latest_user_query(request: ChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content.strip()
    return ""


def _decision_cache_scope(
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


_IMAGERY_ID_PATTERN = re.compile(r"[a-f0-9]{12}")
_TRUSTED_IMAGERY_ID_PATTERN = re.compile(r"(?:ID|id)\s*[:=：]\s*([a-f0-9]{12})")


def _detect_ndvi_intent(query: str, messages: list[Any] | None = None) -> RuntimeToolCall | None:
    """Return an NDVI tool call for explicit calculation requests with an imagery ID in context."""
    if not wants_ndvi_calculation(query):
        return None
    context_text = query
    if messages:
        context_text = "\n".join(
            str(_read(message, "content", "") or "")
            for message in messages[-6:]
        )
    imagery_id = _trusted_imagery_id(context_text) or _known_imagery_id_in_text(context_text)
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


def _trusted_imagery_id(text: str) -> str | None:
    trusted_markers = ("当前上传影像", "已上传影像", "可用影像", "上传影像")
    if not any(marker in text for marker in trusted_markers):
        return None
    match = _TRUSTED_IMAGERY_ID_PATTERN.search(text)
    return match.group(1) if match else None


def _known_imagery_id_in_text(text: str) -> str | None:
    known_ids = _known_imagery_ids()
    if not known_ids:
        return None
    for match in _IMAGERY_ID_PATTERN.finditer(text):
        if match.group() in known_ids:
            return match.group()
    return None


def _known_imagery_ids() -> set[str]:
    root = imagery_root()
    if not root.exists():
        return set()
    result: set[str] = set()
    for entry in root.iterdir():
        if entry.is_dir() and _IMAGERY_ID_PATTERN.fullmatch(entry.name) and (entry / "metadata.json").exists():
            result.add(entry.name)
    return result
