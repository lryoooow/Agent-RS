"""imagery_search runner：检索成功 / 零结果 / 源失败 / 地名解析失败四条路径。

重点安全断言：给模型的 tool_context 只含场景 key 与摘要，
**不含任何 http(s) 资产 URL**（防提示词泄漏）；卡片数据（geospatial_result）
里的 URL 是本平台相对路径。
"""

from __future__ import annotations

import pytest

from app.agent.stac_search.model import SceneRecord
from app.agent.stac_search.sources import StacSearchError
from app.agent.tools.imagery_search.runner import run_imagery_search
from app.agent.tools.imagery_search.schema import ImagerySearchArguments


def _record(key: str = "ab12cd34ef56") -> SceneRecord:
    return SceneRecord(
        key=key, source="earthsearch", item_id="S2B_TEST", collection="c",
        satellite="Sentinel-2B", datetime="2026-08-11T03:11:32+00:00",
        cloud_cover=5.0, bbox=[113.9, 22.4, 114.3, 22.7], resolution_m=10.0,
        band_assets={"red": "https://secret-asset-url/B04.tif"},
        display_name="S2B_TEST",
    )


def _args(**overrides) -> ImagerySearchArguments:
    base = {"bbox": [113.9, 22.4, 114.3, 22.7], "reason": "找影像"}
    base.update(overrides)
    return ImagerySearchArguments(**base)


def _patch_search(monkeypatch, records, notes=None, error: str | None = None):
    async def fake_search(**kwargs):
        if error:
            raise StacSearchError(error)
        return list(records), list(notes or [])

    monkeypatch.setattr("app.agent.tools.imagery_search.runner.search_scenes", fake_search)


@pytest.mark.asyncio
async def test_runner_success_builds_cards_without_leaking_urls(monkeypatch) -> None:
    record = _record()
    _patch_search(monkeypatch, [record])

    result = await run_imagery_search(_args())

    assert result.error is None
    assert "S2B_TEST" in result.tool_context
    assert record.key in result.tool_context
    assert "http" not in result.tool_context, "资产 URL 不得进模型上下文"

    cards = result.geospatial_result
    assert cards["type"] == "scene_search"
    scene = cards["scenes"][0]
    assert scene["key"] == record.key
    assert scene["preview_url"] == f"/api/scenes/{record.key}/preview"
    assert scene["download_url"] == f"/api/scenes/{record.key}/download"
    assert "secret-asset-url" not in str(cards), "SAS/资产 URL 只留服务端"


@pytest.mark.asyncio
async def test_runner_empty_results_suggests_widening(monkeypatch) -> None:
    _patch_search(monkeypatch, [])
    result = await run_imagery_search(_args(cloud_max=5))
    assert result.error is None
    assert "没有找到" in result.tool_context
    assert "放宽" in result.tool_context


@pytest.mark.asyncio
async def test_runner_source_failure_is_honest(monkeypatch) -> None:
    _patch_search(monkeypatch, [], error="两个源都超时")
    result = await run_imagery_search(_args())
    assert result.error == "stac_unavailable"
    assert "不可用" in result.tool_context
    assert "不要编造" in result.tool_context


@pytest.mark.asyncio
async def test_runner_place_unresolved(monkeypatch) -> None:
    async def fake_geocode(_q):
        return None

    monkeypatch.setattr(
        "app.agent.tools.imagery_search.runner.forward_geocode", fake_geocode
    )
    result = await run_imagery_search(_args(bbox=None, place="不存在的地方"))
    assert result.error == "place_unresolved"


@pytest.mark.asyncio
async def test_runner_place_resolves_to_bbox(monkeypatch) -> None:
    captured: dict = {}
    record = _record()

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return [record], []

    async def fake_geocode(_q):
        return {"display_name": "深圳", "center": [114.06, 22.55], "zoom": 11}

    monkeypatch.setattr("app.agent.tools.imagery_search.runner.search_scenes", fake_search)
    monkeypatch.setattr(
        "app.agent.tools.imagery_search.runner.forward_geocode", fake_geocode
    )
    result = await run_imagery_search(_args(bbox=None, place="深圳"))
    assert result.error is None
    assert captured["bbox"][0] == pytest.approx(113.91)
