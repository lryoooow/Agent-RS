"""Framework-neutral request context shared with tool runners."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Callable


AnalysisProvider = Callable[[], list[dict]]
_analysis_provider: ContextVar[AnalysisProvider | None] = ContextVar(
    "agent_rs_analysis_provider", default=None
)


def current_analysis_results() -> list[dict]:
    """Return successful analyses from the active turn, if one exists."""

    provider = _analysis_provider.get()
    return list(provider()) if provider is not None else []


def swap_analysis_provider(provider: AnalysisProvider | None) -> AnalysisProvider | None:
    """Install a provider and return the previous value for explicit restore."""

    previous = _analysis_provider.get()
    _analysis_provider.set(provider)
    return previous
