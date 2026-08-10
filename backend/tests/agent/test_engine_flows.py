"""engine/flows.py：预设链路的领域名漂移检测。

PRESET_FLOWS 引用 domain_specs() 里的领域名，如果领域改名只在运行时 build_flow
才暴露 KeyError。这里用参数化测试钉死一致性。
"""
from __future__ import annotations

import pytest

from app.agent.engine.agents import domain_specs
from app.agent.engine.flows import PRESET_FLOWS, available_flows


def _all_domain_names() -> set[str]:
    return {spec.name for spec in domain_specs()}


@pytest.mark.parametrize("flow_name", sorted(PRESET_FLOWS))
def test_preset_flow_references_existing_domains(flow_name: str) -> None:
    """每条预设链路的领域名都必须在 domain_specs() 中存在。"""
    names = PRESET_FLOWS[flow_name]
    valid = _all_domain_names()
    for domain in names:
        assert domain in valid, (
            f"链路 {flow_name!r} 引用了不存在的领域 {domain!r}。"
            f"当前 domain_specs(): {sorted(valid)}"
        )


def test_preset_flows_are_non_empty() -> None:
    """每条链路至少有一个节点。"""
    for name, sequence in PRESET_FLOWS.items():
        assert len(sequence) >= 2, f"链路 {name!r} 至少需要两个节点才有意义"


def test_available_flows_matches_preset_keys() -> None:
    """available_flows() 返回的列表与 PRESET_FLOWS 键一致。"""
    assert available_flows() == sorted(PRESET_FLOWS)


def test_unknown_flow_raises_key_error() -> None:
    """未知链路名 → KeyError（在用 model_client 之前就抛）。"""
    from unittest.mock import MagicMock
    from app.agent.engine.flows import build_flow

    with pytest.raises(KeyError, match="未知链路"):
        build_flow("nonexistent_flow", model_client=MagicMock())
