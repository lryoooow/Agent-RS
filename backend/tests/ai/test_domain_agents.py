import pytest

from app.agent.domain_agents import (
    DOMAIN_LABELS,
    TOOL_DOMAIN,
    DomainToolAgent,
    domain_for_tool,
)
from app.agent.types import AgentTrace, RuntimeToolCall, ToolRunResult


# ---------- 1. 归属正确性 ----------

def test_domain_for_tool_maps_all_six_tools() -> None:
    assert domain_for_tool("raster_inspect") == "spectral_agent"
    assert domain_for_tool("calculate_ndvi") == "spectral_agent"
    assert domain_for_tool("calculate_spectral_index") == "spectral_agent"
    assert domain_for_tool("render_band_composite") == "spectral_agent"
    assert domain_for_tool("segment_landcover") == "segmentation_agent"
    assert domain_for_tool("detect_objects") == "detection_agent"


def test_domain_for_tool_unknown_returns_none() -> None:
    assert domain_for_tool("nonexistent_tool") is None


def test_every_domain_has_label() -> None:
    for domain in set(TOOL_DOMAIN.values()):
        assert domain in DOMAIN_LABELS


# ---------- 2. 派发正确性（领域 agent 委托底层工具执行器） ----------

class _StubToolChildAgent:
    """记录被委托执行的工具调用与 parent_run_id。"""

    instances: list["_StubToolChildAgent"] = []

    def __init__(self, *, parent_run_id: str | None = None) -> None:
        self.parent_run_id = parent_run_id
        self.received: RuntimeToolCall | None = None
        _StubToolChildAgent.instances.append(self)

    async def run(self, tool_call, *, user_id, trace, on_event=None):
        self.received = tool_call
        return ToolRunResult(
            tool_context="stub-ok",
            geospatial_result={"type": "stub"},
            metadata={"echo": tool_call.name},
        )


@pytest.fixture
def stub_tool_child(monkeypatch):
    _StubToolChildAgent.instances = []
    monkeypatch.setattr(
        "app.agent.domain_agents.ToolChildAgent", _StubToolChildAgent
    )
    return _StubToolChildAgent


@pytest.mark.asyncio
async def test_domain_agent_delegates_to_tool_child(stub_tool_child) -> None:
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="calculate_ndvi", arguments={"imagery_id": "94e758f38ede"})
    await DomainToolAgent("spectral_agent").run(call, user_id="u1", trace=trace, on_event=None)
    assert len(stub_tool_child.instances) == 1
    assert stub_tool_child.instances[0].received is call


# ---------- 3. trace 局部上下文 ----------

@pytest.mark.asyncio
async def test_domain_agent_emits_local_context_event(stub_tool_child) -> None:
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="segment_landcover", arguments={"imagery_id": "94e758f38ede"})
    await DomainToolAgent("segmentation_agent").run(call, user_id="u1", trace=trace, on_event=None)
    takeover = [e for e in trace.events if e.stage == "child_agent_running"][0]
    assert takeover.metadata["agent_name"] == "segmentation_agent"
    assert takeover.metadata["domain_label"] == "地物分类"
    assert takeover.metadata["child_run_id"]


@pytest.mark.asyncio
async def test_domain_agent_child_run_id_is_unique(stub_tool_child) -> None:
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="detect_objects", arguments={"imagery_id": "94e758f38ede"})
    agent = DomainToolAgent("detection_agent")
    await agent.run(call, user_id="u1", trace=trace, on_event=None)
    await agent.run(call, user_id="u1", trace=trace, on_event=None)
    run_ids = [e.metadata["child_run_id"] for e in trace.events if e.stage == "child_agent_running"]
    assert len(run_ids) == 2 and run_ids[0] != run_ids[1]
    # 领域 agent 的 child_run_id 作为底层工具执行器的 parent，形成上下文链
    assert {inst.parent_run_id for inst in stub_tool_child.instances} == set(run_ids)


# ---------- 4. 执行结果透传（不吞掉底层结果） ----------

@pytest.mark.asyncio
async def test_domain_agent_passes_through_result(stub_tool_child) -> None:
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="calculate_ndvi", arguments={"imagery_id": "94e758f38ede"})
    result = await DomainToolAgent("spectral_agent").run(call, user_id="u1", trace=trace, on_event=None)
    assert result.tool_context == "stub-ok"
    assert result.geospatial_result == {"type": "stub"}
    assert result.metadata["echo"] == "calculate_ndvi"


# ---------- 5. runtime 未知工具回退 ----------

@pytest.mark.asyncio
async def test_runtime_unknown_tool_falls_back_to_tool_child(monkeypatch) -> None:
    import app.agent.runtime as runtime_mod

    fallback_calls: list[RuntimeToolCall] = []

    class _FallbackToolChild:
        def __init__(self, *, parent_run_id=None) -> None:
            pass

        async def run(self, tool_call, *, user_id, trace, on_event=None):
            fallback_calls.append(tool_call)
            return ToolRunResult(tool_context="fallback")

    monkeypatch.setattr(runtime_mod, "ToolChildAgent", _FallbackToolChild)
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="unregistered_tool", arguments={})
    result = await runtime_mod.AgentRuntime().run_tool_call(
        call, trace=trace, on_event=None, user_id="u1"
    )
    assert result.tool_context == "fallback"
    assert fallback_calls == [call]


