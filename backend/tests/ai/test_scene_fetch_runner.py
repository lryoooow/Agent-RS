"""scene_fetch runner：场景导入的成功 / 过期 / 失败三条路径。"""

from __future__ import annotations

import pytest

from app.agent.stac_search.cache import clear_all, put_scenes
from app.agent.stac_search.importer import SceneImportError
from app.agent.stac_search.model import SceneRecord
from app.agent.tools.scene_fetch.runner import run_scene_fetch
from app.agent.tools.scene_fetch.schema import SceneFetchArguments


def _record() -> SceneRecord:
    return SceneRecord(
        key="ab12cd34ef56", source="earthsearch", item_id="S2B_TEST", collection="c",
        satellite="Sentinel-2B", datetime="2026-08-11T03:11:32+00:00",
        cloud_cover=5.0, bbox=[113.9, 22.4, 114.3, 22.7], resolution_m=10.0,
        band_assets={"red": "u", "blue": "u", "green": "u", "nir": "u", "swir": "u"},
        display_name="S2B_TEST",
    )


def _args(key: str = "ab12cd34ef56") -> SceneFetchArguments:
    return SceneFetchArguments(scene_key=key, reason="导入分析")


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_all()
    yield
    clear_all()


@pytest.mark.asyncio
async def test_fetch_success_reports_imagery_and_roles(monkeypatch) -> None:
    put_scenes("u1", [_record()])

    async def fake_import(record, user_id):
        return {
            "imagery_id": "0123456789ab",
            "item_id": record.item_id,
            "satellite": record.satellite,
            "band_roles": record.band_roles,
        }

    monkeypatch.setattr(
        "app.agent.tools.scene_fetch.runner.peek_current_user_id", lambda: "u1"
    )
    monkeypatch.setattr(
        "app.agent.tools.scene_fetch.runner.import_scene_as_imagery", fake_import
    )

    result = await run_scene_fetch(_args())
    assert result.error is None
    assert "0123456789ab" in result.tool_context
    assert "S2B_TEST" in result.tool_context
    # 波段角色随导入说明回给模型，后续分析工具调用不再瞎猜波段号。
    assert "blue=B1" in result.tool_context and "swir=B5" in result.tool_context


@pytest.mark.asyncio
async def test_fetch_expired_scene_tells_model_to_research(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent.tools.scene_fetch.runner.peek_current_user_id", lambda: "u1"
    )
    result = await run_scene_fetch(_args("ffffffffffff"))
    assert result.error == "scene_not_found"
    assert "重新" in result.tool_context and "search_imagery" in result.tool_context
    assert "不要假装" in result.tool_context


@pytest.mark.asyncio
async def test_fetch_failure_is_honest(monkeypatch) -> None:
    put_scenes("u1", [_record()])

    async def boom(_record, _user_id):
        raise SceneImportError("远程读取失败")

    monkeypatch.setattr(
        "app.agent.tools.scene_fetch.runner.peek_current_user_id", lambda: "u1"
    )
    monkeypatch.setattr("app.agent.tools.scene_fetch.runner.import_scene_as_imagery", boom)

    result = await run_scene_fetch(_args())
    assert result.error == "scene_import_failed"
    assert "导入失败" in result.tool_context and "不要编造" in result.tool_context
