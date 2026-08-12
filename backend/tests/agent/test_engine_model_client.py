"""engine/model_client.py 的单元测试（不打真实网络）。"""
from __future__ import annotations

import json

import pytest

from app.agent.config import ResolvedAIConfig
from app.agent.engine.model_client import (
    _COMPATIBLE_DEFAULT,
    build_model_client,
    resolve_model_info,
    thinking_extra_body,
)
from app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _config(model: str = "deepseek-v4-pro") -> ResolvedAIConfig:
    return ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        model=model,
        timeout_seconds=30,
        max_retries=1,
        trust_env_proxy=False,
    )


def test_known_openai_model_uses_autogen_inference() -> None:
    info = resolve_model_info("gpt-4.1-mini")
    assert info["family"] == "gpt-41"
    assert info["vision"] is True  # AutoGen 推断出来的，不是我们的默认集


def test_unknown_model_falls_back_to_compatible_default() -> None:
    """OpenAI 兼容端点的模型名 AutoGen 不认识，必须落到默认集而不是抛错。"""
    info = resolve_model_info("deepseek-v4-pro")
    assert info == _COMPATIBLE_DEFAULT
    # function_calling 是整个迁移的前提，默认集必须给 True
    assert info["function_calling"] is True


def test_model_info_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """换到不支持 function calling 的供应商时，能用配置关掉。"""
    monkeypatch.setenv("AGENT_MODEL_INFO", json.dumps({"function_calling": False, "vision": True}))
    get_settings.cache_clear()
    info = resolve_model_info("deepseek-v4-pro")
    assert info["function_calling"] is False
    assert info["vision"] is True
    # 未覆盖的字段仍来自默认集
    assert info["json_output"] is _COMPATIBLE_DEFAULT["json_output"]


def test_model_info_override_rejects_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_INFO", "{不是JSON")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="AGENT_MODEL_INFO"):
        resolve_model_info("deepseek-v4-pro")


def test_thinking_extra_body_shapes() -> None:
    assert thinking_extra_body(enable=False) == {"enable_thinking": False}
    enabled = thinking_extra_body(enable=True)
    assert enabled["enable_thinking"] is True
    assert enabled["thinking_budget"] == get_settings().ai_thinking_budget


def test_build_model_client_wires_config() -> None:
    client = build_model_client(_config())
    args = client._create_args  # noqa: SLF001 - 断言透传，没有公开访问器
    assert args["model"] == "deepseek-v4-pro"
    assert args["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": get_settings().ai_thinking_budget,
    }


def test_router_client_disables_thinking_and_honours_router_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_ROUTER_MODEL", "deepseek-v4-flash")
    get_settings.cache_clear()
    client = build_model_client(_config(), for_routing=True, max_tokens=1024)
    args = client._create_args  # noqa: SLF001
    assert args["model"] == "deepseek-v4-flash"
    assert args["extra_body"] == {"enable_thinking": False}
    assert args["max_tokens"] == 1024


def test_routing_client_falls_back_to_main_model_when_unset() -> None:
    client = build_model_client(_config(), for_routing=True)
    assert client._create_args["model"] == "deepseek-v4-pro"  # noqa: SLF001
