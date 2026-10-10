from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin

from app.agent.tools.cloud_mask.runner import run_cloud_mask
from app.agent.tools.cloud_mask.schema import CloudMaskArguments
from app.core.settings import get_settings

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "docker" / "rs_tools"))
from compute_cloud_mask import compute

ID = "94e758f38ede"


def _write_source(path: Path, *, count=4):
    with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=count, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(100, 20, .01, .01)) as dst:
        dst.write(np.full((count, 2, 2), .45, dtype=np.float32))
        dst.units = ("reflectance",) * count
        dst.update_tags(SENSOR="Sentinel-2B")
        for index, label in enumerate(("Blue", "Green", "Red", "NIR")[:count], 1):
            dst.set_band_description(index, label)


def _qa(directory: Path, *, classes=None):
    with rasterio.open(directory / "quality.tif", "w", driver="GTiff", height=2, width=2, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=from_origin(100, 20, .01, .01)) as dst:
        dst.write(np.asarray(classes if classes is not None else [[5, 9], [3, 7]], dtype="uint8"), 1)
        dst.update_tags(QA_TYPE="sentinel2_scl", QA_SOURCE="sentinel2", QA_ITEM_ID="test-scene", QA_SENSOR="Sentinel-2B")
    meta = {"source_origin": "stac_composition", "source_item_id": "test-scene", "source_scene_key": "aabbccddeeff",
            "sensor": "Sentinel-2B", "bounds": [100, 19.98, 100.02, 20],
            "quality_mask": {"filename": "quality.tif", "type": "sentinel2_scl", "source": "sentinel2",
                             "item_id": "test-scene", "scene_key": "aabbccddeeff"}}
    (directory / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


@pytest.fixture
def imagery(monkeypatch, tmp_path):
    directory = tmp_path / ID
    directory.mkdir()
    _write_source(directory / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()
    yield directory
    get_settings.cache_clear()


class ActualComputeClient:
    def __init__(self, *a, **k):
        pass

    async def call_tool(self, name, *, source_path, output_dir, arguments):
        assert name == "cloud_shadow_mask"
        args = dict(arguments)
        if args.get("method") == "quality":
            assert args["quality_path"] == "/data/quality.tif" and args["quality_type"] == "sentinel2_scl"
            args["quality_path"] = str(source_path.parent / "quality.tif")
        return compute(input_path=str(source_path), output_dir=str(output_dir), **args)


def test_cloud_mask_schema_defaults():
    args = CloudMaskArguments(imagery_id=ID)
    assert args.method == "quality"
    assert (args.red_band, args.green_band, args.blue_band, args.nir_band) == (3, 2, 1, 4)


@pytest.mark.parametrize("kwargs", [{"imagery_id": "BADID"}, {"imagery_id": ID, "red_band": 0},
                                      {"imagery_id": ID, "method": "fmask"},
                                      {"imagery_id": ID, "quality_path": "D:/other/quality.tif"},
                                      {"imagery_id": ID, "quality_type": "sentinel2_scl"}])
def test_cloud_schema_rejects_invalid_and_server_path_parameters(kwargs):
    with pytest.raises(ValidationError):
        CloudMaskArguments(**kwargs)


@pytest.mark.asyncio
async def test_cloud_mask_runner_invalid_imagery_id():
    result = await run_cloud_mask(CloudMaskArguments.model_construct(imagery_id="BADID"))
    assert result.error == "invalid_imagery_id"


@pytest.mark.asyncio
async def test_cloud_mask_runner_imagery_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert (await run_cloud_mask(CloudMaskArguments(imagery_id=ID))).error == "imagery_not_found"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cloud_mask_runner_mcp_disabled(imagery, monkeypatch):
    monkeypatch.setenv("RS_TOOLS_MCP_USE_DOCKER", "false")
    get_settings.cache_clear()
    assert (await run_cloud_mask(CloudMaskArguments(imagery_id=ID))).error == "mcp_disabled"


@pytest.mark.asyncio
async def test_missing_qa_returns_unavailable_without_mcp_or_results(imagery, monkeypatch):
    def must_not_construct(*a, **kw):
        pytest.fail("Missing QA must not invoke Docker or heuristic")
    monkeypatch.setattr("app.agent.tools.cloud_mask.runner.RSToolsMCPClient", must_not_construct)
    result = await run_cloud_mask(CloudMaskArguments(imagery_id=ID))
    assert result.error == "quality_mask_unavailable"
    assert result.geospatial_result is None and not result.artifacts
    assert not (imagery / "results").exists()


@pytest.mark.parametrize("field", ["filename", "type", "source", "item_id", "scene_key", "origin", "sensor", "nonstring_type"])
@pytest.mark.asyncio
async def test_qa_manifest_provenance_is_enforced(imagery, field, monkeypatch):
    meta = _qa(imagery)
    if field == "origin": meta["source_origin"] = "user_upload"
    elif field == "sensor": meta["sensor"] = "Landsat 8"
    elif field == "nonstring_type": meta["quality_mask"]["type"] = []
    else: meta["quality_mask"][field] = "../another/quality.tif" if field == "filename" else "different"
    (imagery / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    def must_not_construct(*a, **kw):
        pytest.fail("Invalid provenance must not invoke MCP")
    monkeypatch.setattr("app.agent.tools.cloud_mask.runner.RSToolsMCPClient", must_not_construct)
    assert (await run_cloud_mask(CloudMaskArguments(imagery_id=ID))).error == "quality_mask_invalid"


@pytest.mark.asyncio
async def test_qa_manifest_does_not_hide_missing_product(imagery):
    _qa(imagery)
    (imagery / "quality.tif").unlink()
    assert (await run_cloud_mask(CloudMaskArguments(imagery_id=ID))).error == "quality_mask_unavailable"


@pytest.mark.asyncio
async def test_corrupt_quality_is_rejected_before_mcp_success(imagery):
    _qa(imagery)
    (imagery / "quality.tif").write_bytes(b"not a TIFF")
    assert (await run_cloud_mask(CloudMaskArguments(imagery_id=ID))).error == "quality_mask_invalid"


@pytest.mark.asyncio
async def test_cloud_mask_runner_mcp_error(imagery, monkeypatch):
    from app.mcp.client import MCPCallError
    _qa(imagery)
    class RaisingClient:
        def __init__(self, *a, **k): pass
        async def call_tool(self, *a, **k): raise MCPCallError("boom")
    monkeypatch.setattr("app.agent.tools.cloud_mask.runner.RSToolsMCPClient", RaisingClient)
    result = await run_cloud_mask(CloudMaskArguments(imagery_id=ID))
    assert result.error == "mcp_error" and result.metadata["error_code"] == "mcp_error"


@pytest.mark.asyncio
async def test_cloud_mask_runner_uses_real_quality_compute(imagery, monkeypatch):
    _qa(imagery)
    monkeypatch.setattr("app.agent.tools.cloud_mask.runner.RSToolsMCPClient", ActualComputeClient)
    result = await run_cloud_mask(CloudMaskArguments(imagery_id=ID))
    assert result.error is None and result.result_count == 1
    geo = result.geospatial_result
    assert geo["type"] == "cloud_mask" and geo["stats"]["cloud_pct"] == 25.0
    assert geo["stats"]["unknown_pct"] == 25.0 and geo["stats"]["shadow_pct"] == 25.0
    assert geo["stats"]["method"] == "quality_mask" and geo["stats"]["valid_pixels"] == 4
    assert geo["legend"]["classes"][4]["name"] == "未知/未分类"
    assert result.artifacts and result.artifacts[0].type == "geospatial"
    assert "未标记云/云影不能保证" in result.tool_context
    assert "适合后续分析" not in result.tool_context


@pytest.mark.asyncio
async def test_quality_does_not_need_four_spectral_bands(imagery, monkeypatch):
    _write_source(imagery / "working.tif", count=1)
    _qa(imagery, classes=[[5, 5], [5, 5]])
    monkeypatch.setattr("app.agent.tools.cloud_mask.runner.RSToolsMCPClient", ActualComputeClient)
    result = await run_cloud_mask(CloudMaskArguments(imagery_id=ID))
    assert result.error is None and result.geospatial_result["stats"]["clear_pct"] == 100.0


@pytest.mark.asyncio
async def test_explicit_heuristic_context_is_unvalidated(imagery, monkeypatch):
    monkeypatch.setattr("app.agent.tools.cloud_mask.runner.RSToolsMCPClient", ActualComputeClient)
    result = await run_cloud_mask(CloudMaskArguments(imagery_id=ID, method="heuristic"))
    assert result.error is None
    stats = result.geospatial_result["stats"]
    assert stats["cloud_pct"] is None and stats["candidate_bright_pct"] == 100.0
    assert "未验证" in result.tool_context and "不得把候选比例称为云量" in result.tool_context
    assert result.geospatial_result["legend"]["classes"][1]["name"] == "疑似高亮"


@pytest.mark.asyncio
async def test_old_container_result_without_method_is_rejected(imagery, monkeypatch):
    _qa(imagery)
    class OldClient:
        def __init__(self, *a, **k): pass
        async def call_tool(self, *a, **k):
            return {"cloud_pct": 100.0, "output_png": "old.png"}
    monkeypatch.setattr("app.agent.tools.cloud_mask.runner.RSToolsMCPClient", OldClient)
    assert (await run_cloud_mask(CloudMaskArguments(imagery_id=ID))).error == "invalid_tool_result"


@pytest.mark.parametrize("arguments", [{"red_band": 1}, {"red_band": 2, "green_band": 2}, {"nir_band": 20}])
@pytest.mark.asyncio
async def test_explicit_heuristic_cannot_override_authoritative_spectral_roles(imagery, monkeypatch, arguments):
    def must_not_construct(*a, **kw):
        pytest.fail("Invalid spectral selection must not invoke MCP")
    monkeypatch.setattr("app.agent.tools.cloud_mask.runner.RSToolsMCPClient", must_not_construct)
    result = await run_cloud_mask(CloudMaskArguments(imagery_id=ID, method="heuristic", **arguments))
    assert result.error == "invalid_bands"


@pytest.mark.asyncio
async def test_heuristic_without_nir_is_unavailable_not_alpha_analysis(imagery):
    _write_source(imagery / "working.tif", count=3)
    result = await run_cloud_mask(CloudMaskArguments(imagery_id=ID, method="heuristic"))
    assert result.error == "band_roles_unknown"
