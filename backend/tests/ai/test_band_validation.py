from __future__ import annotations
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio

from app.agent.tools.band_composite.runner import run_band_composite
from app.agent.tools.band_composite.schema import BandCompositeArguments
from app.agent.tools.common import classify_rs_tool_failure, validate_band_indices
from app.agent.tools.detect.runner import run_detect
from app.agent.tools.detect.schema import DetectArguments
from app.agent.tools.instance_segment.runner import run_instance_segment
from app.agent.tools.instance_segment.schema import InstanceSegmentArguments
from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVIArguments
from app.agent.tools.spectral_index.runner import run_spectral_index
from app.agent.tools.spectral_index.schema import SpectralIndexArguments
from app.core.settings import get_settings
from app.mcp.client import MCPCallError


IMAGERY_ID = "94e758f38ede"


def _write_test_tif(path: Path, *, count: int = 4) -> None:
    data = np.ones((count, 2, 2), dtype=np.uint16)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=count,
        dtype="uint16",
    ) as dst:
        dst.write(data)
        # This fixture represents an explicitly documented BGR+NIR sensor.
        if count >= 4:
            for index, label in enumerate(("Blue", "Green", "Red", "NIR"), 1):
                dst.set_band_description(index, label)


def _prepare_imagery(root: Path, *, count: int = 4, imagery_id: str = IMAGERY_ID) -> Path:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "working.tif", count=count)
    (imagery_dir / "metadata.json").write_text(
        '{"crs":"EPSG:4326","bounds":[100,20,101,21]}',
        encoding="utf-8",
    )
    return imagery_dir


def _fake_success_result(tool_name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    if tool_name == "calculate_spectral_index":
        return {
            "min": 0.1,
            "max": 0.9,
            "mean": 0.4,
            "std": 0.2,
            "nodata_pct": 0.0,
            "output_png": f"{arguments['index_type']}_colored.png",
        }
    if tool_name == "render_band_composite":
        mode = arguments["mode"]
        return {
            "bands_used": arguments.get("bands") or ([3, 2, 1] if mode == "true_color" else [4, 3, 2]),
            "output_png": f"composite_{mode}.png",
        }
    if tool_name == "detect_objects":
        return {
            "detection_count": 1,
            "score_threshold": arguments["score_threshold"],
            "classes": [{"name": "plane", "label": "plane", "count": 1, "color": "#ff0000"}],
            "output_png": "detection_overlay.png",
        }
    if tool_name == "calculate_ndvi":
        return {
            "min": 0.1,
            "max": 0.8,
            "mean": 0.4,
            "std": 0.2,
            "nodata_pct": 0.0,
            "output_png": "ndvi_colored.png",
        }
    raise AssertionError(f"unexpected tool: {tool_name}")


@pytest.mark.asyncio
async def test_validate_band_indices_accepts_valid_and_boundary(tmp_path: Path) -> None:
    source_path = tmp_path / "source.tif"
    _write_test_tif(source_path, count=4)

    assert await validate_band_indices(source_path, {"red": 3, "green": 2, "blue": 1}) is None
    assert await validate_band_indices(source_path, {"nir": 4}) is None


@pytest.mark.asyncio
async def test_validate_band_indices_rejects_zero_negative_and_overrange(tmp_path: Path) -> None:
    source_path = tmp_path / "source.tif"
    _write_test_tif(source_path, count=4)

    below_range = await validate_band_indices(source_path, {"red": 0, "nir": -1})
    assert below_range is not None
    assert "从 1 开始" in below_range
    assert "red" in below_range and "nir" in below_range

    over_range = await validate_band_indices(source_path, {"red": 1, "nir": 99})
    assert over_range is not None
    assert "只有 4 个波段" in over_range
    assert "nir" in over_range
    assert "red" not in over_range


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner", "args"),
    [
        (run_detect, DetectArguments(imagery_id=IMAGERY_ID, red_band=99, green_band=2, blue_band=1)),
        (run_instance_segment, InstanceSegmentArguments(imagery_id=IMAGERY_ID, concepts=["building"], red_band=99, green_band=2, blue_band=1)),
        # swir_band=5 显式给出（A4 后未显式的参数走 band_roles 解析；该夹具没有
        # swir 角色，显式给出才能保持本用例测的是"越界波段号拒绝"）
        (run_spectral_index, SpectralIndexArguments(imagery_id=IMAGERY_ID, index_type="mndwi", swir1_band=5)),
        (run_band_composite, BandCompositeArguments(imagery_id=IMAGERY_ID, mode="custom", bands=[1, 2, 99])),
        (run_band_composite, BandCompositeArguments(imagery_id=IMAGERY_ID, mode="true_color")),
        (run_band_composite, BandCompositeArguments(imagery_id=IMAGERY_ID, mode="false_color")),
        (run_ndvi, NDVIArguments(imagery_id=IMAGERY_ID, red_band=3, nir_band=5)),
    ],
)
async def test_runner_rejects_invalid_bands_before_mcp_call(monkeypatch, tmp_path: Path, runner, args) -> None:
    count = 2 if isinstance(args, BandCompositeArguments) and args.mode == "true_color" else 4
    if isinstance(args, BandCompositeArguments) and args.mode == "false_color":
        count = 3
    _prepare_imagery(tmp_path, count=count)
    calls: list[str] = []

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        calls.append(tool_name)
        return _fake_success_result(tool_name, arguments or {})

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    result = await runner(args)

    assert result.error == "invalid_bands"
    assert result.metadata["error_code"] == "invalid_bands"
    assert calls == []
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_spectral_ndwi_ignores_unused_default_swir_band(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path, count=4)
    seen: dict[str, Any] = {}

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        seen["tool_name"] = tool_name
        seen["arguments"] = arguments
        return _fake_success_result(tool_name, arguments or {})

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    result = await run_spectral_index(SpectralIndexArguments(imagery_id=IMAGERY_ID, index_type="ndwi"))

    assert result.error is None
    assert seen["tool_name"] == "calculate_spectral_index"
    assert seen["arguments"]["swir_band"] == 5
    assert result.geospatial_result["index_type"] == "ndwi"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_band_composite_false_color_passes_on_four_band_imagery(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path, count=4)
    seen: dict[str, Any] = {}

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        seen["tool_name"] = tool_name
        seen["arguments"] = arguments
        return _fake_success_result(tool_name, arguments or {})

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    result = await run_band_composite(BandCompositeArguments(imagery_id=IMAGERY_ID, mode="false_color"))

    assert result.error is None
    assert seen["tool_name"] == "render_band_composite"
    assert seen["arguments"]["mode"] == "false_color"
    assert result.geospatial_result["bands_used"] == [4, 3, 2]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_detect_rejects_explicit_mapping_conflicting_with_documented_roles(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path, count=4)
    payloads: list[dict[str, Any]] = []

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        payloads.append(arguments)
        return _fake_success_result(tool_name, arguments or {})

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    default_args = DetectArguments(imagery_id=IMAGERY_ID)
    explicit_args = DetectArguments(imagery_id=IMAGERY_ID, red_band=1, green_band=2, blue_band=3)

    assert (default_args.red_band, default_args.green_band, default_args.blue_band) == (3, 2, 1)

    default_result = await run_detect(default_args)
    explicit_result = await run_detect(explicit_args)

    assert default_result.error is None
    assert explicit_result.error == "invalid_bands"
    assert (payloads[0]["red_band"], payloads[0]["green_band"], payloads[0]["blue_band"]) == (3, 2, 1)
    assert len(payloads) == 1
    get_settings.cache_clear()


# ---------- 定标兜底错误码映射（D3 收尾：stale_s2_composite） ----------
# compute 侧（docker/rs_tools/raster_utils.py）对"无 REFL_* 标签 + 成像
# >= 2022-01-25 的 S2 旧缓存"抛 "stale_s2_composite:" 前缀文本，经 MCP
# isError 原样带回；这里锁定 runner 侧把它映射成稳定错误码与用户可读文案
# （说明为修复前合成、需重新导入/重新合成），而不是通用 mcp_error。


def test_classify_rs_tool_failure_maps_stale_s2_composite() -> None:
    exc = MCPCallError(
        "calculate_ndvi execution failed: stale_s2_composite: Sentinel-2 影像"
        "（成像日期 2024-06-01）缺少 REFL_SCALE/REFL_OFFSET 定标标签……"
    )
    code, message = classify_rs_tool_failure(exc)
    assert code == "stale_s2_composite"
    # 用户可读文案必须给出处置方向（重新导入/重新合成），不暴露内部标签名
    assert "重新导入" in message and ("反射率单位" in message and "逐波段定标参数" in message)


def test_classify_rs_tool_failure_keeps_existing_codes() -> None:
    """回归：原有两个前缀的映射不受新增分支影响。"""
    assert classify_rs_tool_failure(MCPCallError("x failed: uncalibrated_input: …"))[0] == "uncalibrated_input"
    assert classify_rs_tool_failure(MCPCallError("x failed: all_pixels_invalid: …"))[0] == "all_pixels_invalid"
    assert classify_rs_tool_failure(MCPCallError("boom"))[0] == "mcp_error"


@pytest.mark.asyncio
async def test_ndvi_runner_surfaces_stale_s2_composite_error(monkeypatch, tmp_path: Path) -> None:
    """端到端：MCP 带回 stale_s2_composite 文本 → ToolRunResult 的 error 与
    metadata.error_code 都是 stale_s2_composite，tool_context 是用户可读文案。"""
    _prepare_imagery(tmp_path)

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        raise MCPCallError(
            "calculate_ndvi execution failed: stale_s2_composite: Sentinel-2 影像"
            "（成像日期 2024-06-01）缺少 REFL_SCALE/REFL_OFFSET 定标标签……"
        )

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    result = await run_ndvi(NDVIArguments(imagery_id=IMAGERY_ID))

    assert result.error == "stale_s2_composite"
    assert result.metadata["error_code"] == "stale_s2_composite"
    assert "重新导入" in result.tool_context
    get_settings.cache_clear()
