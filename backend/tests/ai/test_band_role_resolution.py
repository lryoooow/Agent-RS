"""A4：指数类 runner 接入影像波段角色（band_roles）。

历史 bug：STAC 合成影像按角色字母序排波段（blue=1,green=2,nir=3,red=4），
而 NDVI schema 默认 red=3/nir=4（GF-2 顺序），默认参数把红光与近红外互换，
植被 NDVI = -0.6（真值 +0.6）。修复（工作单 A4）：
1. 模型未显式给出的波段参数，用影像 band_roles 解析的波段号覆盖默认值；
2. 需要的角色缺失且模型未显式给出 -> band_roles_unknown，不得静默用 GF-2 默认值。

期望值独立手算：red=1000/nir=3000 -> NDVI = (3000-1000)/4000 = +0.5。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.agent.tools.cloud_mask.runner import run_cloud_mask
from app.agent.tools.cloud_mask.schema import CloudMaskArguments
from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVIArguments
from app.agent.tools.spectral_index.runner import run_spectral_index
from app.agent.tools.spectral_index.schema import SpectralIndexArguments
from app.agent.tools.water_mask.runner import run_water_mask
from app.agent.tools.water_mask.schema import WaterMaskArguments
from app.agent.stac_search.model import SceneRecord
from app.agent.stac_search.raster import compose_scene_tif
from app.core.settings import get_settings

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

import compute_ndvi  # noqa: E402

IMAGERY_ID = "94e758f38ede"

# GF-2 波序（B1蓝/B2绿/B3红/B4近红外）与字母序两种排列的同一物理内容。
GF2_LAYOUT = {"blue": 1, "green": 2, "red": 3, "nir": 4}
ALPHA_LAYOUT = {"blue": 1, "green": 2, "nir": 3, "red": 4}
VALUES = {"blue": 800.0, "green": 900.0, "red": 1000.0, "nir": 3000.0}


def _write_layout_tif(path: Path, layout: dict[str, int]) -> None:
    data = np.zeros((4, 2, 2), dtype=np.uint16)
    for role, band_index in layout.items():
        data[band_index - 1] = VALUES[role]
    with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=4,
                       dtype="uint16") as dst:
        dst.write(data)
        for role, band_index in layout.items():
            dst.set_band_description(band_index, role)


def _prepare_imagery(root: Path, layout: dict[str, int], imagery_id: str = IMAGERY_ID) -> Path:
    imagery_dir = root / imagery_id
    (imagery_dir / "results").mkdir(parents=True)
    _write_layout_tif(imagery_dir / "working.tif", layout)
    (imagery_dir / "metadata.json").write_text(
        '{"crs":"EPSG:4326","bounds":[100,20,101,21]}', encoding="utf-8"
    )
    return imagery_dir


_SEEN: dict[str, Any] = {}


async def _computing_call_tool(self, tool_name, *, source_path, output_dir, arguments=None):
    """假 MCP 客户端方法：记录 payload，并真实执行 compute_ndvi 得到可断言数值。"""
    _SEEN["arguments"] = arguments
    _SEEN["source_path"] = source_path
    return compute_ndvi.compute(
        input_path=str(source_path), output_dir=str(output_dir), **(arguments or {})
    )


def _install(monkeypatch, tmp_path: Path) -> None:
    _SEEN.clear()
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", _computing_call_tool)


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", [GF2_LAYOUT, ALPHA_LAYOUT], ids=["gf2_order", "alphabetical_order"])
async def test_ndvi_runner_resolves_band_roles_for_both_layouts(
    monkeypatch, tmp_path: Path, layout: dict[str, int]
) -> None:
    """正常：GF-2 顺序与字母序两种影像各跑一遍（默认参数），结果一致。

    字母序影像 band_roles 为 {blue:1,green:2,nir:3,red:4}，runner 必须发
    red_band=4/nir_band=3；GF-2 顺序影像发 red=3/nir=4。两种排列物理内容
    相同 -> 真实计算的 NDVI 均为 +0.5（手算：(3000-1000)/4000）。
    """
    _prepare_imagery(tmp_path, layout)
    _install(monkeypatch, tmp_path)

    result = await run_ndvi(NDVIArguments(imagery_id=IMAGERY_ID))

    assert result.error is None
    payload = _SEEN["arguments"]
    assert payload == {"red_band": layout["red"], "nir_band": layout["nir"]}
    assert result.geospatial_result["stats"]["mean"] == pytest.approx(0.5, abs=1e-4)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ndvi_runner_explicit_bands_cannot_override_documented_roles(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path, ALPHA_LAYOUT)
    _install(monkeypatch, tmp_path)
    result = await run_ndvi(NDVIArguments(imagery_id=IMAGERY_ID, red_band=3, nir_band=4))
    assert result.error == "invalid_bands"
    assert not _SEEN
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ndvi_runner_missing_nir_role_returns_band_roles_unknown(
    monkeypatch, tmp_path: Path
) -> None:
    """异常：缺少 nir 角色（3 波段真彩色影像）且模型未显式给出波段
    -> band_roles_unknown，不得静默使用 GF-2 默认值。"""
    imagery_dir = tmp_path / IMAGERY_ID
    (imagery_dir / "results").mkdir(parents=True)
    data = np.stack([np.full((2, 2), 1000)] * 3).astype(np.uint16)
    with rasterio.open(imagery_dir / "working.tif", "w", driver="GTiff", height=2,
                       width=2, count=3, dtype="uint16") as dst:
        dst.write(data)
        for index, role in enumerate(("red", "green", "blue"), 1):
            dst.set_band_description(index, role)

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("client should not be called when band roles are unknown")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_if_called)

    result = await run_ndvi(NDVIArguments(imagery_id=IMAGERY_ID))

    assert result.error == "band_roles_unknown"
    assert result.metadata["error_code"] == "band_roles_unknown"
    assert "nir" in result.tool_context
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_water_cloud_spectral_runners_resolve_alphabetical_layout(
    monkeypatch, tmp_path: Path
) -> None:
    """正常：water_mask / cloud_mask / spectral_index 同样接入 band_roles。"""
    payloads: list[tuple[str, dict[str, Any]]] = []

    class _CapturingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def call_tool(self, tool_name, *, source_path, output_dir, arguments=None):
            payloads.append((tool_name, dict(arguments or {})))
            if tool_name == "extract_water_mask":
                return {"water_pct": 0.0, "non_water_pct": 100.0, "nodata_pct": 0.0,
                        "threshold_method": "fixed_ndwi", "threshold_value": 0.0,
                        "ndwi_threshold": 0.0, "output_png": "water_mask_x_colored.png",
                        "output_tif": "water_mask_x.tif"}
            if tool_name == "cloud_shadow_mask":
                return {"method": "heuristic", "suspected_bright_pct": 0.0, "suspected_dark_pct": 0.0,
                        "nodata_pct": 0.0, "output_png": "cloud_mask_x_colored.png",
                        "output_tif": "cloud_mask_x.tif"}
            return {"min": -1.0, "max": 1.0, "mean": -0.5, "std": 0.0, "nodata_pct": 0.0,
                    "calibrated": False, "out_of_range_pct": 0.0,
                    "output_png": "ndwi_x_colored.png", "output_tif": "ndwi_x.tif"}

    _prepare_imagery(tmp_path, ALPHA_LAYOUT)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", _CapturingClient.call_tool)

    assert (await run_water_mask(WaterMaskArguments(imagery_id=IMAGERY_ID))).error is None
    assert (await run_cloud_mask(CloudMaskArguments(imagery_id=IMAGERY_ID, method="heuristic"))).error is None
    assert (
        await run_spectral_index(SpectralIndexArguments(imagery_id=IMAGERY_ID, index_type="ndwi"))
    ).error is None

    by_tool = {name: args for name, args in payloads}
    # 字母序：blue=1,green=2,nir=3,red=4
    assert by_tool["extract_water_mask"] == {"green_band": 2, "nir_band": 3, "threshold": 0.0}
    assert by_tool["cloud_shadow_mask"] == {
        "method": "heuristic", "red_band": 4, "green_band": 2, "blue_band": 1, "nir_band": 3,
    }
    assert by_tool["calculate_spectral_index"] == {
        "index_type": "ndwi", "blue_band": 1, "green_band": 2, "red_band": 4,
        "nir_band": 3, "swir_band": 5,
    }
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_compose_scene_tif_output_feeds_ndvi_runner_directly(
    monkeypatch, tmp_path: Path
) -> None:
    """集成（跨模块）：compose_scene_tif 的输出直接接入 NDVI runner（默认参数）。

    验收（工作单 A4）：合成影像直接交给工具、用默认参数运行，植被像元
    NDVI > 0。手算：red 填充 1000、nir 填充 4000（20m 波段双线性重采样到
    10m 网格值不变）-> NDVI = (4000-1000)/5000 = +0.6。
    """
    bands = {
        "red": (32, 10.0, 1000),
        "green": (32, 10.0, 900),
        "blue": (32, 10.0, 800),
        "nir": (16, 20.0, 4000),
        "swir": (16, 20.0, 2500),
    }
    assets: dict[str, str] = {}
    for role, (size, res, fill) in bands.items():
        path = tmp_path / f"{role}.tif"
        with rasterio.open(
            path, "w", driver="GTiff", width=size, height=size, count=1, dtype="uint16",
            crs="EPSG:32649", transform=from_origin(500000, 2500000, res, res),
        ) as dst:
            dst.write(np.full((size, size), fill, dtype="uint16"), 1)
        assets[role] = str(path)
    record = SceneRecord(
        key="e" * 12, source="earthsearch", item_id="S2B_A4", collection="c",
        # 本用例聚焦波段角色：显式标注已知逐波段定标参数。
        # 日期只用于来源描述；无可信定标标记的场景不能按日期猜测 DN/10000。
        satellite="Sentinel-2B", datetime="2021-06-01T00:00:00+00:00", cloud_cover=None,
        bbox=[113.9, 22.4, 114.3, 22.7], resolution_m=10.0, band_assets=assets,
        display_name="S2B_A4", reflectance_scale=0.0001, reflectance_offset=0.0,
        reflectance_applied_at_compose=False,
    )
    composed = tmp_path / "composed.tif"
    compose_scene_tif(record, composed)

    imagery_dir = tmp_path / IMAGERY_ID
    (imagery_dir / "results").mkdir(parents=True)
    (imagery_dir / "working.tif").write_bytes(composed.read_bytes())
    (imagery_dir / "metadata.json").write_text(
        '{"crs":"EPSG:32649","bounds":[113.9,22.4,114.3,22.7]}', encoding="utf-8"
    )

    _install(monkeypatch, tmp_path)

    result = await run_ndvi(NDVIArguments(imagery_id=IMAGERY_ID))

    assert result.error is None
    # 字母序 band_roles：red=4/nir=3（而不是 GF-2 默认 3/4）
    assert _SEEN["arguments"] == {"red_band": 4, "nir_band": 3}
    assert result.geospatial_result["stats"]["mean"] == pytest.approx(0.6, abs=1e-3)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_real_autogen_tool_chain_preserves_omitted_band_parameters(monkeypatch, tmp_path):
    import json
    from autogen_core import CancellationToken
    from app.agent.engine.tools import RemoteSensingTool
    from app.agent.engine.turn_context import turn_scope
    from app.agent.tool_registry import TOOLS
    from app.auth import set_current_user_id, reset_current_user_id

    owner = "00000000-0000-4000-8000-000000000001"
    directory = _prepare_imagery(tmp_path, ALPHA_LAYOUT)
    (directory / "metadata.json").write_text(json.dumps({
        "owner_user_id": owner, "bounds": [100, 20, 101, 21],
    }), encoding="utf-8")
    _install(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    # This local-raster contract does not use the API application's PG pool.
    # A preceding TestClient test may leave a pool bound to its closed loop.
    from unittest.mock import AsyncMock
    for module in ("app.agent.imagery_access", "app.agent.tools.staging", "app.agent.tool_jobs"):
        monkeypatch.setattr(module + ".fetch_optional_pool", AsyncMock(return_value=None))
    get_settings.cache_clear()
    token = set_current_user_id(owner)
    try:
        with turn_scope() as state:
            await RemoteSensingTool(TOOLS["calculate_ndvi"]).run_json(
                {"imagery_id": IMAGERY_ID}, CancellationToken()
            )
        assert _SEEN["arguments"] == {"red_band": 4, "nir_band": 3}
        assert state.invocations[0].result.geospatial_result["stats"]["mean"] == pytest.approx(0.5)
    finally:
        reset_current_user_id(token)
        get_settings.cache_clear()
