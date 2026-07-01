from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.agent.config import ResolvedAIConfig
from app.agent.imagery_access import iter_user_imagery_metadata
from app.agent.llm_planner import LLMCapabilityPlanner, PlannerDecision, capability_snapshot
from app.agent.plan_validator import PlanValidator
from app.agent.routing import AgentRoute
from app.agent.search.cache import get_planner_decision_cache
from app.agent.types import AgentEvent, AgentTrace, RuntimeAgentCall, RuntimeToolCall
from app.db.errors import is_missing_schema_error
from app.db.pool import fetch_optional_pool
from app.db.repositories.document import list_documents
from app.db.repositories.message import list_recent_analysis_results
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


logger = logging.getLogger(__name__)

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]

_GUARD_ERROR_CODES = {
    "imagery_not_found_or_forbidden",
    "document_not_found_or_forbidden",
    "owner_required",
}


@dataclass(frozen=True)
class TaskSelection:
    tool_call: RuntimeToolCall | None = None
    agent_call: RuntimeAgentCall | None = None
    reason: str = "no_tool"
    planner_error_context: str | None = None


class TaskSelector:
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
        capabilities = capability_snapshot()
        scope = await _planner_cache_scope(
            config=config,
            route=route,
            capabilities=capabilities,
            user_id=user_id,
            request=request,
        )
        cache = get_planner_decision_cache()
        cached = cache.get_plan(query, scope=scope)
        if cached:
            decision = PlannerDecision(
                action=str(cached.get("action") or "none"),
                capability=cached.get("capability") if isinstance(cached.get("capability"), str) else None,
                arguments=cached.get("arguments") if isinstance(cached.get("arguments"), dict) else {},
                reason=str(cached.get("reason") or "cached_planner_decision"),
                raw=cached,
            )
        else:
            decision = await LLMCapabilityPlanner().plan(
                client=client,
                config=config,
                request=request,
                query=query,
                user_id=user_id,
                capabilities=capabilities,
                trace=trace,
                on_event=on_event,
                add_event=add_event,
            )

        validated = await PlanValidator().validate(decision, route=route, user_id=user_id)
        if validated.validation_error:
            stage = (
                "capability_guard_rejected"
                if validated.validation_error in _GUARD_ERROR_CODES
                else "plan_validation_failed"
            )
            label = (
                "能力调用被拒绝，降级为直接回答"
                if stage == "capability_guard_rejected"
                else "能力规划校验失败，降级为直接回答"
            )
            await add_event(
                trace,
                on_event,
                stage,
                label,
                capability=validated.capability_name,
                error=validated.validation_error,
            )
            context = None
            if decision.action == "call":
                context = (
                    "能力规划已请求调用工具或子 Agent，但校验未通过，系统已禁止执行。\n"
                    f"- capability: {decision.capability}\n"
                    f"- error: {validated.validation_error}\n"
                    "- 回答时请说明本次没有执行外部能力，不要编造工具结果。"
                )
            return TaskSelection(reason=validated.validation_error, planner_error_context=context)

        if validated.action == "none":
            await add_event(
                trace,
                on_event,
                "planner_no_call",
                "规划结果无需调用能力",
                reason=validated.reason,
            )
            return TaskSelection(reason=validated.reason or "planner_no_call")

        if not cached:
            cache.put_plan(
                query,
                {
                    "action": "call",
                    "capability": validated.capability_name,
                    "arguments": validated.arguments,
                    "reason": validated.reason,
                },
                scope=scope,
            )

        await add_event(
            trace,
            on_event,
            "planner_selected",
            "规划选择能力调用",
            capability=validated.capability_name,
            dispatch_kind=validated.capability_kind,
            reason=validated.reason,
            cached=bool(cached),
        )
        return TaskSelection(
            tool_call=validated.tool_call,
            agent_call=validated.agent_call,
            reason=validated.reason or "llm_planner",
        )


async def _planner_cache_scope(
    *,
    config: ResolvedAIConfig,
    route: AgentRoute | None,
    capabilities,
    user_id: str | None,
    request: ChatRequest,
) -> str:
    """构造规划决策缓存 key 的 scope。

    必须覆盖规划器实际依赖的全部上下文，否则「同 query 不同上下文」会错误命中同一决策。
    除原有维度外，追加规划器真实读取的动态上下文（见 llm_planner._build_messages）：
    - 影像清单指纹：换了影像/影像集变化 → 决策应重算（根治跨影像误判）。
    - 文档清单指纹：上传/删除文档 → parse_document 决策应重算。
    - 分析状态标记：本对话有无分析史 → generate_report 等决策应重算（根治报告状态钉死）。
    """
    capability_key = ",".join(sorted(capability.name for capability in capabilities))
    imagery_fp = await _imagery_fingerprint(user_id)
    document_fp = await _document_fingerprint(user_id)
    analysis_fp = await _analysis_state_fingerprint(request, user_id)
    return "|".join(
        [
            user_id or "anonymous",
            request.conversation_id or "no-conversation",
            config.model,
            "mode:llm",
            route.mode if route else "no-route",
            capability_key,
            f"rag:{int(request.use_rag)}",
            f"memory:{int(request.use_memory)}",
            f"img:{imagery_fp}",
            f"doc:{document_fp}",
            f"ana:{analysis_fp}",
        ]
    )


async def _imagery_fingerprint(user_id: str | None) -> str:
    """当前用户可用影像清单的稳定指纹（仅取有序 imagery_id 集合，不掺易变 meta）。

    规划器 prompt 注入了影像清单并据其选 imagery_id；清单变化必须使决策缓存失效。
    无影像 / 无 user_id → 固定串 "none"。best-effort：任何异常退回 "none"（等价于不靠此维区分，
    不会比修复前更差，且绝不抛进规划主路径）。
    """
    if not user_id:
        return "none"
    try:
        items = await iter_user_imagery_metadata(user_id)
    except Exception:
        logger.debug("Imagery fingerprint lookup failed; falling back to 'none'.", exc_info=True)
        return "none"
    imagery_ids = [imagery_id for imagery_id, _meta in items]
    if not imagery_ids:
        return "none"
    joined = ",".join(imagery_ids)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


async def _document_fingerprint(user_id: str | None) -> str:
    """当前用户文档 ID 集合的稳定指纹，使文档上传/删除立即失效 planner 缓存。"""
    if not user_id or not get_settings().storage_active:
        return "none"
    pool = await fetch_optional_pool()
    if pool is None:
        return "none"
    try:
        async with pool.acquire() as conn:
            documents = await list_documents(
                conn,
                user_id=user_id,
                limit=get_settings().agent_document_inventory_limit,
            )
    except Exception:
        logger.debug("Document fingerprint lookup failed; falling back to 'none'.", exc_info=True)
        return "none"
    document_ids = sorted(str(document["id"]) for document in documents)
    if not document_ids:
        return "none"
    return hashlib.sha256(",".join(document_ids).encode("utf-8")).hexdigest()[:12]


async def _analysis_state_fingerprint(request: ChatRequest, user_id: str | None) -> str:
    """本对话是否已有持久化分析结果的布尔指纹（"1"=有，"0"=无）。

    generate_report 等决策依赖「本对话有无分析史」；该状态变化必须使决策缓存失效。
    无 conversation_id / 无 user_id / 存储未启用 / DB 不可用 / 缺表 / 查询异常 → "0"
    （best-effort，对齐 request_builder._resolve_prior_analysis_results 的容错风格）。
    limit=1 足够：只需区分有/无，不需分析明细。
    """
    if not request.conversation_id or not user_id or not get_settings().storage_active:
        return "0"
    pool = await fetch_optional_pool()
    if pool is None:
        return "0"
    try:
        async with pool.acquire() as conn:
            results = await list_recent_analysis_results(
                conn,
                conversation_id=request.conversation_id,
                user_id=user_id,
                limit=1,
            )
        return "1" if results else "0"
    except Exception as exc:
        if not is_missing_schema_error(exc):
            logger.debug("Analysis-state fingerprint lookup failed; falling back to '0'.", exc_info=True)
        return "0"
