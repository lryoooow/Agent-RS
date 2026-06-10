from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio

from app.agent.tools.spectral_index.runner import run_spectral_index
from app.agent.tools.spectral_index.schema import SpectralIndexArguments
from app.core.settings import get_settings
from app.mcp.client import MCPCallError


IMAGERY_ID = "94e758f38ede"


def _write_test_tif(path: Path, *, count: int = 5) -> None:
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


def _prepare_imagery(root: Path, *, count: int = 5) -> Path:
    imagery_dir = root / IMAGERY_ID
    results_dir = imagery_dir / "results"
    results_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "working.tif", count=count)
    (imagery_dir / "metadata.json").write_text(
        '{"crs":"EPSG:4326","bounds":[100,20,101,21]}',
        encoding="utf-8",
    )
    return imagery_dir


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("index_type", "palette"),
    [
        ("mndwi", "water"),
        ("ndwi", "water"),
        ("msavi", "vegetation"),
        ("savi", "vegetation"),
        ("bsi", "built"),
    ],
)
async def test_spectral_index_runner_uses_rs_tools_client_and_keeps_result_shape(
    monkeypatch,
    tmp_path: Path,
    index_type: str,
    palette: str,
) -> None:
    imagery_dir = _prepare_imagery(tmp_path)
    seen: dict[str, Any] = {}

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        seen["tool_name"] = tool_name
        seen["source_path"] = source_path
        seen["output_dir"] = output_dir
        seen["arguments"] = arguments
        return {
            "min": 0.1,
            "max": 0.9,
            "mean": 0.4,
            "std": 0.2,
            "nodata_pct": 0.0,
            "output_png": f"{arguments['index_type']}_colored.png",
        }

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    result = await run_spectral_index(SpectralIndexArguments(imagery_id=IMAGERY_ID, index_type=index_type))

    assert result.error is None
    assert seen["tool_name"] == "calculate_spectral_index"
    assert seen["source_path"] == imagery_dir / "working.tif"
    assert seen["output_dir"] == imagery_dir / "results"
    assert seen["arguments"]["index_type"] == index_type
    assert result.geospatial_result["type"] == "spectral_index"
    assert result.geospatial_result["index_type"] == index_type
    assert result.geospatial_result["stats"]["mean"] == 0.4
    assert result.geospatial_result["legend"]["palette"] == palette
    assert result.geospatial_result["result_url"].endswith(f"/{index_type}_colored.png")
    assert result.metadata["execution_mode"] == "docker_mcp"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_spectral_index_runner_returns_mcp_error_without_fallback(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path)

    async def fail_client(*_args, **_kwargs):
        raise MCPCallError("container failed")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_client)

    result = await run_spectral_index(SpectralIndexArguments(imagery_id=IMAGERY_ID, index_type="ndwi"))

    assert result.error == "mcp_error"
    assert "container failed" in result.tool_context
    assert result.metadata["execution_mode"] == "failed"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_spectral_index_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    result = await run_spectral_index(SpectralIndexArguments(imagery_id=IMAGERY_ID, index_type="ndwi"))

    assert result.error == "imagery_not_found"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_spectral_index_runner_invalid_imagery_id() -> None:
    result = await run_spectral_index(
        SpectralIndexArguments.model_construct(imagery_id="../bad", index_type="ndwi")
    )

    assert result.error == "invalid_imagery_id"
