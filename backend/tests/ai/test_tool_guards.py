from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.routing import ALL_DOCUMENT_TOOLS, ALL_IMAGERY_TOOLS
from app.agent.tool_guards import validate_tool_access
from app.core.settings import get_settings


def _write_meta(root: Path, imagery_id: str, owner: str) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        json.dumps({"filename": "sample.tif", "owner_user_id": owner}),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _force_disk_fallback(monkeypatch):
    """锁死本组用例走"无 DB → 本地 metadata.json 兜底"路径。

    这些用例验证的就是磁盘 owner 校验（与现有上传/测试链路一致）；把 fetch_optional_pool
    打成 None，确保无论测试机 .env 是否 DATABASE_ENABLED=true 都不连真库、稳定走兜底。
    DB 优先路径的 owner 校验另由 tests/agent/test_imagery_repo.py（PG 集成）覆盖。
    """
    async def _no_pool():
        return None

    monkeypatch.setattr("app.agent.imagery_access.fetch_optional_pool", _no_pool)


@pytest.mark.asyncio
async def test_imagery_tools_require_owner(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    owner = "user-a"
    _write_meta(tmp_path, imagery_id, owner)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    for tool_name in ALL_IMAGERY_TOOLS:
        assert await validate_tool_access(tool_name, {"imagery_id": imagery_id}, owner) is None
        assert await validate_tool_access(tool_name, {"imagery_id": imagery_id}, "user-b") == "imagery_not_found_or_forbidden"
        assert await validate_tool_access(tool_name, {"imagery_id": imagery_id}, None) == "owner_required"


@pytest.mark.asyncio
async def test_recent_preprocess_tools_reject_non_owner(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    _write_meta(tmp_path, imagery_id, "user-a")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    for tool_name in ("cloud_shadow_mask", "extract_water_mask", "clip_reproject_raster"):
        assert (
            await validate_tool_access(tool_name, {"imagery_id": imagery_id}, "user-b")
            == "imagery_not_found_or_forbidden"
        )
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ocr_recognize_uses_imagery_owner_guard(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    _write_meta(tmp_path, imagery_id, "user-a")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    assert await validate_tool_access("ocr_recognize", {"imagery_id": imagery_id}, "user-a") is None
    assert (
        await validate_tool_access("ocr_recognize", {"imagery_id": imagery_id}, "user-b")
        == "imagery_not_found_or_forbidden"
    )
    assert await validate_tool_access("ocr_recognize", {"imagery_id": imagery_id}, None) == "owner_required"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_document_tools_validate_document_ownership(monkeypatch) -> None:
    class FakeAcquire:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            return None

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    async def fake_pool():
        return FakePool()

    async def fake_get_document(_conn, *, document_id, user_id):
        if document_id == "11111111-1111-1111-1111-111111111111" and user_id == "user-a":
            return {"id": document_id}
        return None

    monkeypatch.setattr("app.agent.tool_guards.fetch_optional_pool", fake_pool)
    monkeypatch.setattr("app.agent.tool_guards.get_document", fake_get_document)

    for tool_name in ALL_DOCUMENT_TOOLS:
        assert await validate_tool_access(tool_name, {"document_id": "11111111-1111-1111-1111-111111111111"}, None) == "owner_required"
        assert await validate_tool_access(tool_name, {"document_id": "11111111-1111-1111-1111-111111111111"}, "user-a") is None
        assert (
            await validate_tool_access(
                tool_name,
                {"document_id": "11111111-1111-1111-1111-111111111111"},
                "user-b",
            )
            == "document_not_found_or_forbidden"
        )


@pytest.mark.asyncio
async def test_document_tools_reject_when_database_is_unavailable(monkeypatch) -> None:
    async def no_pool():
        return None

    monkeypatch.setattr("app.agent.tool_guards.fetch_optional_pool", no_pool)

    assert (
        await validate_tool_access(
            "parse_document",
            {"document_id": "11111111-1111-1111-1111-111111111111"},
            "user-a",
        )
        == "document_not_found_or_forbidden"
    )


@pytest.mark.asyncio
async def test_non_imagery_tool_is_not_guarded() -> None:
    assert await validate_tool_access("web_search", {}, None) is None
