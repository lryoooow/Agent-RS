from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio

from app.agent.tools.raster_inspect.runner import run_raster_inspect
from app.agent.tools.raster_inspect.schema import RasterInspectArguments
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


def _prepare_imagery(root: Path) -> Path:
    imagery_dir = root / IMAGERY_ID
    imagery_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "working.tif")
    return imagery_dir


@pytest.mark.asyncio
async def test_raster_inspect_runner_uses_rs_tools_client_and_keeps_result_shape(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = _prepare_imagery(tmp_path)
    seen: dict[str, object] = {}

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        seen["tool_name"] = tool_name
        seen["source_path"] = source_path
        return {
            "width": 2,
            "height": 2,
            "band_count": 4,
            "crs": "EPSG:4326",
            "bounds": [100, 20, 101, 21],
            "pixel_size": [0.5, 0.5],
            "dtype": "uint16",
            "nodata": None,
            "capabilities": {"has_blue": True, "has_green": True, "has_red": True, "has_nir": True},
            "per_band_stats": [{"band": 1, "min": 1, "max": 1, "mean": 1, "std": 0}],
        }

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    result = await run_raster_inspect(RasterInspectArguments(imagery_id=IMAGERY_ID))

    assert result.error is None
    assert seen == {"tool_name": "raster_inspect", "source_path": imagery_dir / "working.tif"}
    assert result.tool_result["type"] == "raster_inspect"
    assert result.tool_result["band_count"] == 4
    assert result.tool_result["execution"]["mode"] == "docker_mcp"
    assert result.metadata["execution_mode"] == "docker_mcp"
    assert result.metadata["inspect"]["band_count"] == 4
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_raster_inspect_runner_returns_mcp_error_without_fallback(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path)

    async def fail_client(*_args, **_kwargs):
        raise MCPCallError("container failed")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_client)

    result = await run_raster_inspect(RasterInspectArguments(imagery_id=IMAGERY_ID))

    assert result.error == "mcp_error"
    assert "container failed" in result.tool_context
    assert result.metadata["execution_mode"] == "failed"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_raster_inspect_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    result = await run_raster_inspect(RasterInspectArguments(imagery_id=IMAGERY_ID))

    assert result.error == "imagery_not_found"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_raster_inspect_runner_invalid_imagery_id() -> None:
    result = await run_raster_inspect(RasterInspectArguments.model_construct(imagery_id="../bad"))

    assert result.error == "invalid_imagery_id"
