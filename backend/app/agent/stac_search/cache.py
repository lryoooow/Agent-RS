"""场景缓存：搜索结果 → 后续预览/下载/导入的句柄存储。

按 user_id 隔离（越权 key 直接查不到），TTL 30 分钟、每用户 200 条封顶。
只在内存里——多 worker 部署时各进程各自缓存（搜索会重新写入，预览/下载
最多让用户重搜一次，不存在正确性问题；上 Redis 属于后续运维优化）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.agent.stac_search.model import SceneRecord

_TTL_SECONDS = 30 * 60
_MAX_PER_USER = 200

# user_id -> {scene_key -> (record, expires_at_monotonic)}
_CACHE: dict[str, dict[str, tuple[SceneRecord, float]]] = {}


def _sweep(user_id: str) -> None:
    bucket = _CACHE.get(user_id)
    if not bucket:
        return
    now = time.monotonic()
    expired = [key for key, (_, expires) in bucket.items() if expires <= now]
    for key in expired:
        bucket.pop(key, None)


def put_scenes(user_id: str | None, records: list[SceneRecord]) -> None:
    if not user_id or not records:
        return
    bucket = _CACHE.setdefault(user_id, {})
    _sweep(user_id)
    expires = time.monotonic() + _TTL_SECONDS
    for record in records:
        bucket[record.key] = (record, expires)
    # 超量淘汰最旧的（dict 保序即插入序）。
    while len(bucket) > _MAX_PER_USER:
        oldest = next(iter(bucket))
        bucket.pop(oldest, None)


def get_scene(user_id: str | None, key: str) -> SceneRecord | None:
    if not user_id or not key:
        return None
    bucket = _CACHE.get(user_id)
    if not bucket:
        return None
    entry = bucket.get(key)
    if entry is None:
        return None
    record, expires = entry
    if expires <= time.monotonic():
        bucket.pop(key, None)
        return None
    return record


def clear_all() -> None:
    """测试用：清空全部缓存。"""
    _CACHE.clear()


@dataclass(frozen=True)
class CacheStats:
    users: int
    scenes: int


def stats() -> CacheStats:
    return CacheStats(
        users=len(_CACHE),
        scenes=sum(len(bucket) for bucket in _CACHE.values()),
    )
