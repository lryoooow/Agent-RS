"""engine/config_export.py：声明式配置导出与脱敏。

脱敏是这里唯一的安全要点：`dump_component()` 会把模型客户端配置一起序列化，
里面有 api_key，漏出去就等于把密钥写进接口响应和日志。
"""
from __future__ import annotations

import json

from app.agent.engine.config_export import (
    describe_orchestration,
    dump_team_component,
    redact,
)
from app.agent.engine.orchestrator import build_team


def test_description_lists_every_domain_agent() -> None:
    from app.agent.engine.agents import domain_specs

    described = describe_orchestration()
    names = {a["name"] for a in described["agents"]}
    assert {spec.name for spec in domain_specs()} <= names
    assert described["max_tool_iterations"] >= 1
    json.dumps(described, ensure_ascii=False)  # 必须能进 API 响应


def test_description_carries_tool_ownership() -> None:
    """暴露"哪个专家拿了哪些工具"——以前这些散在代码里，出问题只能读源码。"""
    described = describe_orchestration()
    by_name = {a["name"]: a for a in described["agents"]}
    assert "calculate_ndvi" in by_name["spectral_agent"]["tools"]
    assert "detect_objects" in by_name["detection_agent"]["tools"]
    assert "detect_objects" not in by_name["spectral_agent"]["tools"]


def test_redact_removes_secrets_at_any_depth() -> None:
    payload = {
        "provider": "openai",
        "config": {
            "api_key": "sk-realkey",
            "base_url": "https://api.deepseek.com",
            "nested": [{"token": "t0ken"}, {"harmless": "ok"}],
        },
    }
    cleaned = redact(payload)
    serialized = json.dumps(cleaned)
    assert "sk-realkey" not in serialized
    assert "t0ken" not in serialized
    # 非敏感字段必须原样保留，否则这个视图就没用了
    assert cleaned["config"]["base_url"] == "https://api.deepseek.com"
    assert cleaned["config"]["nested"][1]["harmless"] == "ok"


def test_dump_team_component_is_redacted() -> None:
    team = build_team(user_id="00000000-0000-4000-8000-000000000001")
    dumped = dump_team_component(team)
    serialized = json.dumps(dumped, ensure_ascii=False, default=str)
    # .env 里的真实 key 绝不能出现在 dump 里
    from app.core.settings import get_settings

    api_key = get_settings().ai_api_key
    if api_key:
        assert api_key not in serialized


def test_dump_failure_returns_placeholder_not_exception() -> None:
    """诊断接口自己把服务搞挂就本末倒置了。"""

    class Unserializable:
        def dump_component(self):
            raise RuntimeError("nope")

    result = dump_team_component(Unserializable())
    assert "error" in result
