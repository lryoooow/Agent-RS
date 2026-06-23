from __future__ import annotations

import asyncio

from app.core.settings import get_settings

# 遥感工具 docker 执行的全局并发总闸。
# 病根：从 child.py 的 `await tool.runner(args)` → runner 的 `_client()` →
# rs_tools_client.call_tool → client.py 跑 `docker run`，全链路零并发控制；
# 10 人同点 detect/segment（各吃 6g）= 60g 内存瞬间被预定 → 打爆宿主机。
# 范式照搬 embedding/service.py:22 的 asyncio.Semaphore，但只控工具容器执行。
_semaphore: asyncio.Semaphore | None = None


def tool_semaphore() -> asyncio.Semaphore:
    """返回工具并发信号量（懒初始化）。

    懒建而非模块导入期建：asyncio.Semaphore 在首次 await 时绑定当前 event loop，
    懒建确保它绑定到真正运行工具的 loop，避免 import 期错绑到别的 loop。
    单线程 asyncio 下 `None 检查 → 赋值` 之间无 await 切换点，无竞态。
    取 max(1, ...) 兜底：settings 是裸字段无 Field 约束（与全文件风格一致），
    在此集中防御 0/负数配置，避免 Semaphore(0) 永久死锁。
    """
    global _semaphore
    if _semaphore is None:
        limit = max(1, get_settings().rs_tools_max_concurrent)
        _semaphore = asyncio.Semaphore(limit)
    return _semaphore


def reset_tool_semaphore() -> None:
    """重置信号量（仅供测试 teardown）。

    各测试用例跑在各自的 event loop 上，复用同一个跨 loop 绑定的信号量会报
    'bound to a different event loop'；teardown 调用本函数清空，下次按新 loop 重建。
    """
    global _semaphore
    _semaphore = None
