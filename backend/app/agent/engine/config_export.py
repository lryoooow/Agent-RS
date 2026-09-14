"""把编排配置导出成声明式描述。

AutoGen 的 `Component` 体系支持 `dump_component()` / `load_component()`——
Agent、团队、模型客户端都能序列化成 `ComponentModel`（一段 JSON），再从 JSON 还原。

## 用途

1. **运维可见**："当前编排长什么样"——有哪些专家、各自拿了哪些工具、多步上限是多少。
   以前这些散在代码里，出问题只能读源码。
   注意：`describe_orchestration()` 目前**还没有接进任何 HTTP 路由**
   （`/api/config` 不返回它），只在测试与本地排查里直接调用。要对外暴露时，
   记得走这个脱敏视图而不是 `dump_team_component()`。
2. **变更审计**：工具归属或 system message 变化后，可以对比声明式导出来定位漂移。
3. **可复现**：把一次线上编排的配置 dump 下来，用于本地复现问题。

## 为什么不直接暴露完整 dump

`dump_component()` 会把模型客户端的配置一起序列化，**里面有 api_key**。
所以对外暴露必须走 `describe_orchestration()` 这个脱敏视图，
完整 dump 只留给本地调试（`dump_team_component()`），且在文档里标注不要外传。
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.engine.agents import domain_specs
from app.agent.engine.flows import PRESET_FLOWS
from app.agent.engine.tools import shared_tool_names
from app.agent.tool_registry import TOOLS
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_REDACTED = "***"
_SECRET_KEYS = frozenset({"api_key", "apikey", "token", "secret", "password"})


def describe_orchestration() -> dict[str, Any]:
    """脱敏的编排描述，可安全经 API 暴露。"""
    settings = get_settings()
    shared = list(shared_tool_names())
    all_tools = sorted(TOOLS)
    return {
        "engine": "autogen",
        "auto_flow_enabled": settings.agent_auto_flow_enabled,
        "max_tool_iterations": settings.agent_max_tool_iterations,
        "max_gpu_tool_calls": settings.agent_max_gpu_tool_calls,
        "shared_tools": shared,
        "agents": [
            {
                "name": "main_agent",
                "label": "主智能体",
                "tools": all_tools,
                "description": "自由请求的唯一入口：闲聊问答与全部遥感分析",
            },
        ]
        # 以下节点仅 GraphFlow 固定流水线使用；流内领域专家同样持有共享工具。
        + [
            {
                "name": spec.name,
                "label": spec.label,
                "tools": [*spec.tools, *shared],
                "description": f"GraphFlow 流内节点。{spec.description}",
            }
            for spec in domain_specs()
        ]
        + [
            {
                "name": "report_agent",
                "label": "报告生成",
                "tools": ["generate_report"],
                "description": "GraphFlow 收尾节点。",
            }
        ],
        "preset_flows": {name: list(seq) for name, seq in PRESET_FLOWS.items()},
    }


def dump_team_component(team: Any) -> dict[str, Any]:
    """完整的声明式配置（**含敏感字段，已脱敏但仅供本地调试**）。

    团队不可序列化时返回带 error 的占位而不是抛异常——这是个诊断接口，
    诊断接口自己把服务搞挂就本末倒置了。
    """
    try:
        component = team.dump_component()
        return redact(component.model_dump())
    except Exception as exc:
        logger.warning("团队配置无法序列化：%s", exc)
        return {"error": f"not_serializable: {exc}"}


def redact(payload: Any) -> Any:
    """递归抹掉密钥类字段。

    `dump_component()` 会把模型客户端配置一起序列化，里面有 api_key，
    直接返回等于把密钥写进接口响应和日志。
    """
    if isinstance(payload, dict):
        return {
            key: _REDACTED if _is_secret(key) else redact(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact(item) for item in payload]
    return payload


def _is_secret(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEYS)
