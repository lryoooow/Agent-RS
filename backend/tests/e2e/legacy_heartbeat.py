"""故障对照样本，仅供测试：逐字保留修复前的心跳函数。

来源：backend/app/api/routes/chat.py @ 3f58b83db6f5360c16e8a51bcfbeebf091cca6f7
提取时只补齐函数所需导入和常量，不修改函数主体。
这里的请求上下文丢失是待复现的历史缺陷，禁止在生产代码引用。
固定样本使仓库新克隆、源码归档和浅克隆均能验证修复。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing

_SSE_HEARTBEAT_SECONDS = 15.0


async def stream_with_heartbeat(
    source: AsyncIterator[str],
    *,
    interval_seconds: float = _SSE_HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """Forward an SSE stream and emit comments while a tool is silent.

    Long raster imports can spend minutes inside one tool call.  Without bytes on
    the wire, the browser's idle watchdog treats a healthy request as failed and
    disconnects while the durable tool job continues in the background.
    """
    async with aclosing(source) as stream:
        pending = asyncio.create_task(anext(stream))
        try:
            while True:
                done, _ = await asyncio.wait({pending}, timeout=interval_seconds)
                if not done:
                    yield ": keepalive\n\n"
                    continue
                try:
                    item = pending.result()
                except StopAsyncIteration:
                    return
                yield item
                pending = asyncio.create_task(anext(stream))
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
