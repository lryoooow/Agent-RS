from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.agent.capability_registry import RegisteredCapability, list_capabilities
from app.agent.config import ResolvedAIConfig
from app.agent.request_builder import (
    build_imagery_inventory,
    build_planning_context,
    should_include_imagery_inventory,
)
from app.agent.types import AgentEvent, AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannerDecision:
    action: str
    capability: str | None = None
    arguments: dict[str, Any] | None = None
    reason: str = ""
    raw: dict[str, Any] | None = None


def capability_snapshot() -> list[RegisteredCapability]:
    return list_capabilities(available_only=True)


class LLMCapabilityPlanner:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def plan(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        query: str,
        user_id: str | None = None,
        capabilities: list[RegisteredCapability],
        trace: AgentTrace,
        on_event,
        add_event,
    ) -> PlannerDecision:
        await add_event(
            trace,
            on_event,
            "planner_started",
            "正在规划是否需要调用能力",
            capability_count=len(capabilities),
        )
        messages = await self._build_messages(
            request,
            query=query,
            user_id=user_id,
            capabilities=capabilities,
        )
        model = self.settings.agent_planning_model.strip() or config.model
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                max_tokens=self.settings.agent_planner_max_tokens,
                extra_body={"enable_thinking": False},
            )
        except Exception as exc:
            logger.warning("Capability planner failed: %s", exc)
            await add_event(trace, on_event, "planner_invalid", "能力规划失败，降级为直接回答", error=str(exc))
            return PlannerDecision(action="none", reason="planner_error")

        text = _extract_text(response).strip()
        try:
            payload = _parse_json_object(text)
        except ValueError as exc:
            await add_event(trace, on_event, "planner_invalid", "能力规划输出无效，降级为直接回答", error=str(exc))
            return PlannerDecision(action="none", reason="invalid_json")

        decision = PlannerDecision(
            action=str(payload.get("action") or "none"),
            capability=payload.get("capability") if isinstance(payload.get("capability"), str) else None,
            arguments=payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {},
            reason=str(payload.get("reason") or ""),
            raw=payload,
        )
        await add_event(
            trace,
            on_event,
            "planner_completed",
            "能力规划已完成",
            action=decision.action,
            capability=decision.capability,
            reason=decision.reason,
        )
        return decision

    async def _build_messages(
        self,
        request: ChatRequest,
        *,
        query: str,
        user_id: str | None,
        capabilities: list[RegisteredCapability],
    ) -> list[dict[str, str]]:
        recent = await build_planning_context(request)
        messages = [
            {"role": "system", "content": _planner_prompt(capabilities)},
        ]
        inventory = (
            build_imagery_inventory(user_id) if should_include_imagery_inventory(query) else None
        )
        if inventory:
            messages.append(
                {
                    "role": "system",
                    "content": "Current user imagery inventory. Use only these imagery_id values:\n" + inventory,
                }
            )
        messages.extend(recent[1:])
        messages.append({"role": "user", "content": query[:800]})
        return messages


def _planner_prompt(capabilities: list[RegisteredCapability]) -> str:
    capability_lines = []
    for capability in capabilities:
        schema = capability.argument_model.model_json_schema()
        capability_lines.append(
            json.dumps(
                {
                    "name": capability.name,
                    "kind": capability.kind,
                    "description": capability.description,
                    "tags": capability.tags,
                    "schema": schema,
                },
                ensure_ascii=False,
            )
        )
    return (
        "你是 Agent-RS 的能力规划器，只决定是否调用一个能力，不回答用户问题。\n"
        "只输出 JSON 对象，不输出 Markdown，不输出解释。\n"
        "可选 action: none 或 call。action=call 时 capability 必须来自可用能力列表，arguments 必须符合 schema。\n"
        "不要猜测 imagery_id；只有上下文中明确出现可用影像 ID 时才能用于遥感工具。\n"
        "需要实时、最新、外部验证、天气、价格、官网、来源时，选择 web_search。\n"
        "普通解释、代码、翻译、数学、写作任务选择 none。\n"
        "示例：\n"
        '用户：明天杭州有中雨吗？ -> {"action":"call","capability":"web_search","arguments":{"query":"明天杭州有中雨吗？","reason":"需要实时天气预报"},"reason":"needs_current_weather"}\n'
        '用户：什么是 NDVI？ -> {"action":"none","capability":null,"arguments":{},"reason":"concept_question"}\n'
        '用户：计算影像 94e758f38ede 的 NDVI -> {"action":"call","capability":"calculate_ndvi","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求计算 NDVI"},"reason":"ndvi_calculation"}\n'
        "可用能力:\n"
        + "\n".join(capability_lines)
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("missing json object")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("planner output is not an object")
    return payload


def _extract_text(response: Any) -> str:
    choices = _read(response, "choices", []) or []
    if not choices:
        return ""
    message = _read(choices[0], "message", {})
    return _read(message, "content", "") or ""


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
