from __future__ import annotations

import json
from pathlib import Path

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

    for tool_name in (
        "calculate_ndvi",
        "raster_inspect",
        "calculate_spectral_index",
        "render_band_composite",
    ):
        assert validate_tool_access(tool_name, {"imagery_id": imagery_id}, owner) is None
        assert validate_tool_access(tool_name, {"imagery_id": imagery_id}, "user-b") == "imagery_not_found_or_forbidden"
        assert validate_tool_access(tool_name, {"imagery_id": imagery_id}, None) == "owner_required"


def test_non_imagery_tool_is_not_guarded() -> None:
    assert validate_tool_access("web_search", {}, None) is None
