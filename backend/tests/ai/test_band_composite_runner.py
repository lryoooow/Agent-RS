from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio

from app.agent.tools.band_composite.runner import run_band_composite
from app.agent.tools.band_composite.schema import BandCompositeArguments
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


def _prepare_imagery(root: Path, *, count: int = 4) -> Path:
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
async def test_band_composite_runner_uses_rs_tools_client_and_keeps_result_shape(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = _prepare_imagery(tmp_path)
    seen: dict[str, Any] = {}

    async def fake_call_tool(self, tool_name, *, source_path=None, output_dir=None, arguments=None):
        seen["tool_name"] = tool_name
        seen["source_path"] = source_path
        seen["output_dir"] = output_dir
        seen["arguments"] = arguments
        return {"bands_used": [3, 2, 1], "output_png": "composite_true_color.png"}

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    result = await run_band_composite(BandCompositeArguments(imagery_id=IMAGERY_ID, mode="true_color"))

    assert result.error is None
    assert seen["tool_name"] == "render_band_composite"
    assert seen["source_path"] == imagery_dir / "working.tif"
    assert seen["output_dir"] == imagery_dir / "results"
    assert seen["arguments"]["mode"] == "true_color"
    assert result.geospatial_result["type"] == "composite"
    assert result.geospatial_result["bands_used"] == [3, 2, 1]
    assert result.geospatial_result["execution"]["mode"] == "docker_mcp"
    assert result.metadata["execution_mode"] == "docker_mcp"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_band_composite_runner_returns_mcp_error_without_fallback(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path)

    async def fail_client(*_args, **_kwargs):
        raise MCPCallError("container failed")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_client)

    result = await run_band_composite(BandCompositeArguments(imagery_id=IMAGERY_ID, mode="true_color"))

    assert result.error == "mcp_error"
    assert "container failed" in result.tool_context
    assert result.metadata["execution_mode"] == "failed"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_band_composite_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    result = await run_band_composite(BandCompositeArguments(imagery_id=IMAGERY_ID, mode="true_color"))

    assert result.error == "imagery_not_found"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_band_composite_runner_invalid_imagery_id() -> None:
    result = await run_band_composite(
        BandCompositeArguments.model_construct(imagery_id="../bad", mode="true_color", bands=None)
    )

    assert result.error == "invalid_imagery_id"
