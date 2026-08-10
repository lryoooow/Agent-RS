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
    """门面本身必须保持延迟导入，否则 AGENT_ENGINE=legacy 也会被迫加载 autogen。"""
    facade = ENGINE_ROOT / "__init__.py"
    hits = _imports_autogen(facade)
    assert not hits, (
        "app/agent/engine/__init__.py 不应在模块顶层导入 autogen（应走 __getattr__ 延迟导入）。\n"
        f"越界处：{hits}"
    )
