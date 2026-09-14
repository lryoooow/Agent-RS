"""scenes API：检索/预览/下载/导入的路由契约与安全边界。

不打真实网络：search_scenes 与地理编码全部 monkeypatch，场景用本地合成 COG
（10m/20m 混合分辨率）。重点断言：user 隔离、过期 key、限流、导入产物形状。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.agent.stac_search.cache import clear_all
from app.agent.stac_search.model import SceneRecord
from app.api.deps import require_authenticated_user
from app.core.settings import get_settings

DEFAULT_USER = None  # auth 关闭时依赖返回 settings.default_user_id


class _FakeGeo(BaseModel):
    pass


def _write_band(path: Path, size: int, resolution: float, fill: float) -> None:
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(
        path, "w", driver="GTiff", width=size, height=size, count=1, dtype="uint16",
        crs="EPSG:32649", transform=from_origin(500000, 2500000, resolution, resolution),
    ) as dst:
        dst.write(np.full((size, size), fill, dtype="uint16"), 1)


def _fake_record(tmp_path: Path, key: str = "ab12cd34ef56") -> SceneRecord:
    bands = {
        "red": (160, 10.0, 1000),
        "green": (160, 10.0, 900),
        "blue": (160, 10.0, 800),
        "nir": (80, 20.0, 4000),
        "swir": (80, 20.0, 2500),
    }
    assets: dict[str, str] = {}
    for role, (size, res, fill) in bands.items():
        path = tmp_path / f"{key}_{role}.tif"
        _write_band(path, size, res, fill)
        assets[role] = str(path)
    return SceneRecord(
        key=key, source="earthsearch", item_id="S2B_TEST_SCENE", collection="c",
        satellite="Sentinel-2B", datetime="2026-08-11T03:11:32+00:00", cloud_cover=5.0,
        bbox=[113.9, 22.4, 114.3, 22.7], resolution_m=10.0,
        band_assets=assets, display_name="S2B_TEST_SCENE",
    )


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SCENE_CACHE_DIR", str(tmp_path / "scenes"))
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    get_settings.cache_clear()
    clear_all()
    yield
    get_settings.cache_clear()
    clear_all()


@pytest.fixture
def record(tmp_path: Path) -> SceneRecord:
    return _fake_record(tmp_path)


def _patch_search(monkeypatch, records, notes=None):
    async def fake_search(**kwargs):
        return list(records), list(notes or [])

    monkeypatch.setattr("app.api.routes.scenes.search_scenes", fake_search)


def test_search_returns_cards_and_caches(monkeypatch, record):
    from app.main import app

    _patch_search(monkeypatch, [record])
    with TestClient(app) as client:
        response = client.post(
            "/api/scenes/search",
            json={"bbox": [113.9, 22.4, 114.3, 22.7], "cloud_max": 20},
        )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["scenes"]) == 1
    card = payload["scenes"][0]
    assert card["key"] == record.key
    assert card["preview_url"] == f"/api/scenes/{record.key}/preview"
    assert card["download_url"] == f"/api/scenes/{record.key}/download"
    assert card["satellite"] == "Sentinel-2B"


def test_search_requires_area(monkeypatch):
    from app.main import app

    with TestClient(app) as client:
        response = client.post("/api/scenes/search", json={"source": "auto"})
    assert response.status_code == 400


def test_search_place_resolves_to_bbox(monkeypatch, record):
    from app.main import app

    captured: dict = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return [record], []

    async def fake_geocode(query):
        return {"display_name": "深圳市", "center": [114.06, 22.55], "zoom": 11}

    monkeypatch.setattr("app.api.routes.scenes.search_scenes", fake_search)
    monkeypatch.setattr("app.api.routes.scenes.forward_geocode", fake_geocode)
    with TestClient(app) as client:
        response = client.post("/api/scenes/search", json={"place": "深圳"})
    assert response.status_code == 200
    # 地名 → 中心 ±0.15° 的检索范围
    assert captured["bbox"] == pytest.approx([113.91, 22.4, 114.21, 22.7])


def test_place_unresolvable_is_400(monkeypatch):
    from app.main import app

    async def fake_geocode(_query):
        return None

    monkeypatch.setattr("app.api.routes.scenes.forward_geocode", fake_geocode)
    with TestClient(app) as client:
        response = client.post("/api/scenes/search", json={"place": "不存在的地名xyz"})
    assert response.status_code == 400


def test_preview_download_and_import_roundtrip(monkeypatch, record, tmp_path):
    from app.main import app

    _patch_search(monkeypatch, [record])
    with TestClient(app) as client:
        assert client.post("/api/scenes/search", json={"bbox": [0, 0, 1, 1]}).status_code == 200

        preview = client.get(f"/api/scenes/{record.key}/preview")
        assert preview.status_code == 200
        assert preview.headers["content-type"].startswith("image/png")
        assert preview.content[:8] == b"\x89PNG\r\n\x1a\n"

        download = client.get(f"/api/scenes/{record.key}/download")
        assert download.status_code == 200
        assert "attachment" in download.headers.get("content-disposition", "")
        assert b"S2B_TEST_SCENE.tif" in download.headers["content-disposition"].encode()

        imported = client.post(f"/api/scenes/{record.key}/import")
        assert imported.status_code == 200, imported.text
        payload = imported.json()
        imagery_id = payload["imagery_id"]
        assert payload["band_roles"] == {"blue": 1, "green": 2, "nir": 3, "red": 4, "swir": 5}

    # 导入产物走上传目录约定，本地 metadata.json 兜底能让清单看到它。
    import json as jsonlib

    dest = get_settings().imagery_upload_dir
    meta_path = Path(dest) / imagery_id / "metadata.json"
    assert meta_path.exists()
    meta = jsonlib.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["band_roles_source"] == "stac_assets"
    assert meta["sensor"] == "Sentinel-2B"
    assert meta["band_count"] == 5


def test_cross_user_and_expired_keys_are_404(monkeypatch, record):
    from app.main import app

    _patch_search(monkeypatch, [record])
    with TestClient(app) as client:
        client.post("/api/scenes/search", json={"bbox": [0, 0, 1, 1]})

        # 换一个用户身份：场景缓存查不到 → 404。
        app.dependency_overrides[require_authenticated_user] = lambda: (
            "00000000-0000-4000-8000-00000000000b"
        )
        try:
            assert client.get(f"/api/scenes/{record.key}/preview").status_code == 404
        finally:
            app.dependency_overrides.clear()

        # 回到原用户，但 key 不存在 / 形状非法 → 404。
        assert client.get("/api/scenes/ffffffffffff/preview").status_code == 404
        assert client.get("/api/scenes/zzz/preview").status_code == 404


def test_download_rate_limit(monkeypatch, record):
    from app.api.routes import scenes as scenes_module
    from app.main import app

    scenes_module._HEAVY_WINDOWS.clear()
    _patch_search(monkeypatch, [record])
    with TestClient(app) as client:
        client.post("/api/scenes/search", json={"bbox": [0, 0, 1, 1]})
        statuses = [
            client.get(f"/api/scenes/{record.key}/download").status_code
            for _ in range(scenes_module._HEAVY_OPS_PER_HOUR + 2)
        ]
    assert statuses[0] == 200
    assert statuses[-1] == 429
