from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from app.agent.tools.clip_reproject.runner import run_clip_reproject
from app.agent.tools.clip_reproject.schema import ClipReprojectArguments
from app.core.settings import get_settings


def _write_test_tif(path: Path, *, count: int = 4) -> None:
    data = np.ones((count, 2, 2), dtype=np.uint16)
    with rasterio.open(
        path, "w", driver="GTiff", height=2, width=2, count=count, dtype="uint16"
    ) as dst:
        dst.write(data)


# ---------- schema 校验（本步新难点：CRS/bbox） ----------

def test_clip_reproject_schema_accepts_dst_crs_only() -> None:
    args = ClipReprojectArguments(imagery_id="94e758f38ede", dst_crs="EPSG:4326")
    assert args.dst_crs == "EPSG:4326"
    assert args.resampling == "nearest"


def test_clip_reproject_schema_accepts_bbox_only() -> None:
    args = ClipReprojectArguments(imagery_id="94e758f38ede", bbox=[0.0, 0.0, 1.0, 1.0])
    assert args.bbox == [0.0, 0.0, 1.0, 1.0]


def test_clip_reproject_schema_requires_crs_or_bbox() -> None:
    with pytest.raises(ValidationError):
        ClipReprojectArguments(imagery_id="94e758f38ede")


def test_clip_reproject_schema_rejects_invalid_imagery_id() -> None:
    with pytest.raises(ValidationError):
        ClipReprojectArguments(imagery_id="BADID", dst_crs="EPSG:4326")


def test_clip_reproject_schema_rejects_bad_crs() -> None:
    with pytest.raises(ValidationError):
        ClipReprojectArguments(imagery_id="94e758f38ede", dst_crs="not-a-crs")


def test_clip_reproject_schema_accepts_bare_epsg_number() -> None:
    args = ClipReprojectArguments(imagery_id="94e758f38ede", dst_crs="32650")
    assert args.dst_crs == "32650"


def test_clip_reproject_schema_rejects_bbox_wrong_length() -> None:
    with pytest.raises(ValidationError):
        ClipReprojectArguments(imagery_id="94e758f38ede", bbox=[0.0, 0.0, 1.0])


def test_clip_reproject_schema_rejects_degenerate_bbox() -> None:
    with pytest.raises(ValidationError):
        ClipReprojectArguments(imagery_id="94e758f38ede", bbox=[2.0, 0.0, 1.0, 1.0])


def test_clip_reproject_schema_rejects_bad_resampling() -> None:
    with pytest.raises(ValidationError):
        ClipReprojectArguments(imagery_id="94e758f38ede", dst_crs="EPSG:4326", resampling="lanczos")


# ---------- runner 边界/错误路径 ----------

@pytest.mark.asyncio
async def test_clip_reproject_runner_invalid_imagery_id() -> None:
    result = await run_clip_reproject(
        ClipReprojectArguments.model_construct(imagery_id="BADID", dst_crs="EPSG:4326")
    )
    assert result.error == "invalid_imagery_id"


@pytest.mark.asyncio
async def test_clip_reproject_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    result = await run_clip_reproject(
        ClipReprojectArguments(imagery_id="94e758f38ede", dst_crs="EPSG:4326")
    )
    assert result.error == "imagery_not_found"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_clip_reproject_runner_mcp_disabled(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "false")
    get_settings.cache_clear()

    result = await run_clip_reproject(
        ClipReprojectArguments(imagery_id="94e758f38ede", dst_crs="EPSG:4326")
    )

    assert result.error == "mcp_disabled"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_clip_reproject_runner_mcp_error(monkeypatch, tmp_path: Path) -> None:
    from app.mcp.client import MCPCallError

    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    class _RaisingClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def call_tool(self, *a, **k):
            raise MCPCallError("boom")

    monkeypatch.setattr("app.agent.tools.clip_reproject.runner.RSToolsMCPClient", _RaisingClient)

    result = await run_clip_reproject(
        ClipReprojectArguments(imagery_id="94e758f38ede", dst_crs="EPSG:4326")
    )

    assert result.error == "mcp_error"
    assert result.metadata["error_code"] == "mcp_error"
    get_settings.cache_clear()


# ---------- runner 成功路径 ----------

@pytest.mark.asyncio
async def test_clip_reproject_runner_success(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    stub_stats = {
        "src_crs": "EPSG:32650",
        "dst_crs": "EPSG:4326",
        "width": 512,
        "height": 480,
        "band_count": 4,
        "clipped": False,
        "reprojected": True,
        "bounds_wgs84": [116.0, 39.0, 116.5, 39.5],
        "output_tif": "clip_reproject.tif",
        "output_png": "clip_reproject_colored.png",
    }

    captured: dict = {}

    class _OkClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def call_tool(self, tool_name, *, source_path, output_dir, arguments):
            assert tool_name == "clip_reproject_raster"
            captured.update(arguments)
            return stub_stats

    monkeypatch.setattr("app.agent.tools.clip_reproject.runner.RSToolsMCPClient", _OkClient)

    result = await run_clip_reproject(
        ClipReprojectArguments(imagery_id="94e758f38ede", dst_crs="EPSG:4326", resampling="bilinear")
    )

    assert result.error is None
    assert result.result_count == 1
    assert captured["dst_crs"] == "EPSG:4326"
    assert captured["resampling"] == "bilinear"
    geo = result.geospatial_result
    assert geo["type"] == "clip_reproject"
    assert geo["result_url"].endswith("clip_reproject_colored.png")
    assert geo["download_url"].endswith("clip_reproject.tif")
    assert geo["bounds"] == (116.0, 39.0, 116.5, 39.5)
    assert geo["stats"]["dst_crs"] == "EPSG:4326"
    assert geo["stats"]["reprojected"] is True
    assert result.artifacts and result.artifacts[0].type == "geospatial"
    assert result.metadata["execution_mode"] == "docker_mcp"
    assert "重投影" in result.tool_context
    get_settings.cache_clear()
