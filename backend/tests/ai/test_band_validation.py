from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio

from app.agent.tools.band_composite.runner import run_band_composite
from app.agent.tools.band_composite.schema import BandCompositeArguments
from app.agent.tools.common import validate_band_indices
from app.agent.tools.detect.runner import run_detect
from app.agent.tools.detect.schema import DetectArguments
from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVIArguments
from app.agent.tools.segment.runner import run_segment
from app.agent.tools.segment.schema import SegmentArguments
from app.agent.tools.spectral_index.runner import run_spectral_index
from app.agent.tools.spectral_index.schema import SpectralIndexArguments
from app.core.settings import get_settings


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
    if tool_name == "segment_landcover":
        return {
            "total_pixels": 4,
            "classes": [
                {"name": "building", "label": "building", "pixel_count": 2, "percentage": 50.0, "color": "#ffffff"}
            ],
            "output_png": "segmentation_overlay.png",
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


def test_validate_band_indices_accepts_valid_and_boundary(tmp_path: Path) -> None:
    source_path = tmp_path / "source.tif"
    _write_test_tif(source_path, count=4)

    assert validate_band_indices(source_path, {"red": 1, "green": 2, "blue": 3}) is None
    assert validate_band_indices(source_path, {"nir": 4}) is None


def test_validate_band_indices_rejects_zero_negative_and_overrange(tmp_path: Path) -> None:
    source_path = tmp_path / "source.tif"
    _write_test_tif(source_path, count=4)

    below_range = validate_band_indices(source_path, {"red": 0, "nir": -1})
    assert below_range is not None
    assert "从 1 开始" in below_range
    assert "red" in below_range and "nir" in below_range

    over_range = validate_band_indices(source_path, {"red": 1, "nir": 99})
    assert over_range is not None
    assert "只有 4 个波段" in over_range
    assert "nir" in over_range
    assert "red" not in over_range


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner", "args"),
    [
        (run_detect, DetectArguments(imagery_id=IMAGERY_ID, red_band=99, green_band=2, blue_band=1)),
        (run_segment, SegmentArguments(imagery_id=IMAGERY_ID, red_band=99, green_band=2, blue_band=1)),
        (run_spectral_index, SpectralIndexArguments(imagery_id=IMAGERY_ID, index_type="mndwi")),
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
async def test_detect_default_bands_are_gf2_and_explicit_override_reaches_mcp(monkeypatch, tmp_path: Path) -> None:
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
    assert explicit_result.error is None
    assert (payloads[0]["red_band"], payloads[0]["green_band"], payloads[0]["blue_band"]) == (3, 2, 1)
    assert (payloads[1]["red_band"], payloads[1]["green_band"], payloads[1]["blue_band"]) == (1, 2, 3)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_segment_default_bands_are_gf2_and_reach_mcp(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path, count=4)
    seen: dict[str, Any] = {}

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        seen["tool_name"] = tool_name
        seen["arguments"] = arguments
        return _fake_success_result(tool_name, arguments or {})

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    args = SegmentArguments(imagery_id=IMAGERY_ID)
    result = await run_segment(args)

    assert (args.red_band, args.green_band, args.blue_band) == (3, 2, 1)
    assert result.error is None
    assert seen["tool_name"] == "segment_landcover"
    assert (seen["arguments"]["red_band"], seen["arguments"]["green_band"], seen["arguments"]["blue_band"]) == (3, 2, 1)
    get_settings.cache_clear()
