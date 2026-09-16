"""Phase 2：波段语义提取与结构化影像清单的测试。

三层各自独立验证：
1. `_match_band_role` / `_derive_band_roles` 纯函数——角色识别与位置兜底；
2. `_extract_metadata`——真实 GeoTIFF（带波段描述/标签）的字段提取；
3. `build_imagery_inventory`——结构化清单的排序、上限与格式。
"""

from __future__ import annotations

import pytest

from app.agent.request_builder import build_imagery_inventory
from app.services.imagery_persist import (
    _derive_band_roles,
    _extract_metadata,
    _match_band_role,
)
from app.core.settings import get_settings


# ───────────────────────── 角色识别（纯函数） ─────────────────────────


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Blue", "blue"),
        ("Green", "green"),
        ("Red", "red"),
        ("NIR", "nir"),
        ("Near Infrared", "nir"),  # 不能被 'red' 子串误伤
        ("near-infrared", "nir"),
        ("近红外", "nir"),
        ("SWIR 1", "swir"),
        ("Shortwave Infrared", "swir"),
        ("短波红外", "swir"),
        ("Red Edge", "rededge"),  # 无参数对应，识别出来只为排除
        ("B4", None),
        ("Band 4", None),
        ("", None),
        ("全色", None),
    ],
)
def test_match_band_role(description, expected):
    assert _match_band_role(description) == expected


def test_derive_band_roles_prefers_descriptions():
    roles, source = _derive_band_roles(
        4, ["Coastal Aerosol", "Blue", "Green", "Near Infrared"]
    )
    assert source == "descriptions"
    assert roles == {"blue": 2, "green": 3, "nir": 4}


def test_derive_band_roles_landsat_style_red_edge_excluded():
    roles, source = _derive_band_roles(
        8,
        ["Coastal", "Blue", "Green", "Red", "Red Edge", "NIR", "SWIR1", "SWIR2"],
    )
    assert source == "descriptions"
    # 同一角色多波段（SWIR1/SWIR2）取第一个；Red Edge 不占用 red。
    assert roles == {"blue": 2, "green": 3, "red": 4, "nir": 6, "swir": 7}


@pytest.mark.parametrize(
    ("count", "expected_source"),
    [
        (4, None),
        (5, None),
        (3, "positional_rgb"),
        (1, "positional_gray"),
    ],
)
def test_derive_band_roles_positional_fallbacks(count, expected_source):
    roles, source = _derive_band_roles(count, [None] * count)
    assert source == expected_source
    if expected_source == "positional_gf2":
        assert roles["red"] == 3 and roles["nir"] == 4
        assert ("swir" in roles) == (count >= 5)
    elif expected_source == "positional_rgb":
        assert roles == {"red": 1, "green": 2, "blue": 3}


def test_derive_band_roles_two_bands_unknown():
    assert _derive_band_roles(2, [None, None]) == (None, None)


# ───────────────────────── 元数据提取（合成 GeoTIFF） ─────────────────────────


def _write_tif(path, *, band_descriptions=None, tags=None):
    import numpy as np
    import rasterio

    count = len(band_descriptions) if band_descriptions else 4
    data = np.zeros((count, 8, 8), dtype="uint16")
    profile = {
        "driver": "GTiff",
        "width": 8,
        "height": 8,
        "count": count,
        "dtype": "uint16",
        "crs": "EPSG:32650",
        "transform": rasterio.Affine(4.0, 0.0, 0.0, 0.0, -4.0, 0.0),
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)
        for index, description in enumerate(band_descriptions or [], start=1):
            if description:
                dst.set_band_description(index, description)
        if tags:
            dst.update_tags(**tags)


def test_extract_metadata_reads_band_semantics(tmp_path):
    tif = tmp_path / "ms.tif"
    _write_tif(
        tif,
        band_descriptions=["Blue", "Green", "Red", "NIR"],
        tags={"SENSOR_ID": "GF-2", "TIFFTAG_DATETIME": "2024:05:01 10:30:00"},
    )
    meta = _extract_metadata(tif)
    assert meta["band_descriptions"] == ["Blue", "Green", "Red", "NIR"]
    assert meta["band_roles"] == {"blue": 1, "green": 2, "red": 3, "nir": 4}
    assert meta["band_roles_source"] == "descriptions"
    assert meta["sensor"] == "GF-2"
    assert meta["acquired_at"] == "2024:05:01 10:30:00"


def test_extract_metadata_falls_back_to_positional(tmp_path):
    tif = tmp_path / "plain.tif"
    _write_tif(tif)  # 无描述、无标签的 4 波段
    meta = _extract_metadata(tif)
    assert meta["band_descriptions"] is None
    assert meta["band_roles"] is None
    assert meta["band_roles_source"] is None
    assert meta["sensor"] is None
    assert meta["acquired_at"] is None


# ───────────────────────── 结构化清单 ─────────────────────────


def _imagery(imagery_id, created_at, **extra):
    meta = {
        "band_count": 4,
        "width": 1024,
        "height": 1024,
        "crs": "EPSG:4326",
        "pixel_size": [4.0, 4.0],
        "band_roles": {"blue": 1, "green": 2, "red": 3, "nir": 4},
        "band_roles_source": "descriptions",
        "created_at": created_at,
    }
    meta.update(extra)
    return (imagery_id, meta)


@pytest.mark.asyncio
async def test_inventory_formats_band_roles_and_orders_newest_first(monkeypatch):
    async def fake_iter(_user_id):
        return [
            _imagery("a" * 12, "2026-01-01T00:00:00Z", sensor="GF-2"),
            _imagery("b" * 12, "2026-09-01T00:00:00Z"),
            _imagery("c" * 12, "2026-05-01T00:00:00Z"),
        ]

    monkeypatch.setattr(
        "app.agent.request_builder.iter_user_imagery_metadata", fake_iter
    )
    inventory = await build_imagery_inventory("user-a")
    assert inventory is not None
    lines = inventory.splitlines()
    assert lines[1].startswith("- ID: " + "b" * 12)  # 最新优先
    assert lines[2].startswith("- ID: " + "c" * 12)  # 次新
    assert lines[3].startswith("- ID: " + "a" * 12)  # 最旧垫底
    assert "B1蓝,B2绿,B3红,B4近红外" in inventory
    assert "来自波段描述" in inventory
    assert "传感器: GF-2" in inventory
    assert "波段号以各影像的波段角色表为准" in inventory


@pytest.mark.asyncio
async def test_inventory_respects_limit_and_notes_hidden(monkeypatch):
    async def fake_iter(_user_id):
        return [_imagery(f"{i:012x}", f"2026-01-{day:02d}T00:00:00Z") for i, day in enumerate(range(1, 6), start=1)]

    monkeypatch.setattr(
        "app.agent.request_builder.iter_user_imagery_metadata", fake_iter
    )
    monkeypatch.setenv("AGENT_IMAGERY_INVENTORY_LIMIT", "2")
    get_settings.cache_clear()
    try:
        inventory = await build_imagery_inventory("user-a")
    finally:
        get_settings.cache_clear()
    assert inventory is not None
    assert inventory.count("- ID: ") == 2
    assert "另有 3 张未列出" in inventory


@pytest.mark.asyncio
async def test_inventory_handles_legacy_metadata_without_roles(monkeypatch):
    """老影像（Phase 2 之前上传）没有 band_roles 字段，清单必须照样出。"""

    async def fake_iter(_user_id):
        return [("d" * 12, {"band_count": 3, "width": 512, "height": 512, "crs": None, "created_at": "2025-01-01T00:00:00Z"})]

    monkeypatch.setattr(
        "app.agent.request_builder.iter_user_imagery_metadata", fake_iter
    )
    inventory = await build_imagery_inventory("user-a")
    assert inventory is not None
    assert "3波段(角色未知)" in inventory
    assert "CRS: 未知" in inventory
