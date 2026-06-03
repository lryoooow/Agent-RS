"""In-memory TTL caches for web search decisions and results."""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CachedDecision(Enum):
    SEARCH = "search"
    NO_SEARCH = "no_search"


@dataclass(frozen=True)
class _CacheEntry:
    value: Any
    expires_at: float


def _normalize_query(query: str) -> str:
    text = query.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _hash_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


class TTLCache:
    """Simple in-memory LRU cache with TTL expiry."""

    def __init__(self, max_size: int, ttl_seconds: float) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry.expires_at:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return entry.value

    def put(self, key: str, value: Any) -> None:
        if key in self._store:
            del self._store[key]
        elif len(self._store) >= self._max_size:
            self._store.popitem(last=False)
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time.time() + self._ttl_seconds,
        )

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


class DecisionCache:
    """Cache for search/no-search decisions keyed by normalized query and scope."""

    def __init__(self, max_size: int = 256, ttl_seconds: float = 1800) -> None:
        self._cache = TTLCache(max_size=max_size, ttl_seconds=ttl_seconds)

    def get_decision(self, query: str, *, scope: str = "") -> CachedDecision | None:
        key = _hash_key(f"{scope}|{_normalize_query(query)}")
        return self._cache.get(key)

    def put_decision(self, query: str, decision: CachedDecision, *, scope: str = "") -> None:
        key = _hash_key(f"{scope}|{_normalize_query(query)}")
        self._cache.put(key, decision)

    def clear(self) -> None:
        self._cache.clear()


class ResultCache:
    """Cache for actual search results keyed by normalized query + max_results."""

    def __init__(self, max_size: int = 64, ttl_seconds: float = 300) -> None:
        self._cache = TTLCache(max_size=max_size, ttl_seconds=ttl_seconds)

    def get_results(self, query: str, max_results: int) -> dict[str, Any] | None:
        key = _hash_key(f"{_normalize_query(query)}|{max_results}")
        return self._cache.get(key)

    def put_results(self, query: str, max_results: int, results: dict[str, Any]) -> None:
        key = _hash_key(f"{_normalize_query(query)}|{max_results}")
        self._cache.put(key, results)

    def clear(self) -> None:
        self._cache.clear()


_decision_cache: DecisionCache | None = None
_result_cache: ResultCache | None = None


def get_decision_cache() -> DecisionCache:
    global _decision_cache
    if _decision_cache is None:
        from app.shared.settings import get_settings
        s = get_settings()
        _decision_cache = DecisionCache(
            max_size=s.agent_decision_cache_max_size,
            ttl_seconds=s.agent_decision_cache_ttl_seconds,
        )
    return _decision_cache


def get_result_cache() -> ResultCache:
    global _result_cache
    if _result_cache is None:
        from app.shared.settings import get_settings
        s = get_settings()
        _result_cache = ResultCache(
            max_size=s.agent_result_cache_max_size,
            ttl_seconds=s.agent_result_cache_ttl_seconds,
        )
    return _result_cache
