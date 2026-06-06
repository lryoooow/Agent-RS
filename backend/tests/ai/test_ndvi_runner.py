from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVIArguments
from app.core.settings import get_settings
from app.mcp.client import MCPCallError


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


@pytest.mark.asyncio
async def test_ndvi_runner_uses_rs_tools_client_and_keeps_result_shape(
    monkeypatch,
    tmp_path: Path,
) -> None:
    imagery_id = "94e758f38ede"
    imagery_dir = tmp_path / imagery_id
    results_dir = imagery_dir / "results"
    results_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "source.tif")
    _write_test_tif(imagery_dir / "working.tif")
    (imagery_dir / "metadata.json").write_text(
        '{"crs":"EPSG:4326","bounds":[100,20,101,21]}',
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    async def fake_call_tool(self, tool_name, *, source_path, output_dir, arguments=None):
        seen["tool_name"] = tool_name
        seen["source_path"] = source_path
        seen["output_dir"] = output_dir
        seen["arguments"] = arguments
        return {
            "min": 0.1,
            "max": 0.8,
            "mean": 0.4,
            "std": 0.2,
            "nodata_pct": 0.0,
            "output_png": "ndvi_colored.png",
            "output_tif": "ndvi.tif",
        }

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    result = await run_ndvi(NDVIArguments(imagery_id=imagery_id))

    assert result.error is None
    assert seen == {
        "tool_name": "calculate_ndvi",
        "source_path": imagery_dir / "working.tif",
        "output_dir": results_dir,
        "arguments": {"red_band": 3, "nir_band": 4},
    }
    assert result.geospatial_result
    assert result.geospatial_result["type"] == "ndvi"
    assert result.geospatial_result["execution"]["mode"] == "docker_mcp"
    assert result.geospatial_result["legend"]["palette"] == "vegetation"
    assert result.geospatial_result["result_url"].endswith("/ndvi_colored.png")
    assert result.metadata["execution_mode"] == "docker_mcp"


@pytest.mark.asyncio
async def test_ndvi_runner_rejects_invalid_band_before_client_call(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    imagery_dir = tmp_path / imagery_id
    imagery_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "working.tif", count=4)

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("NDVI client should not run for invalid bands")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_if_called)

    result = await run_ndvi(
        NDVIArguments.model_construct(imagery_id=imagery_id, red_band=0, nir_band=4, reason="test")
    )

    assert result.error == "invalid_bands"
    assert "波段索引必须从 1 开始" in result.tool_context


@pytest.mark.asyncio
async def test_ndvi_runner_rejects_invalid_imagery_id_before_path_lookup() -> None:
    get_settings.cache_clear()

    result = await run_ndvi(
        NDVIArguments.model_construct(imagery_id="../bad", red_band=3, nir_band=4, reason="test")
    )

    assert result.error == "invalid_imagery_id"


def test_ndvi_arguments_reject_invalid_imagery_id_at_schema_layer() -> None:
    with pytest.raises(ValidationError):
        NDVIArguments(imagery_id="../bad")


@pytest.mark.asyncio
async def test_ndvi_runner_rejects_band_above_available_count_before_client_call(
    monkeypatch,
    tmp_path: Path,
) -> None:
    imagery_id = "94e758f38ede"
    imagery_dir = tmp_path / imagery_id
    imagery_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "working.tif", count=4)

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("NDVI client should not run for unavailable bands")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_if_called)

    result = await run_ndvi(
        NDVIArguments(imagery_id=imagery_id, red_band=3, nir_band=5, reason="test")
    )

    assert result.error == "invalid_bands"
    assert result.metadata["error_code"] == "invalid_bands"


@pytest.mark.asyncio
async def test_ndvi_runner_returns_mcp_error_without_local_fallback(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    imagery_dir = tmp_path / imagery_id
    imagery_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "working.tif", count=4)

    async def fail_client(*_args, **_kwargs):
        raise MCPCallError("container failed")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_client)

    result = await run_ndvi(NDVIArguments(imagery_id=imagery_id))

    assert result.error == "mcp_error"
    assert "container failed" in result.tool_context
    assert result.metadata["execution_mode"] == "failed"


@pytest.mark.asyncio
async def test_ndvi_runner_returns_unexpected_error(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    imagery_dir = tmp_path / imagery_id
    imagery_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "working.tif", count=4)

    async def fail_client(*_args, **_kwargs):
        raise RuntimeError("bad")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_client)

    result = await run_ndvi(NDVIArguments(imagery_id=imagery_id))

    assert result.error == "unexpected_error"
    assert "bad" in result.tool_context
