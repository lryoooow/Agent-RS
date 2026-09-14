"""stac_search 数据层：统一模型、双源适配、SAS 签名、场景缓存、COG 合成。

全部不打真实网络：搜索与签名用假对象/假响应，合成用本地合成 COG
（刻意做成 10m/20m 混合分辨率，复现 S2 网格不齐的真实形态）。
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.agent.stac_search.cache import clear_all, get_scene, put_scenes, stats
from app.agent.stac_search.model import SceneRecord, scene_key
from app.agent.stac_search.raster import (
    SceneRasterError,
    compose_scene_tif,
    render_scene_preview,
)
from app.agent.stac_search import sources as stac_sources
from app.agent.stac_search.sources import (
    SourceSpec,
    _sign_target_from_href,
    record_from_item,
    signed_href,
)


def _asset(href: str, extra: dict | None = None):
    return SimpleNamespace(href=href, extra_fields=extra or {})


def _item(item_id: str, assets: dict, *, bbox=(113.9, 22.4, 114.3, 22.7), **properties):
    return SimpleNamespace(
        id=item_id,
        properties={"platform": "sentinel-2b", "eo:cloud_cover": 5.5, **properties},
        bbox=list(bbox),
        assets=assets,
        datetime="2026-08-11T03:11:32+00:00",
    )


def _s2_spec() -> SourceSpec:
    return stac_sources._SOURCES["sentinel2"]


def _landsat_spec() -> SourceSpec:
    return stac_sources._SOURCES["landsat"]


# --------------------------------------------------------------- 模型


def test_scene_key_is_stable_and_imagery_shaped() -> None:
    key = scene_key("earthsearch", "S2B_T50SMJ_20260831")
    assert key == scene_key("earthsearch", "S2B_T50SMJ_20260831")
    assert key != scene_key("planetary_computer", "S2B_T50SMJ_20260831")
    assert len(key) == 12 and all(c in "0123456789abcdef" for c in key)


def test_band_roles_follow_sorted_band_order() -> None:
    record = SceneRecord(
        key="a" * 12, source="earthsearch", item_id="x", collection="c",
        satellite="S2", datetime="2026-01-01", cloud_cover=None,
        bbox=[0, 0, 1, 1], resolution_m=10.0,
        band_assets={"red": "u", "blue": "u", "nir": "u", "green": "u", "swir": "u"},
        display_name="x",
    )
    assert record.band_roles == {"blue": 1, "green": 2, "nir": 3, "red": 4, "swir": 5}


# --------------------------------------------------------------- record_from_item


def test_record_from_item_maps_roles_and_label() -> None:
    item = _item(
        "S2B_X",
        {
            "blue": _asset("https://bucket/B02.tif"),
            "green": _asset("https://bucket/B03.tif"),
            "red": _asset("https://bucket/B04.tif"),
            "nir08": _asset("https://bucket/B8A.tif"),  # 无 10m nir，回落 nir08
            "swir22": _asset("https://bucket/B12.tif"),
        },
    )
    record = record_from_item(_s2_spec(), item)
    assert record is not None
    assert record.satellite == "Sentinel-2B"
    assert record.band_assets["nir"] == "https://bucket/B8A.tif"
    assert record.band_assets["swir"] == "https://bucket/B12.tif"
    assert record.cloud_cover == 5.5
    assert record.reflectance_scale is None  # S2 保持 DN


def test_record_from_item_requires_rgb() -> None:
    item = _item("X", {"red": _asset("u")})  # 缺 green/blue
    assert record_from_item(_s2_spec(), item) is None


def test_record_from_item_captures_pc_sign_targets() -> None:
    item = _item(
        "LC09_X",
        {
            "blue": _asset("https://landsateuwest.blob.core.windows.net/landsat-c2/a/B2.TIF"),
            "green": _asset("https://landsateuwest.blob.core.windows.net/landsat-c2/a/B3.TIF"),
            "red": _asset("https://landsateuwest.blob.core.windows.net/landsat-c2/a/B4.TIF"),
            "nir08": _asset("https://landsateuwest.blob.core.windows.net/landsat-c2/a/B5.TIF"),
            "swir22": _asset("https://landsateuwest.blob.core.windows.net/landsat-c2/a/B7.TIF"),
        },
        platform="landsat-9",
    )
    record = record_from_item(_landsat_spec(), item)
    assert record is not None
    assert record.satellite == "Landsat 9"
    # 从 blob URL 推断（账号=主机首段，容器=路径首段）
    assert record.asset_sign_info["red"] == ("landsateuwest", "landsat-c2")
    assert record.reflectance_scale == pytest.approx(2.75e-05)
    assert record.reflectance_offset == pytest.approx(-0.2)


# --------------------------------------------------------------- SAS 签名


def test_sign_target_from_href_parses_account_and_container() -> None:
    assert _sign_target_from_href(
        "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/x.TIF"
    ) == ("landsateuwest", "landsat-c2")
    assert _sign_target_from_href("https://example.com/a.tif") is None


def test_signed_href_appends_token_and_caches(monkeypatch) -> None:
    calls: list[str] = []

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"token": "sv=2020&se=2030", "msft:expiry": "2099-01-01T00:00:00Z"}

    def fake_get(url, **_kwargs):
        calls.append(url)
        return FakeResp()

    monkeypatch.setattr(stac_sources.httpx, "get", fake_get)

    href = "https://acct.blob.core.windows.net/cont/a.tif"
    signed = signed_href(href, ("acct", "cont"))
    assert signed == f"{href}?sv=2020&se=2030"
    # 第二次签名命中令牌缓存，不再发请求。
    assert signed_href(href + "?x=1", ("acct", "cont")) == f"{href}?x=1&sv=2020&se=2030"
    assert len(calls) == 1


def test_signed_href_passthrough_for_non_azure() -> None:
    assert signed_href("https://e84-earth-search.s3.amazonaws.com/a/B04.tif") == (
        "https://e84-earth-search.s3.amazonaws.com/a/B04.tif"
    )


# --------------------------------------------------------------- 场景缓存


def _record(key: str) -> SceneRecord:
    return SceneRecord(
        key=key, source="earthsearch", item_id=key, collection="c",
        satellite="S2", datetime="2026-01-01", cloud_cover=None,
        bbox=[0, 0, 1, 1], resolution_m=10.0, band_assets={"red": "u"}, display_name=key,
    )


def test_cache_isolates_users_and_expires() -> None:
    clear_all()
    put_scenes("user-a", [_record("a" * 12)])
    assert get_scene("user-a", "a" * 12) is not None
    assert get_scene("user-b", "a" * 12) is None, "越权 user 查不到别人的场景"
    assert get_scene("user-a", "unknown") is None

    # TTL 过期后查不到（直接改缓存里的过期时间模拟）。
    stac_cache = stac_sources  # noqa: F841 仅为可读性
    from app.agent.stac_search import cache as cache_module

    bucket = cache_module._CACHE["user-a"]
    record, _ = bucket["a" * 12]
    bucket["a" * 12] = (record, time.monotonic() - 1)
    assert get_scene("user-a", "a" * 12) is None


def test_cache_evicts_oldest_beyond_cap() -> None:
    clear_all()
    cap = cache_cap = 200
    put_scenes("user-c", [_record(f"{i:012x}") for i in range(cap + 5)])
    assert stats().scenes <= cap


# --------------------------------------------------------------- COG 合成（本地伪 COG）


def _write_band(path: Path, size: int, resolution: float, fill: float) -> None:
    import rasterio
    from rasterio.transform import from_origin

    data = np.full((size, size), fill, dtype="uint16")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="uint16",
        crs="EPSG:32649",
        transform=from_origin(500000, 2500000, resolution, resolution),
    ) as dst:
        dst.write(data, 1)


@pytest.fixture
def mixed_grid_scene(tmp_path: Path) -> SceneRecord:
    """10m 三波段 + 20m 两波段的混合分辨率场景（S2 的真实形态）。

    20m 波段的栅格尺寸是一半——这正是 compose 必须按地理范围对齐各波段
    窗口的原因（按基准波段像素窗口直接套会越界）。
    """
    bands = {
        "red": (400, 10.0, 1000),     # (size, resolution, fill)
        "green": (400, 10.0, 900),
        "blue": (400, 10.0, 800),
        "nir": (200, 20.0, 4000),
        "swir": (200, 20.0, 2500),
    }
    assets: dict[str, str] = {}
    for role, (size, res, fill) in bands.items():
        path = tmp_path / f"{role}.tif"
        _write_band(path, size, res, fill)
        assets[role] = str(path)
    return SceneRecord(
        key="b" * 12, source="earthsearch", item_id="S2B_TEST", collection="c",
        satellite="Sentinel-2B", datetime="2026-08-11T03:11:32+00:00",
        cloud_cover=5.0, bbox=[113.9, 22.4, 114.3, 22.7], resolution_m=10.0,
        band_assets=assets, display_name="S2B_TEST",
    )


def test_compose_aligns_mixed_resolution_bands(mixed_grid_scene: SceneRecord, tmp_path: Path) -> None:
    import rasterio

    out = tmp_path / "composed.tif"
    meta = compose_scene_tif(mixed_grid_scene, out)
    with rasterio.open(out) as src:
        assert src.count == 5
        assert src.descriptions == ("blue", "green", "nir", "red", "swir")
        assert src.tags()["SENSOR"] == "Sentinel-2B"
        # 20m 波段与 10m 波段读进同一个输出网格：值域正确（各自填充值）。
        blue_index = src.descriptions.index("blue") + 1
        nir_index = src.descriptions.index("nir") + 1
        assert src.read(blue_index).mean() == pytest.approx(800, abs=1)
        assert src.read(nir_index).mean() == pytest.approx(4000, abs=2)
    assert meta["band_roles"] == {"blue": 1, "green": 2, "nir": 3, "red": 4, "swir": 5}
    assert meta["band_roles_source"] == "stac_assets"


def test_compose_converts_landsat_to_reflectance(tmp_path: Path) -> None:
    import rasterio

    scene = SceneRecord(
        key="c" * 12, source="planetary_computer", item_id="LC09_TEST", collection="c",
        satellite="Landsat 9", datetime="2026-08-30T02:46:14+00:00",
        cloud_cover=None, bbox=[113.9, 22.4, 114.3, 22.7], resolution_m=30.0,
        band_assets={"red": str(tmp_path / "r.tif")},
        display_name="LC09_TEST",
        reflectance_scale=2.75e-05,
        reflectance_offset=-0.2,
    )
    _write_band(tmp_path / "r.tif", 64, 30.0, 10000)
    out = tmp_path / "lc.tif"
    compose_scene_tif(scene, out)
    with rasterio.open(out) as src:
        data = src.read(1)
        assert data.dtype == np.float32
        # DN 10000 → 10000*2.75e-05 - 0.2 = 0.075（真反射率）
        assert data.mean() == pytest.approx(0.075, abs=1e-4)


def test_preview_renders_png_and_reuses_cache(mixed_grid_scene: SceneRecord, tmp_path: Path) -> None:
    out = tmp_path / "preview.png"
    render_scene_preview(mixed_grid_scene, out)
    assert out.stat().st_size > 0
    first_mtime = out.stat().st_mtime_ns
    render_scene_preview(mixed_grid_scene, out)  # 已存在直接复用
    assert out.stat().st_mtime_ns == first_mtime


def test_compose_missing_band_raises_clean_error(tmp_path: Path) -> None:
    scene = SceneRecord(
        key="d" * 12, source="earthsearch", item_id="X", collection="c",
        satellite="S2", datetime="2026-01-01", cloud_cover=None,
        bbox=[0, 0, 1, 1], resolution_m=10.0,
        band_assets={"green": str(tmp_path / "g.tif")}, display_name="X",
    )
    _write_band(tmp_path / "g.tif", 32, 10.0, 1)
    with pytest.raises(SceneRasterError, match="red"):
        compose_scene_tif(scene, tmp_path / "x.tif")
