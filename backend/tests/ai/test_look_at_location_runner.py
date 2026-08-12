"""对话控图工具 look_at_location 回归：地名→坐标，写 turn_state + 回 metadata.map_target。"""
from __future__ import annotations

import pytest

from app.agent.engine.turn_context import turn_scope
from app.agent.tools.look_at_location.runner import run_look_at_location
from app.agent.tools.look_at_location.schema import LookAtLocationArguments


@pytest.mark.asyncio
async def test_look_at_location_success_sets_map_target(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_forward(query: str) -> dict:
        return {
            "display_name": "深圳南山",
            "center": [113.9, 22.5],
            "zoom": 12,
            "bbox": [[113.8, 22.4], [114.0, 22.6]],
        }

    monkeypatch.setattr("app.agent.tools.look_at_location.runner.forward_geocode", fake_forward)

    args = LookAtLocationArguments(query="深圳南山")
    with turn_scope() as state:
        result = await run_look_at_location(args)
        # autogen 链路：写入回合状态，编排层 mid-stream 取走发 map_control。
        assert state.map_target is not None
        assert state.map_target["center"] == [113.9, 22.5]
        assert state.map_target["bbox"] == [[113.8, 22.4], [114.0, 22.6]]

    # legacy 链路：map_target 在 metadata，runtime 取走发事件。
    assert result.error is None
    assert result.metadata["map_target"]["center"] == [113.9, 22.5]


@pytest.mark.asyncio
async def test_look_at_location_handles_unknown_place(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_none(query: str):
        return None

    monkeypatch.setattr("app.agent.tools.look_at_location.runner.forward_geocode", fake_none)

    result = await run_look_at_location(LookAtLocationArguments(query="不存在的地点XYZ"))
    assert result.error == "location_not_found"
