"""AutoGen 编排层适配门面。

**本包是整个后端唯一允许 import `autogen_*` 的地方。** 其余业务代码
（`app/api`、`app/services`、`app/agent` 其它模块）一律 `from app.agent.engine import ...`。

## 为什么要这一层

AutoGen 官方已进入 maintenance mode（`README.md` 原文："It will not receive new features
or enhancements and is community managed going forward"），推荐的继任者是 Microsoft Agent
Framework。把框架接触面收在一个包里，将来换框架只改这里，业务代码不动。

这条边界由 `tests/test_engine_boundary.py` 守着，越界会让测试直接失败。

## 延迟导入

本模块用 PEP 562 的 `__getattr__` 保持门面轻量；生产聊天入口会直接加载服务层，
AutoGen 缺失或版本不兼容时应用启动/导入立即失败，不存在静默回退引擎。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    # 以下经 __getattr__ 延迟导入
    "build_model_client",
    "resolve_model_info",
    "thinking_extra_body",
    "build_tools",
    "build_tool_map",
    "turn_scope",
    "current_turn_state",
    "TurnToolState",
    "RagMemory",
    "PgVectorMemory",
    "BudgetedChatCompletionContext",
    "run_turn",
    "stream_turn",
    "OrchestrationResult",
    "build_flow",
    "available_flows",
    "MemoryDecision",
    "decide_memory",
    "complete_turn",
    "stream_turn_events",
]

# 子模块导出名 -> 所在模块。
_LAZY_EXPORTS: dict[str, str] = {
    "build_model_client": "app.agent.engine.model_client",
    "resolve_model_info": "app.agent.engine.model_client",
    "thinking_extra_body": "app.agent.engine.model_client",
    "build_tools": "app.agent.engine.tools",
    "build_tool_map": "app.agent.engine.tools",
    "turn_scope": "app.agent.engine.turn_context",
    "current_turn_state": "app.agent.engine.turn_context",
    "TurnToolState": "app.agent.engine.turn_context",
    "RagMemory": "app.agent.engine.memory",
    "PgVectorMemory": "app.agent.engine.memory",
    "BudgetedChatCompletionContext": "app.agent.engine.context",
    "run_turn": "app.agent.engine.orchestrator",
    "stream_turn": "app.agent.engine.orchestrator",
    "OrchestrationResult": "app.agent.engine.orchestrator",
    "build_flow": "app.agent.engine.flows",
    "available_flows": "app.agent.engine.flows",
    "MemoryDecision": "app.agent.engine.memory_judge",
    "decide_memory": "app.agent.engine.memory_judge",
    "complete_turn": "app.agent.engine.service",
    "stream_turn_events": "app.agent.engine.service",
}

if TYPE_CHECKING:  # pragma: no cover - 只为类型检查器，运行期不执行
    pass


def __getattr__(name: str) -> Any:
    """延迟导入子模块里的导出符号（PEP 562）。"""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *_LAZY_EXPORTS])
