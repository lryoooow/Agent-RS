"""AutoGen 模型客户端适配。

把项目已有的 `ResolvedAIConfig`（env + 前端配置页的降级链，见 `app/agent/config.py`）
转成 AutoGen 的 `ChatCompletionClient`。业务代码不直接构造 AutoGen 客户端，一律走这里。

## 为什么需要显式 model_info

AutoGen 只认识 OpenAI 官方模型名，其它一律要求调用方显式声明能力：

    >>> _model_info.get_info("deepseek-v4-pro")
    ValueError: model_info is required when model name is not a valid OpenAI model

而本项目是「OpenAI 兼容端点」架构（`AI_BASE_URL` 可以指向 DeepSeek、阿里云百炼等），
模型名基本都不是 OpenAI 官方名。所以这里做三段式：

1. 能被 AutoGen 识别的（gpt-*）→ 用它推断出来的；
2. `AGENT_MODEL_INFO` 显式配置了 → 用配置的（换供应商时的逃生舱）；
3. 都没有 → 用 `_COMPATIBLE_DEFAULT`，并在日志里说明依据。

## 关于 extra_body

项目原有代码给两类调用传了不同的 thinking 参数（阿里云百炼特有）：

- 规划：`{"enable_thinking": False}`
- 主回答：`{"enable_thinking": True, "thinking_budget": N}`

AutoGen 的 `create_kwargs` 允许 `extra_body`，所以这里原样保留。对不认识这些字段的
供应商（如 DeepSeek）是无害的——已实测。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from autogen_core.models import ChatCompletionClient, ModelFamily, ModelInfo
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.openai import _model_info as autogen_model_info

from app.agent.config import ResolvedAIConfig, resolve_ai_config
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# OpenAI 兼容端点的保守默认能力集。
#
# function_calling=True 是整个 AutoGen 迁移的前提——没有它就退回不了 AutoGen 的工具循环。
# 2026-08-07 已对 deepseek-v4-pro 实测四项：单工具调用、并行多工具、概念题不硬凑工具、
# 流式 tool_call，全部通过。换供应商时若该供应商不支持，用 AGENT_MODEL_INFO 覆盖。
#
# vision=False 是刻意保守：本项目的影像走 MCP 容器算，不喂给模型看，多模态能力用不上；
# 声明 False 可以避免 AutoGen 往请求里塞图片内容块。
_COMPATIBLE_DEFAULT: ModelInfo = {
    "vision": False,
    "function_calling": True,
    "json_output": True,
    "structured_output": True,
    "family": ModelFamily.UNKNOWN,
    "multiple_system_messages": True,
}


def resolve_model_info(model: str) -> ModelInfo:
    """决定给 AutoGen 的 model_info。优先级：显式配置 > AutoGen 推断 > 兼容默认。"""
    override = get_settings().agent_model_info.strip()
    if override:
        try:
            parsed = json.loads(override)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"AGENT_MODEL_INFO 不是合法 JSON：{exc}。"
                '示例：{"vision":false,"function_calling":true,"json_output":true,'
                '"structured_output":true,"family":"unknown"}'
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError("AGENT_MODEL_INFO 必须是 JSON 对象")
        merged: ModelInfo = {**_COMPATIBLE_DEFAULT, **parsed}  # type: ignore[typeddict-item]
        return merged

    try:
        return autogen_model_info.get_info(model)
    except ValueError:
        logger.info(
            "模型 %s 不是 AutoGen 已知的 OpenAI 模型，使用兼容端点默认能力集"
            "（function_calling=True）。如与实际供应商能力不符，请设置 AGENT_MODEL_INFO。",
            model,
        )
        return dict(_COMPATIBLE_DEFAULT)  # type: ignore[return-value]


def thinking_extra_body(*, enable: bool) -> dict[str, Any]:
    """项目原有的 thinking 透传参数。

    与 legacy 链路保持一字不差，避免迁移后模型行为悄悄变化：
    - 规划走 `enable_thinking: False`（llm_planner._create_completion）
    - 主回答走 `enable_thinking: True` + budget（ai_service / runtime）
    """
    if not enable:
        return {"enable_thinking": False}
    return {
        "enable_thinking": True,
        "thinking_budget": get_settings().ai_thinking_budget,
    }


def build_model_client(
    config: ResolvedAIConfig | None = None,
    *,
    for_planning: bool = False,
    **create_args: Any,
) -> ChatCompletionClient:
    """构造 AutoGen 模型客户端。

    Args:
        config: 不传则用 `resolve_ai_config()`（env + 前端配置页降级链）。
        for_planning: True 时使用 `AGENT_PLANNING_MODEL`（留空则复用主模型）并关闭 thinking，
            与 legacy 的 `llm_planner` 行为一致。
        **create_args: 追加的 create 参数（如 max_tokens、temperature）。
    """
    settings = get_settings()
    config = config or resolve_ai_config()

    model = config.model
    if for_planning:
        model = settings.agent_planning_model.strip() or config.model

    extra_body = thinking_extra_body(enable=not for_planning)

    return OpenAIChatCompletionClient(
        model=model,
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
        model_info=resolve_model_info(model),
        extra_body=extra_body,
        **create_args,
    )
