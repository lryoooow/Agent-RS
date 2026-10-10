"""Per-loop bounded preprocessing slots; callers settle native work before release."""
from __future__ import annotations
import asyncio
import weakref
_limits=weakref.WeakKeyDictionary()


def resource_semaphore(name: str, concurrency: int):
    per_loop=_limits.setdefault(asyncio.get_running_loop(),{})
    return per_loop.setdefault(name,asyncio.Semaphore(max(1,concurrency)))
