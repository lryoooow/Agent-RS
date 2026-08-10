"""AutoGen 编排层适配门面。

**本包是整个后端唯一允许 import `autogen_*` 的地方。** 其余业务代码
（`app/api`、`app/services`、`app/agent` 其它模块）一律 `from app.agent.engine import ...`。

## 为什么要这一层

AutoGen 官方已进入 maintenance mode（`README.md` 原文："It will not receive new features
or enhancements and is community managed going forward"），推荐的继任者是 Microsoft Agent
Framework。把框架接触面收在一个包里，将来换框架只改这里，业务代码不动。

这条边界由 `tests/test_engine_boundary.py` 守着，越界会让测试直接失败。

## 双引擎并存

迁移期 `AGENT_ENGINE=legacy|autogen` 两条链路并存（见 `app/core/settings.py`）：

- `legacy`  —— 自研规划器链路：`AgentRuntime` → `TaskSelector` → `LLMCapabilityPlanner`
- `autogen` —— 本包提供的 AutoGen 链路

出问题改一行配置即可回滚。阶段 7 迁移完成后删除 legacy 分支，本开关一并退役。

## 延迟导入

本模块用 PEP 562 的 `__getattr__` 做**延迟导入**：`AGENT_ENGINE=legacy` 时不会真正
加载 autogen（省下约 1 秒 import 开销，也让未装 autogen 的环境仍能跑 legacy 链路）。
所以这里**不要**在模块顶层 `from autogen_... import ...`。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.settings import get_settings

__all__ = [
    "autogen_engine_enabled",
    "require_autogen_engine",
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
    "build_team",
    "run_turn",
    "stream_turn",
    "OrchestrationResult",
    "build_flow",
    "available_flows",
]

# 子模块导出名 -> 所在模块。随各阶段落地逐步补齐；写在这里而不是顶层 import，
# 是为了让 legacy 环境完全不加载 autogen。
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
    "build_team": "app.agent.engine.orchestrator",
    "run_turn": "app.agent.engine.orchestrator",
    "stream_turn": "app.agent.engine.orchestrator",
    "OrchestrationResult": "app.agent.engine.orchestrator",
    "build_flow": "app.agent.engine.flows",
    "available_flows": "app.agent.engine.flows",
}

if TYPE_CHECKING:  # pragma: no cover - 只为类型检查器，运行期不执行
    pass


def autogen_engine_enabled() -> bool:
    """当前是否启用 AutoGen 编排引擎。"""
    return get_settings().agent_engine == "autogen"


def require_autogen_engine() -> None:
    """在只应由 AutoGen 链路走到的代码里做断言，避免 legacy 配置下被误调。"""
    if not autogen_engine_enabled():
        raise RuntimeError(
            "当前 AGENT_ENGINE=legacy，不应进入 AutoGen 链路。"
            "要启用请设置 AGENT_ENGINE=autogen。"
        )


def __getattr__(name: str) -> Any:
    """延迟导入子模块里的导出符号（PEP 562）。"""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *_LAZY_EXPORTS])
