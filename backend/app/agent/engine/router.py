"""AutoGen-native structured router for stable GraphFlow presets."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import StructuredMessage, TextMessage
from pydantic import BaseModel, Field

from app.agent.config import ResolvedAIConfig
from app.agent.engine.input import TurnInput
from app.agent.engine.model_client import build_model_client
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# OpenAI-compatible providers vary in response_format support.  Once an endpoint
# proves it cannot do structured output, skip the known-failing request for later
# turns and use strict JSON text parsing directly.
_PLAIN_ROUTER_KEYS: set[str] = set()
_MAX_PLAIN_ROUTER_KEYS = 64

FlowName = Literal["inspect_index_report", "mask_segment_report", "detect_report"]


class FlowDecision(BaseModel):
    strategy: Literal["selector", "graph"] = "selector"
    flow_name: FlowName | None = None
    reason: str = Field(max_length=240)


@dataclass(frozen=True)
class RouteResult:
    strategy: Literal["selector", "graph"]
    flow_name: FlowName | None
    reason: str
    usage: dict[str, int] | None = None


_ROUTER_PROMPT = """
你是 Agent-RS 的流程路由 Agent。只判断请求是否完整命中一个固定标准作业；不回答问题，
不调用工具。返回结构化 FlowDecision。

可用流程：
- inspect_index_report：同一影像上明确要求影像质检 + 一个光谱指数计算 + 生成报告。
- mask_segment_report：同一影像上明确要求云/阴影掩膜 + 地物分类 + 生成报告。
- detect_report：同一影像上明确要求目标检测 + 生成报告。

只有用户明确要求流程中的全部步骤、顺序成立且没有额外跨领域步骤时才选 graph。
缺任一步、只是概念提问、需要澄清资源、步骤更多/不同、或任何不确定情况都选 selector，
flow_name 置空。不得根据历史内容替用户补出当前没要求的步骤。
""".strip()


async def choose_route(turn: TurnInput, config: ResolvedAIConfig) -> RouteResult:
    settings = get_settings()
    if not settings.agent_auto_flow_enabled:
        return RouteResult(strategy="selector", flow_name=None, reason="auto_flow_disabled")

    client = build_model_client(
        config,
        for_routing=True,
        max_tokens=max(64, settings.agent_router_max_tokens),
    )
    try:
        router_key = _router_key(config)
        if router_key in _PLAIN_ROUTER_KEYS:
            decision = await _run_plain_router(turn, client)
        else:
            try:
                decision = await _run_structured_router(turn, client)
            except Exception as exc:
                if not _can_retry_as_plain(exc):
                    raise
                decision = await _run_plain_router(turn, client)
                _remember_plain_router(router_key)
        if decision.strategy == "graph" and decision.flow_name is None:
            raise ValueError("graph strategy requires flow_name")
        if decision.strategy == "selector" and decision.flow_name is not None:
            decision = decision.model_copy(update={"flow_name": None})
        return RouteResult(
            strategy=decision.strategy,
            flow_name=decision.flow_name,
            reason=decision.reason,
            usage=_usage(client),
        )
    except Exception as exc:
        # 第三方异常字符串可能带请求/响应正文，只记录异常类别。
        logger.warning(
            "AutoGen flow router failed; falling back to selector: %s",
            type(exc).__name__,
        )
        return RouteResult(
            strategy="selector",
            flow_name=None,
            reason=f"router_fallback:{type(exc).__name__}",
            usage=_usage(client),
        )
    finally:
        try:
            await client.close()
        except Exception:
            logger.debug("Failed to close flow router model client", exc_info=True)


async def _run_structured_router(turn: TurnInput, client) -> FlowDecision:
    agent = AssistantAgent(
        name="flow_router",
        description="选择标准 GraphFlow 或通用 SelectorGroupChat。",
        model_client=client,
        system_message=_ROUTER_PROMPT,
        model_context=turn.context(),
        output_content_type=FlowDecision,
    )
    result = await agent.run(task=turn.query, output_task_messages=False)
    decision = next(
        (
            message.content
            for message in reversed(result.messages)
            if isinstance(message, StructuredMessage)
            and isinstance(message.content, FlowDecision)
        ),
        None,
    )
    if decision is None:
        raise ValueError("flow router returned no structured decision")
    return decision


async def _run_plain_router(turn: TurnInput, client) -> FlowDecision:
    agent = AssistantAgent(
        name="flow_router",
        description="选择标准 GraphFlow 或通用 SelectorGroupChat。",
        model_client=client,
        system_message=(
            f"{_ROUTER_PROMPT}\n\n"
            '供应商不支持结构化响应。只返回一行 JSON，例如：'
            '{"strategy":"selector","flow_name":null,"reason":"请求未完整命中标准流程"}。'
            "不要使用 Markdown 代码块，不要添加其它文字。"
        ),
        model_context=turn.context(),
    )
    result = await agent.run(task=turn.query, output_task_messages=False)
    text = next(
        (
            message.to_model_text()
            for message in reversed(result.messages)
            if isinstance(message, TextMessage) and message.source != "user"
        ),
        "",
    )
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match is None:
        raise ValueError("flow router returned no JSON decision")
    return FlowDecision.model_validate_json(match.group(0))


def _can_retry_as_plain(exc: Exception) -> bool:
    # Some compatible endpoints silently ignore response_format and return text;
    # that appears here as our own ValueError.  Explicit HTTP 400 is the common
    # unsupported-response-format signal.  Network/timeout errors are not retried.
    return isinstance(exc, ValueError) or getattr(exc, "status_code", None) == 400


def _router_key(config: ResolvedAIConfig) -> str:
    return "|".join(
        (
            str(getattr(config, "provider", "")),
            str(getattr(config, "base_url", "")),
            str(getattr(config, "model", "")),
        )
    )


def _remember_plain_router(key: str) -> None:
    if len(_PLAIN_ROUTER_KEYS) >= _MAX_PLAIN_ROUTER_KEYS:
        _PLAIN_ROUTER_KEYS.pop()
    _PLAIN_ROUTER_KEYS.add(key)


def _usage(client) -> dict[str, int] | None:
    try:
        usage = client.total_usage
        if callable(usage):
            usage = usage()
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
    except Exception:
        return None
    if not (prompt or completion):
        return None
    return {
        "input_tokens": prompt,
        "output_tokens": completion,
        "total_tokens": prompt + completion,
    }
