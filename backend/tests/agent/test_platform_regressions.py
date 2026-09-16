import importlib.util
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.agent.engine.model_client import BudgetAwareOpenAIClient, _COMPATIBLE_DEFAULT
from app.agent.engine.turn_context import turn_scope
from app.agent.tools.raster_inspect.formatter import format_raster_inspect_context


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [True, False])
async def test_active_imagery_only_promoted_after_ownership_check(monkeypatch, owned):
    from types import SimpleNamespace
    from app.agent.engine.input import build_turn_input
    from app.schemas.chat import ChatRequest, ChatMessage
    async def context(*args, **kwargs):
        return SimpleNamespace(messages=[])
    async def owns(imagery_id, user_id):
        assert imagery_id == "74e277eeaae6" and user_id == "user-one"
        return owned
    monkeypatch.setattr("app.agent.engine.input.build_provider_request_context", context)
    monkeypatch.setattr("app.agent.engine.input.user_owns_imagery", owns)
    request = ChatRequest(messages=[ChatMessage(role="user", content="影像在哪里")], metadata={"active_imagery_id": "74e277eeaae6"})
    turn = await build_turn_input(request, user_id="user-one")
    assert ("74e277eeaae6" in str(turn.initial_messages)) is owned


def load_compute(name, folder):
    path = Path(__file__).resolve().parents[3] / "docker" / folder / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_exhausted_tools_removed_from_provider_requests(monkeypatch):
    observed = []
    async def create(self, messages, *, tools, **kwargs):
        observed.append([tool["name"] for tool in tools])
        return "done"
    async def stream(self, messages, *, tools, **kwargs):
        observed.append([tool["name"] for tool in tools])
        yield "done"
    monkeypatch.setattr("autogen_ext.models.openai.OpenAIChatCompletionClient.create", create)
    monkeypatch.setattr("autogen_ext.models.openai.OpenAIChatCompletionClient.create_stream", stream)
    monkeypatch.setenv("AGENT_MAX_GPU_TOOL_CALLS", "1")
    client = BudgetAwareOpenAIClient(model="local-test", api_key="test", model_info=_COMPATIBLE_DEFAULT)
    tools = [{"name": name} for name in ("segment_instances", "detect_objects", "raster_inspect")]
    with turn_scope() as state:
        await client.create([], tools=tools)
        assert state.try_reserve("segment_instances")
        await client.create([], tools=tools)
        assert [v async for v in client.create_stream([], tools=tools)] == ["done"]
        state.release("segment_instances")
        await client.create([], tools=tools)
    assert observed == [["segment_instances", "detect_objects", "raster_inspect"], ["raster_inspect"], ["raster_inspect"], ["segment_instances", "detect_objects", "raster_inspect"]]
    await client.close()


def test_inspect_transforms_actual_projected_bounds(tmp_path):
    module = load_compute("compute_raster_inspect", "rs_tools")
    path = tmp_path / "image.tif"
    with rasterio.open(path, "w", driver="GTiff", width=20, height=10, count=1, dtype="uint8", crs="EPSG:4526", transform=from_origin(38500542.870824516, 2759545.04883242, 0.8, 0.8)) as dst:
        dst.write(np.ones((1, 10, 20), dtype="uint8"))
    result = module.inspect(str(path))
    assert 114 < result["center_wgs84"][0] < 115
    assert 24 < result["center_wgs84"][1] < 25
    assert result["bounds"][0] > 38000000
    text = format_raster_inspect_context("74e277eeaae6", result)
    assert "WGS84" in text and str(result["center_wgs84"]) in text
    assert "无需另行重投影" in text


@pytest.mark.asyncio
async def test_rgba_is_not_multispectral_and_rejects_alpha_as_nir(tmp_path):
    from app.services.imagery_persist import _extract_metadata
    from app.agent.tools.common import validate_band_indices
    path = tmp_path / "rgba.tif"
    data = np.full((4, 10, 10), 70, dtype="uint8")
    data[3] = 255
    with rasterio.open(path, "w", driver="GTiff", width=10, height=10, count=4, dtype="uint8", crs="EPSG:4526", transform=from_origin(38500000, 2700000, 1, 1)) as dst:
        dst.write(data)
        dst.colorinterp = (rasterio.enums.ColorInterp.red, rasterio.enums.ColorInterp.green, rasterio.enums.ColorInterp.blue, rasterio.enums.ColorInterp.alpha)
    meta = _extract_metadata(path)
    assert meta["band_roles"] == {"red": 1, "green": 2, "blue": 3}
    assert meta["band_roles_source"] == "colorinterp" and meta["alpha_bands"] == [4]
    assert "Alpha" in await validate_band_indices(path, {"nir": 4})
    inspected = load_compute("compute_raster_inspect", "rs_tools").inspect(str(path))
    assert inspected["capabilities"]["has_nir"] is False


def test_working_copy_preserves_spectral_descriptions_and_color_interpretation(tmp_path):
    from app.api.routes.imagery import _create_working_tif
    from app.core.settings import get_settings
    from app.services.imagery_persist import _extract_metadata
    path, output = tmp_path / "source.tif", tmp_path / "working.tif"
    with rasterio.open(path, "w", driver="GTiff", width=20, height=20, count=4, dtype="uint8", crs="EPSG:4526", transform=from_origin(38500000, 2700000, 1, 1)) as dst:
        dst.write(np.ones((4, 20, 20), dtype="uint8"))
        dst.colorinterp = (rasterio.enums.ColorInterp.gray,) + (rasterio.enums.ColorInterp.undefined,) * 3
        dst.descriptions = ("Blue", "Green", "Red", "NIR")
        dst.update_tags(SENSOR_ID="GF-2")
    _create_working_tif(path, output, get_settings())
    with rasterio.open(output) as src:
        assert src.colorinterp[-1].name == "undefined"
        assert src.descriptions[-1] == "NIR" and src.tags()["SENSOR_ID"] == "GF-2"
    assert _extract_metadata(output)["band_roles"]["nir"] == 4


def test_alpha_with_incomplete_color_tags_is_explicit_convention():
    from app.services.imagery_persist import _derive_band_roles
    roles, source = _derive_band_roles(4, [None] * 4, ["gray", "undefined", "undefined", "alpha"])
    assert roles == {"red": 1, "green": 2, "blue": 3}
    assert source == "positional_rgba"


@pytest.mark.asyncio
async def test_real_autogen_loop_converges_after_gpu_failure(monkeypatch):
    import json
    import httpx
    from openai import AsyncOpenAI
    from autogen_agentchat.agents import AssistantAgent
    from autogen_core.tools import FunctionTool
    from app.agent.engine.turn_context import current_turn_state
    calls = []
    def provider(request):
        payload = json.loads(request.content)
        calls.append(payload)
        names = [tool["function"]["name"] for tool in payload.get("tools", [])]
        if len(calls) == 1:
            assert "segment_instances" in names
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_test", "type": "function", "function": {"name": "segment_instances", "arguments": "{}"}}]}
            finish = "tool_calls"
        else:
            assert "segment_instances" not in names
            assert any(m.get("role") == "tool" and "服务不可用" in m.get("content", "") for m in payload["messages"])
            message = {"role": "assistant", "content": "分割服务不可用，需要修复服务。"}
            finish = "stop"
        return httpx.Response(200, json={"id": "test-completion", "model": "local-test", "object": "chat.completion", "created": 1, "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    async def segment() -> str:
        assert current_turn_state().try_reserve("segment_instances")
        return "服务不可用；停止重复请求。"
    monkeypatch.setenv("AGENT_MAX_GPU_TOOL_CALLS", "1")
    client = BudgetAwareOpenAIClient(model="local-test", api_key="test", model_info=_COMPATIBLE_DEFAULT)
    await client._client.close()
    client._client = AsyncOpenAI(api_key="test", base_url="https://provider.example/v1", http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    agent = AssistantAgent("test_agent", model_client=client, tools=[FunctionTool(segment, "Run segmentation", name="segment_instances")], reflect_on_tool_use=True, max_tool_iterations=5)
    with turn_scope():
        result = await agent.run(task="提取建筑")
    assert len(calls) == 2
    assert "需要修复服务" in result.messages[-1].content
    await client.close()
