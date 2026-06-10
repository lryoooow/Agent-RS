import pytest

from app.agent.domain_agents import (
    DOMAIN_GUIDANCE,
    DOMAIN_LABELS,
    TOOL_DOMAIN,
    DomainToolAgent,
    domain_for_tool,
)
from app.agent.routing import ALL_DOCUMENT_TOOLS, ALL_IMAGERY_TOOLS
from app.agent.types import AgentArtifact, AgentTrace, RuntimeToolCall, ToolRunResult


# ---------- 1. 归属正确性 ----------

def test_domain_for_tool_maps_all_tools() -> None:
    assert domain_for_tool("raster_inspect") == "spectral_agent"
    assert domain_for_tool("calculate_ndvi") == "spectral_agent"
    assert domain_for_tool("calculate_spectral_index") == "spectral_agent"
    assert domain_for_tool("render_band_composite") == "spectral_agent"
    assert domain_for_tool("segment_landcover") == "segmentation_agent"
    assert domain_for_tool("detect_objects") == "detection_agent"
    assert domain_for_tool("cloud_shadow_mask") == "preprocess_agent"
    assert domain_for_tool("extract_water_mask") == "preprocess_agent"
    assert domain_for_tool("clip_reproject_raster") == "preprocess_agent"
    assert domain_for_tool("parse_document") == "document_agent"
    assert domain_for_tool("ocr_recognize") == "document_agent"


def test_ocr_recognize_uses_imagery_route_but_document_domain() -> None:
    assert "ocr_recognize" in ALL_IMAGERY_TOOLS
    assert "ocr_recognize" not in ALL_DOCUMENT_TOOLS
    assert domain_for_tool("ocr_recognize") == "document_agent"


def test_domain_for_tool_unknown_returns_none() -> None:
    assert domain_for_tool("nonexistent_tool") is None


def test_every_domain_has_label() -> None:
    for domain in set(TOOL_DOMAIN.values()):
        assert domain in DOMAIN_LABELS


# ---------- 2. 派发正确性（领域 agent 委托底层工具执行器） ----------

class _StubToolChildAgent:
    """记录被委托执行的工具调用与 parent_run_id。"""

    instances: list["_StubToolChildAgent"] = []
    result_to_return: ToolRunResult | None = None

    def __init__(self, *, parent_run_id: str | None = None) -> None:
        self.parent_run_id = parent_run_id
        self.received: RuntimeToolCall | None = None
        _StubToolChildAgent.instances.append(self)

    async def run(self, tool_call, *, user_id, trace, on_event=None):
        self.received = tool_call
        if _StubToolChildAgent.result_to_return is not None:
            return _StubToolChildAgent.result_to_return
        return ToolRunResult(
            tool_context="stub-ok",
            geospatial_result={"type": "stub"},
            metadata={"echo": tool_call.name},
        )


@pytest.fixture
def stub_tool_child(monkeypatch):
    _StubToolChildAgent.instances = []
    _StubToolChildAgent.result_to_return = None
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
    assert result.tool_context.startswith("stub-ok")
    assert "min/max/mean/std/nodata" in result.tool_context
    assert result.geospatial_result == {"type": "stub"}
    assert result.metadata["echo"] == "calculate_ndvi"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("domain_name", "marker"),
    [
        ("spectral_agent", "min/max/mean/std/nodata"),
        ("detection_agent", "DOTA 15"),
        ("segmentation_agent", "LandCover.ai"),
        ("preprocess_agent", "阈值法粗筛"),
        ("document_agent", "文档全文"),
    ],
)
async def test_domain_agent_appends_static_guidance_on_success(stub_tool_child, domain_name: str, marker: str) -> None:
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="calculate_ndvi", arguments={"imagery_id": "94e758f38ede"})

    result = await DomainToolAgent(domain_name).run(call, user_id="u1", trace=trace, on_event=None)

    assert result.error is None
    assert result.tool_context.startswith("stub-ok\n\n")
    assert marker in result.tool_context


def test_spectral_guidance_keeps_thresholds_contextual() -> None:
    guidance = DOMAIN_GUIDANCE["spectral_agent"]

    assert ">0.6" not in guidance
    assert "0.2-0.5" not in guidance
    assert "min/max/mean/std/nodata" in guidance


@pytest.mark.asyncio
async def test_domain_agent_does_not_append_guidance_on_failure(stub_tool_child) -> None:
    stub_tool_child.result_to_return = ToolRunResult(tool_context="stub-failed", error="mcp_error")
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="detect_objects", arguments={"imagery_id": "94e758f38ede"})

    result = await DomainToolAgent("detection_agent").run(call, user_id="u1", trace=trace, on_event=None)

    assert result.error == "mcp_error"
    assert result.tool_context == "stub-failed"
    assert "DOTA 15" not in result.tool_context


@pytest.mark.asyncio
async def test_domain_agent_does_not_append_orphan_guidance_to_empty_context(stub_tool_child) -> None:
    stub_tool_child.result_to_return = ToolRunResult(tool_context="")
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="segment_landcover", arguments={"imagery_id": "94e758f38ede"})

    result = await DomainToolAgent("segmentation_agent").run(call, user_id="u1", trace=trace, on_event=None)

    assert result.tool_context == ""


@pytest.mark.asyncio
async def test_domain_agent_guidance_preserves_payload_fields(stub_tool_child) -> None:
    artifact = AgentArtifact(type="geospatial", payload={"type": "stub"})
    stub_tool_child.result_to_return = ToolRunResult(
        tool_context="stub-ok",
        geospatial_result={"type": "stub"},
        metadata={"echo": "value"},
        artifacts=[artifact],
    )
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="calculate_spectral_index", arguments={"imagery_id": "94e758f38ede"})

    result = await DomainToolAgent("spectral_agent").run(call, user_id="u1", trace=trace, on_event=None)

    assert result.tool_context.startswith("stub-ok")
    assert result.geospatial_result == {"type": "stub"}
    assert result.metadata == {"echo": "value"}
    assert result.artifacts == [artifact]


@pytest.mark.asyncio
async def test_ocr_recognize_receives_document_domain_guidance(stub_tool_child) -> None:
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="ocr_recognize", arguments={"imagery_id": "94e758f38ede"})

    result = await DomainToolAgent("document_agent").run(call, user_id="u1", trace=trace, on_event=None)

    takeover = [e for e in trace.events if e.stage == "child_agent_running"][0]
    assert takeover.metadata["agent_name"] == "document_agent"
    assert result.tool_context.startswith("stub-ok\n\n")
    assert "parse_document" in result.tool_context
    assert "ocr_recognize" in result.tool_context


@pytest.mark.asyncio
async def test_domain_agent_without_registered_guidance_passes_through(stub_tool_child) -> None:
    trace = AgentTrace(enabled=True)
    call = RuntimeToolCall(name="calculate_ndvi", arguments={"imagery_id": "94e758f38ede"})

    result = await DomainToolAgent("unregistered_agent").run(call, user_id="u1", trace=trace, on_event=None)

    assert result.tool_context == "stub-ok"


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


