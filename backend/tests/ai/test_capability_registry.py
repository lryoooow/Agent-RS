from __future__ import annotations

from app.agent.capability_registry import (
    get_capability,
    is_capability_enabled,
    list_capabilities,
)
from app.agent.tool_registry import TOOLS
from app.core.settings import get_settings


def reset_settings() -> None:
    get_settings.cache_clear()


def test_web_search_is_registered_as_agent(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()

    capability = get_capability("web_search")

    assert capability is not None
    assert capability.kind == "agent"
    assert capability.is_enabled() is True


def test_imagery_tools_are_composed_from_tool_registry() -> None:
    capability = get_capability("calculate_ndvi")

    assert capability is not None
    assert capability.kind == "tool"
    assert capability.tool is TOOLS["calculate_ndvi"]


def test_disabled_web_search_is_not_available(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "")
    reset_settings()

    assert is_capability_enabled("web_search") is False
    assert "web_search" not in {capability.name for capability in list_capabilities(kind="agent")}


def test_unknown_capability_returns_none() -> None:
    assert get_capability("missing") is None
    assert is_capability_enabled("missing") is False
