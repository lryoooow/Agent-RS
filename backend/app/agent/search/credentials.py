"""Request-scoped Tavily credentials.

The browser may provide a Tavily key for a local deployment.  It must never enter
conversation history, prompts, persistence metadata, traces, or logs, so search
code resolves it from a ContextVar instead of copying it through agent messages.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from app.core.settings import get_settings

_request_tavily_key: ContextVar[str | None] = ContextVar(
    "request_tavily_api_key", default=None
)


def resolve_tavily_api_key() -> str:
    return (_request_tavily_key.get() or get_settings().tavily_api_key).strip()


@contextmanager
def tavily_key_scope(api_key: str | None) -> Iterator[None]:
    # Async generators may resume under a copied Context.  Restore by value rather
    # than ContextVar.reset(token), matching the engine's turn_scope safety rule.
    previous = _request_tavily_key.get()
    _request_tavily_key.set((api_key or "").strip() or None)
    try:
        yield
    finally:
        _request_tavily_key.set(previous)
