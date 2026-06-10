from __future__ import annotations

import json
from pathlib import Path

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


def test_imagery_tools_require_owner(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    owner = "user-a"
    _write_meta(tmp_path, imagery_id, owner)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    for tool_name in ALL_IMAGERY_TOOLS:
        assert validate_tool_access(tool_name, {"imagery_id": imagery_id}, owner) is None
        assert validate_tool_access(tool_name, {"imagery_id": imagery_id}, "user-b") == "imagery_not_found_or_forbidden"
        assert validate_tool_access(tool_name, {"imagery_id": imagery_id}, None) == "owner_required"


def test_recent_preprocess_tools_reject_non_owner(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    _write_meta(tmp_path, imagery_id, "user-a")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    for tool_name in ("cloud_shadow_mask", "extract_water_mask", "clip_reproject_raster"):
        assert (
            validate_tool_access(tool_name, {"imagery_id": imagery_id}, "user-b")
            == "imagery_not_found_or_forbidden"
        )
    get_settings.cache_clear()


def test_ocr_recognize_uses_imagery_owner_guard(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    _write_meta(tmp_path, imagery_id, "user-a")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    assert validate_tool_access("ocr_recognize", {"imagery_id": imagery_id}, "user-a") is None
    assert (
        validate_tool_access("ocr_recognize", {"imagery_id": imagery_id}, "user-b")
        == "imagery_not_found_or_forbidden"
    )
    assert validate_tool_access("ocr_recognize", {"imagery_id": imagery_id}, None) == "owner_required"
    get_settings.cache_clear()


def test_document_tools_require_owner_identity() -> None:
    for tool_name in ALL_DOCUMENT_TOOLS:
        assert validate_tool_access(tool_name, {"document_id": "11111111-1111-1111-1111-111111111111"}, None) == "owner_required"
        assert validate_tool_access(tool_name, {"document_id": "11111111-1111-1111-1111-111111111111"}, "user-a") is None


def test_non_imagery_tool_is_not_guarded() -> None:
    assert validate_tool_access("web_search", {}, None) is None
