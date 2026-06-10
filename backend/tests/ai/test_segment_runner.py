import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from pydantic import ValidationError

from app.agent.tools.segment.runner import run_segment
from app.agent.tools.segment.schema import SegmentArguments
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
        crs="EPSG:4326",
        transform=from_origin(100.0, 20.0, 0.01, 0.01),
    ) as dst:
        dst.write(data)


def _prepare_imagery(root: Path, imagery_id: str = "94e758f38ede", *, count: int = 4) -> Path:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif", count=count)
    (imagery_dir / "metadata.json").write_text(
        json.dumps({"bounds": [100.0, 19.98, 100.02, 20.0]}),
        encoding="utf-8",
    )
    return imagery_dir


def test_segment_schema_rejects_duplicate_bands() -> None:
    with pytest.raises(ValidationError):
        SegmentArguments(imagery_id="94e758f38ede", red_band=2, green_band=2, blue_band=3)


def test_segment_schema_rejects_invalid_imagery_id() -> None:
    with pytest.raises(ValidationError):
        SegmentArguments(imagery_id="BADID")


def test_segment_schema_defaults() -> None:
    args = SegmentArguments(imagery_id="94e758f38ede")
    assert (args.red_band, args.green_band, args.blue_band) == (3, 2, 1)
    assert args.reason


@pytest.mark.asyncio
async def test_segment_runner_invalid_imagery_id() -> None:
    result = await run_segment(SegmentArguments.model_construct(imagery_id="BADID"))
    assert result.error == "invalid_imagery_id"


@pytest.mark.asyncio
async def test_segment_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    result = await run_segment(SegmentArguments(imagery_id="94e758f38ede"))
    assert result.error == "imagery_not_found"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_segment_runner_uses_independent_docker_disabled_switch(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    monkeypatch.setenv("RS_SEGMENT_MCP_USE_DOCKER", "false")
    get_settings.cache_clear()

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("segment MCP client should not run when RS_SEGMENT_MCP_USE_DOCKER=false")

    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_if_called)

    result = await run_segment(SegmentArguments(imagery_id="94e758f38ede"))

    assert result.error == "mcp_disabled"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_segment_runner_can_run_when_rs_tools_switch_is_disabled(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    _prepare_imagery(tmp_path, imagery_id)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "false")
    monkeypatch.setenv("RS_SEGMENT_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    seen: dict[str, object] = {}

    async def ok_client(self, tool_name, *, source_path, output_dir, arguments=None):
        seen["tool_name"] = tool_name
        seen["arguments"] = arguments
        return {
            "output_png": "segmentation_overlay.png",
            "total_pixels": 4,
            "classes": [
                {"name": "water", "label": "water", "pixel_count": 2, "percentage": 50.0, "color": "#0082c8"},
            ],
        }

    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", ok_client)

    result = await run_segment(SegmentArguments(imagery_id="94e758f38ede"))

    assert result.error is None
    assert seen["tool_name"] == "segment_landcover"
    assert seen["arguments"] == {
        "red_band": 3,
        "green_band": 2,
        "blue_band": 1,
    }
    assert result.result_count == 1
    assert result.metadata["execution_mode"] == "docker_mcp"
    assert len(result.artifacts) == 1

    geo = result.geospatial_result
    assert geo is not None
    assert result.artifacts[0].payload == geo
    assert geo["type"] == "segmentation"
    assert geo["imagery_id"] == imagery_id
    assert geo["result_url"] == f"/api/imagery/{imagery_id}/results/segmentation_overlay.png"
    assert geo["bounds"] == (100.0, 19.98, 100.02, 20.0)
    assert geo["total_pixels"] == 4
    assert geo["classes"] == [
        {"name": "water", "label": "water", "pixel_count": 2, "percentage": 50.0, "color": "#0082c8"},
    ]
    assert geo["execution"]["mode"] == "docker_mcp"
    assert geo["execution"]["fallback_used"] is False
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        MCPCallError("mcp failed"),
        asyncio.TimeoutError(),
        FileNotFoundError("missing docker"),
    ],
)
async def test_segment_runner_transport_failures_return_mcp_error(
    monkeypatch,
    tmp_path: Path,
    exc: Exception,
) -> None:
    _prepare_imagery(tmp_path)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_SEGMENT_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    async def fail_client(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_client)

    result = await run_segment(SegmentArguments(imagery_id="94e758f38ede"))

    assert result.error == "mcp_error"
    assert result.metadata["error_code"] == "mcp_error"
    assert result.metadata["execution_mode"] == "failed"
    assert result.geospatial_result is None
    assert result.artifacts == []
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_segment_runner_unexpected_exception_returns_unexpected_error(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_SEGMENT_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    async def fail_client(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fail_client)

    result = await run_segment(SegmentArguments(imagery_id="94e758f38ede"))

    assert result.error == "unexpected_error"
    assert result.metadata["error_code"] == "unexpected_error"
    assert result.metadata["execution_mode"] == "failed"
    assert result.geospatial_result is None
    assert result.artifacts == []
    get_settings.cache_clear()
