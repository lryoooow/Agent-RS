"""守住「只有 app/agent/engine/ 能碰 autogen」这条架构边界。

AutoGen 已进入 maintenance mode，继任者是 Microsoft Agent Framework。把框架接触面
收在一个包里，将来换框架只改适配层。这条约束靠人自觉守不住，所以用测试钉死。

一旦有人在业务代码里直接 `import autogen_core` 之类，这个测试立刻失败并指出文件与行号。
"""
from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
ENGINE_ROOT = APP_ROOT / "agent" / "engine"
LEGACY_AGENT_MODULES = {
    "runtime.py",
    "child.py",
    "domain_agents.py",
    "search_agent.py",
    "tool_selector.py",
    "llm_planner.py",
    "plan_validator.py",
    "capability_registry.py",
    "routing.py",
    "provider.py",
    "normalizer.py",
}


def _imports_autogen(path: Path) -> list[tuple[int, str]]:
    """返回该文件中所有直接导入 autogen 的 (行号, 模块名)。"""
    # utf-8-sig：项目里若干文件带 UTF-8 BOM（如 agent/types.py、tools/ndvi/runner.py），
    # 用普通 utf-8 读会把 ﻿ 留在首行，ast.parse 直接 SyntaxError。
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0].startswith("autogen"):
                    hits.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root.startswith("autogen"):
                hits.append((node.lineno, node.module or ""))
    return hits


def test_only_engine_package_imports_autogen() -> None:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if ENGINE_ROOT in path.parents:
            continue
        for lineno, module in _imports_autogen(path):
            rel = path.relative_to(APP_ROOT.parent)
            violations.append(f"{rel}:{lineno} 直接导入了 {module}")

    assert not violations, (
        "只有 app/agent/engine/ 可以 import autogen_*，业务代码必须经适配层。\n"
        "越界处：\n  " + "\n  ".join(violations)
    )


def test_engine_facade_does_not_import_autogen_at_module_level() -> None:
    """门面保持延迟导入，让轻量配置/诊断代码无需初始化框架依赖。"""
    facade = ENGINE_ROOT / "__init__.py"
    hits = _imports_autogen(facade)
    assert not hits, (
        "app/agent/engine/__init__.py 不应在模块顶层导入 autogen（应走 __getattr__ 延迟导入）。\n"
        f"越界处：{hits}"
    )


def test_business_code_uses_only_the_engine_facade() -> None:
    """业务层不得依赖 engine 内部布局，所有框架调用必须穿过稳定门面。"""
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if ENGINE_ROOT in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "app.agent.engine."
            ):
                rel = path.relative_to(APP_ROOT.parent)
                violations.append(f"{rel}:{node.lineno} import {node.module}")
    assert not violations, "业务代码绕过 app.agent.engine 门面：\n  " + "\n  ".join(violations)


def test_legacy_agent_runtime_modules_are_absent() -> None:
    agent_root = APP_ROOT / "agent"
    present = sorted(name for name in LEGACY_AGENT_MODULES if (agent_root / name).exists())
    assert not present, f"旧 Agent 引擎模块重新出现：{present}"


def test_openai_sdk_outside_engine_is_embedding_only() -> None:
    """生成式 SDK 调用不得绕开 AutoGen；embedding 是唯一允许的确定性例外。"""
    violations: list[str] = []
    embedding_root = APP_ROOT / "agent" / "embedding"
    for path in sorted(APP_ROOT.rglob("*.py")):
        if ENGINE_ROOT in path.parents or embedding_root in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            if any(part.split(".")[0] == "openai" for part in module.split(",")):
                rel = path.relative_to(APP_ROOT.parent)
                violations.append(f"{rel}:{node.lineno} import {module}")
    assert not violations, "生成式 OpenAI SDK 调用绕开 AutoGen：\n  " + "\n  ".join(violations)


def test_no_agent_core_imports_api_layer() -> None:
    """agent 核心层禁止向上依赖 HTTP 层（P4.5 修复①的回归闸）。

    stac importer 曾延迟导入 routes/imagery 的私有持久化函数——
    延迟导入能躲过运行时环，但方向错误；此断言连延迟导入一起拦。
    """
    import ast

    backend = Path(__file__).resolve().parents[1]
    for path in (backend / "app" / "agent").rglob("*.py"):
        if "engine" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                targets = [node.module]
            for target in targets:
                assert not target.startswith("app.api"), (
                    f"{path} 向上依赖 HTTP 层：{target}"
                )


def test_tool_runners_do_not_import_engine() -> None:
    """业务工具 runner 禁止感知编排层（P4.5 修复②的回归闸）。

    编排产物（map_target 等）只能经 ToolRunResult 数据通道回流，
    由 engine 包装层转移；runner 直连 engine 会构成包级循环。
    """
    import ast

    backend = Path(__file__).resolve().parents[1]
    for path in (backend / "app" / "agent" / "tools").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                targets = [node.module]
            for target in targets:
                assert not target.startswith("app.agent.engine"), (
                    f"{path} 直连编排层：{target}"
                )
