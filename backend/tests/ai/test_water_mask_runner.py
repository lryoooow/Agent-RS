from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from app.agent.tools.water_mask.runner import run_water_mask
from app.agent.tools.water_mask.schema import WaterMaskArguments
from app.core.settings import get_settings


def _write_test_tif(path: Path, *, count: int = 4) -> None:
    data = np.ones((count, 2, 2), dtype=np.uint16)
    with rasterio.open(
        path, "w", driver="GTiff", height=2, width=2, count=count, dtype="uint16"
    ) as dst:
        dst.write(data)


# ---------- schema ----------

def test_water_mask_schema_defaults() -> None:
    args = WaterMaskArguments(imagery_id="94e758f38ede")
    assert (args.green_band, args.nir_band) == (2, 4)
    assert args.reason


def test_water_mask_schema_rejects_invalid_imagery_id() -> None:
    with pytest.raises(ValidationError):
        WaterMaskArguments(imagery_id="BADID")


def test_water_mask_schema_rejects_band_below_one() -> None:
    with pytest.raises(ValidationError):
        WaterMaskArguments(imagery_id="94e758f38ede", green_band=0)


# ---------- runner 边界/错误路径 ----------

@pytest.mark.asyncio
async def test_water_mask_runner_invalid_imagery_id() -> None:
    result = await run_water_mask(WaterMaskArguments.model_construct(imagery_id="BADID"))
    assert result.error == "invalid_imagery_id"


@pytest.mark.asyncio
async def test_water_mask_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    result = await run_water_mask(WaterMaskArguments(imagery_id="94e758f38ede"))
    assert result.error == "imagery_not_found"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_water_mask_runner_mcp_disabled(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "false")
    get_settings.cache_clear()

    result = await run_water_mask(WaterMaskArguments(imagery_id="94e758f38ede"))

    assert result.error == "mcp_disabled"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_water_mask_runner_mcp_error(monkeypatch, tmp_path: Path) -> None:
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

    monkeypatch.setattr("app.agent.tools.water_mask.runner.RSToolsMCPClient", _RaisingClient)

    result = await run_water_mask(WaterMaskArguments(imagery_id="94e758f38ede"))

    assert result.error == "mcp_error"
    assert result.metadata["error_code"] == "mcp_error"
    get_settings.cache_clear()


# ---------- runner 成功路径 ----------

@pytest.mark.asyncio
async def test_water_mask_runner_success(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    stub_stats = {
        "water_pct": 22.0,
        "non_water_pct": 78.0,
        "nodata_pct": 0.0,
        "ndwi_threshold": 0.12,
        "output_tif": "water_mask.tif",
        "output_png": "water_mask_colored.png",
    }

    class _OkClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def call_tool(self, tool_name, *, source_path, output_dir, arguments):
            assert tool_name == "extract_water_mask"
            assert arguments == {"green_band": 2, "nir_band": 4}
            return stub_stats

    monkeypatch.setattr("app.agent.tools.water_mask.runner.RSToolsMCPClient", _OkClient)

    result = await run_water_mask(WaterMaskArguments(imagery_id="94e758f38ede"))

    assert result.error is None
    assert result.result_count == 1
    geo = result.geospatial_result
    assert geo["type"] == "water_mask"
    assert geo["result_url"].endswith("water_mask_colored.png")
    assert geo["stats"]["water_pct"] == 22.0
    assert geo["stats"]["ndwi_threshold"] == 0.12
    assert result.artifacts and result.artifacts[0].type == "geospatial"
    assert result.metadata["execution_mode"] == "docker_mcp"
    assert "水体占比" in result.tool_context
    get_settings.cache_clear()
