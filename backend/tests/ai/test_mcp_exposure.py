from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.core.settings import get_settings
from app.agent.tool_registry import TOOLS


ROOT = Path(__file__).resolve().parents[3]


EXPECTED_MCP_TOOLS = {
    "rs_tools": {
        "raster_inspect",
        "calculate_ndvi",
        "calculate_spectral_index",
        "render_band_composite",
        "cloud_shadow_mask",
        "extract_water_mask",
        "clip_reproject_raster",
    },
    "rs_detect": {"detect_objects"},
    "rs_segment": {"segment_landcover"},
    "rs_doc": {"ocr_recognize"},
}

VALID_RUNNER_ARGS = {
    "raster_inspect": {"imagery_id": "94e758f38ede"},
    "calculate_ndvi": {"imagery_id": "94e758f38ede"},
    "calculate_spectral_index": {"imagery_id": "94e758f38ede", "index_type": "ndwi"},
    "render_band_composite": {"imagery_id": "94e758f38ede", "mode": "true_color"},
    "cloud_shadow_mask": {"imagery_id": "94e758f38ede"},
    "extract_water_mask": {"imagery_id": "94e758f38ede"},
    "clip_reproject_raster": {"imagery_id": "94e758f38ede", "dst_crs": "EPSG:4326"},
    "detect_objects": {"imagery_id": "94e758f38ede"},
    "segment_landcover": {"imagery_id": "94e758f38ede"},
    "ocr_recognize": {"imagery_id": "94e758f38ede"},
}

STUB_MCP_RESULTS = {
    "raster_inspect": {
        "width": 2,
        "height": 2,
        "band_count": 6,
        "crs": "EPSG:4326",
        "bounds": [100.0, 19.98, 100.02, 20.0],
        "pixel_size": [0.01, 0.01],
        "dtype": "uint16",
        "nodata": None,
        "capabilities": {
            "has_blue": True,
            "has_green": True,
            "has_red": True,
            "has_nir": True,
            "has_swir": True,
        },
        "per_band_stats": [],
    },
    "calculate_ndvi": {
        "min": 0.1,
        "max": 0.8,
        "mean": 0.4,
        "std": 0.2,
        "nodata_pct": 0.0,
        "output_png": "ndvi_colored.png",
    },
    "calculate_spectral_index": {
        "min": -0.2,
        "max": 0.7,
        "mean": 0.25,
        "std": 0.12,
        "nodata_pct": 0.0,
        "output_png": "ndwi_colored.png",
    },
    "render_band_composite": {
        "output_png": "composite_true_color.png",
        "bands_used": [3, 2, 1],
    },
    "cloud_shadow_mask": {
        "cloud_pct": 3.0,
        "shadow_pct": 2.0,
        "clear_pct": 95.0,
        "nodata_pct": 0.0,
        "output_png": "cloud_mask_colored.png",
    },
    "extract_water_mask": {
        "water_pct": 20.0,
        "non_water_pct": 80.0,
        "nodata_pct": 0.0,
        "ndwi_threshold": 0.1,
        "output_png": "water_mask_colored.png",
    },
    "clip_reproject_raster": {
        "src_crs": "EPSG:4326",
        "dst_crs": "EPSG:4326",
        "width": 2,
        "height": 2,
        "band_count": 6,
        "clipped": False,
        "reprojected": True,
        "bounds_wgs84": [100.0, 19.98, 100.02, 20.0],
        "output_tif": "clip_reproject.tif",
        "output_png": "clip_reproject_colored.png",
    },
    "detect_objects": {
        "output_png": "detection_overlay.png",
        "detection_count": 0,
        "score_threshold": 0.3,
        "classes": [],
    },
    "segment_landcover": {
        "output_png": "segmentation_overlay.png",
        "total_pixels": 4,
        "classes": [],
    },
    "ocr_recognize": {
        "full_text": "测试文本",
        "blocks": [],
        "block_count": 1,
        "char_count": 4,
        "avg_confidence": 0.9,
        "min_confidence_seen": 0.9,
        "grayscale": False,
    },
}


def _load_mcp_server(directory_name: str) -> ModuleType:
    server_dir = ROOT / "docker" / directory_name
    server_path = server_dir / "mcp_server.py"
    module_name = f"test_{directory_name}_mcp_server"
    spec = importlib.util.spec_from_file_location(module_name, server_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(server_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(server_dir))
    return module


def _write_contract_tif(path: Path) -> None:
    data = np.ones((6, 2, 2), dtype=np.uint16)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=6,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(100.0, 20.0, 0.01, 0.01),
    ) as dst:
        dst.write(data)


def test_docker_mcp_servers_expose_exact_tool_sets() -> None:
    for directory_name, expected in EXPECTED_MCP_TOOLS.items():
        module = _load_mcp_server(directory_name)
        actual = {tool["name"] for tool in module.TOOL_DEFINITIONS}

        assert actual == expected, directory_name


def test_mcp_tool_definitions_have_required_protocol_shape() -> None:
    for directory_name in EXPECTED_MCP_TOOLS:
        module = _load_mcp_server(directory_name)
        for tool in module.TOOL_DEFINITIONS:
            assert set(tool) >= {"name", "description", "inputSchema"}, directory_name
            input_schema = tool["inputSchema"]
            assert input_schema["type"] == "object"
            assert input_schema["additionalProperties"] is False
            assert "properties" in input_schema
            assert set(input_schema["required"]).issubset(set(input_schema["properties"]))
            assert "input_path" in input_schema["required"]
            if tool["name"] != "raster_inspect":
                assert "output_dir" in input_schema["required"]


@pytest.mark.asyncio
async def test_actual_backend_mcp_payload_fields_are_accepted_by_container_schemas(
    monkeypatch,
    tmp_path: Path,
) -> None:
    all_mcp_tool_names = set().union(*EXPECTED_MCP_TOOLS.values())
    registered_mcp_tools = {name for name, tool in TOOLS.items() if "mcp" in tool.tags}
    captured_payload_keys: dict[str, set[str]] = {}

    assert registered_mcp_tools == all_mcp_tool_names
    assert set(VALID_RUNNER_ARGS) == all_mcp_tool_names
    assert set(STUB_MCP_RESULTS) == all_mcp_tool_names

    imagery_id = "94e758f38ede"
    imagery_dir = tmp_path / imagery_id
    imagery_dir.mkdir()
    _write_contract_tif(imagery_dir / "working.tif")
    (imagery_dir / "metadata.json").write_text(
        '{"crs":"EPSG:4326","bounds":[100.0,19.98,100.02,20.0]}',
        encoding="utf-8",
    )

    async def fake_call_tool(self, tool_name, *, source_path, output_dir=None, arguments=None):
        keys = set(arguments or {})
        keys.add("input_path")
        if output_dir is not None:
            keys.add("output_dir")
        captured_payload_keys[tool_name] = keys
        return STUB_MCP_RESULTS[tool_name]

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    monkeypatch.setenv("RS_DETECT_MCP_USE_DOCKER", "true")
    monkeypatch.setenv("RS_SEGMENT_MCP_USE_DOCKER", "true")
    monkeypatch.setenv("RS_DOC_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool", fake_call_tool)

    try:
        for tool_name in sorted(all_mcp_tool_names):
            registered_tool = TOOLS[tool_name]
            args = registered_tool.argument_model.model_validate(VALID_RUNNER_ARGS[tool_name])
            result = await registered_tool.runner(args)

            assert result.error is None, tool_name

        assert set(captured_payload_keys) == all_mcp_tool_names

        for directory_name, tool_names in EXPECTED_MCP_TOOLS.items():
            module = _load_mcp_server(directory_name)
            schema_by_name = {
                tool["name"]: tool["inputSchema"]
                for tool in module.TOOL_DEFINITIONS
                if tool["name"] in tool_names
            }

            for tool_name in tool_names:
                properties = set(schema_by_name[tool_name]["properties"])
                assert captured_payload_keys[tool_name] == properties, tool_name
    finally:
        get_settings.cache_clear()
