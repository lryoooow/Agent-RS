from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import AsyncMock
import rasterio
from rasterio.enums import ColorInterp
from rasterio.transform import from_origin

from app.services.raster_semantics import resolve_spectral_bands
from app.services.imagery_persist import _extract_metadata


@pytest.fixture(autouse=True)
def local_contract_has_no_application_pool(monkeypatch):
    # These tests exercise real local metadata/rasters, not PG storage. An API
    # module's app pool must not survive into a different per-test event loop.
    for module in ("app.agent.imagery_access", "app.agent.tools.staging", "app.agent.tool_jobs"):
        monkeypatch.setattr(module + ".fetch_optional_pool", AsyncMock(return_value=None))


def image(path, descriptions, *, alpha=False):
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=len(descriptions),
                       dtype="uint16", transform=from_origin(0, 2, 1, 1)) as dst:
        dst.write(np.full((len(descriptions), 2, 2), 1000, dtype="uint16"))
        dst.colorinterp = tuple(ColorInterp.undefined for _ in descriptions)
        for index, description in enumerate(descriptions, 1):
            if description:
                dst.set_band_description(index, description)
        if alpha:
            dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
    return path


@pytest.mark.parametrize("requested", [{"red": 3, "nir": 4}, {"red": 4, "nir": 4}])
def test_known_roles_reject_wrong_or_repeated_explicit_bands(tmp_path, requested):
    path = image(tmp_path / "source.tif", ["blue", "green", "nir", "red"])
    with pytest.raises(ValueError, match="invalid_bands"):
        resolve_spectral_bands(path, requested, explicit={"red_band", "nir_band"})


def test_alpha_is_never_a_spectral_band_even_if_mislabelled_nir(tmp_path):
    path = image(tmp_path / "source.tif", ["red", "green", "blue", "nir"], alpha=True)
    with pytest.raises(ValueError, match="Alpha"):
        resolve_spectral_bands(path, {"red": 1, "nir": 4}, explicit=set())


def test_duplicate_role_descriptions_are_ambiguous_not_first_match(tmp_path):
    path = image(tmp_path / "source.tif", ["red", "red", "nir"])
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_spectral_bands(path, {"red": 1, "nir": 3}, explicit=set())


def test_swir_wavelengths_remain_distinct_in_metadata(tmp_path):
    path = image(tmp_path / "source.tif", ["nir", "SWIR1", "SWIR2"])
    assert _extract_metadata(path)["band_roles"] == {"nir": 1, "swir1": 2, "swir2": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "expected_band", "expected_mean"), [("ndmi", 5, 7/9), ("nbr", 6, 1/3)])
async def test_real_tool_chain_uses_correct_swir_wavelength(monkeypatch, tmp_path, kind, expected_band, expected_mean):
    import json, sys
    from autogen_core import CancellationToken
    from app.agent.engine.tools import RemoteSensingTool
    from app.agent.engine.turn_context import turn_scope
    from app.agent.tool_registry import TOOLS
    from app.auth import set_current_user_id, reset_current_user_id
    from app.core.settings import get_settings
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "docker" / "rs_tools"))
    from compute_spectral_index import compute

    identity = "aaaaaaaaaaaa"
    owner = "00000000-0000-4000-8000-000000000001"
    directory = tmp_path / identity
    directory.mkdir()
    with rasterio.open(directory / "working.tif", "w", driver="GTiff", width=2, height=2, count=6,
                       dtype="float32", transform=from_origin(0, 2, 1, 1)) as dst:
        for index, (role, value) in enumerate(zip(("blue", "green", "red", "nir", "swir1", "swir2"), (.1,.2,.2,.8,.1,.4)), 1):
            dst.write(np.full((2, 2), value, dtype="float32"), index)
            dst.set_band_description(index, role)
            dst.update_tags(index, REFL_QUANTITY="surface_reflectance", REFL_APPLIED="true", REFL_SOURCE="test_physical_values")
        dst.colorinterp = tuple(ColorInterp.undefined for _ in range(6))
    (directory / "metadata.json").write_text(json.dumps({"owner_user_id": owner, "bounds": [0,0,2,2]}),encoding="utf-8")
    seen = []
    async def compute_client(self, tool_name, *, source_path, output_dir, arguments):
        seen.append(arguments)
        return compute(input_path=str(source_path), output_dir=str(output_dir), **arguments)
    for key, value in {"DATABASE_ENABLED":"false", "STORAGE_BACKEND":"local", "RS_TOOLS_MCP_USE_DOCKER":"true", "IMAGERY_UPLOAD_DIR":str(tmp_path)}.items():
        monkeypatch.setenv(key,value)
    get_settings.cache_clear()
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool",compute_client)
    token = set_current_user_id(owner)
    try:
        with turn_scope() as state:
            await RemoteSensingTool(TOOLS["calculate_spectral_index"]).run_json({"imagery_id":identity,"index_type":kind},CancellationToken())
        assert seen[0]["swir_band"] == expected_band
        assert state.invocations[0].result.geospatial_result["stats"]["mean"] == pytest.approx(expected_mean)
    finally:
        reset_current_user_id(token)
        get_settings.cache_clear()


def test_stac_keeps_both_swir_assets():
    from types import SimpleNamespace as NS
    from app.agent.stac_search.sources import record_from_item, source_spec
    assets = {role:NS(href="https://example.org/"+role+".tif",extra_fields={}) for role in ("blue","green","red","nir","swir16","swir22")}
    item = NS(id="scene", properties={}, assets=assets, datetime="2024-01-01T00:00:00Z", bbox=[0,0,1,1])
    record = record_from_item(source_spec("sentinel2"),item)
    assert record.band_assets["swir1"].endswith("swir16.tif")
    assert record.band_assets["swir2"].endswith("swir22.tif")


def test_generic_legacy_swir_does_not_guess_wavelength(tmp_path):
    path=image(tmp_path / "source.tif",["blue","green","red","nir","swir"])
    with pytest.raises(ValueError,match="swir1"):
        resolve_spectral_bands(path,{"nir":4,"swir1":5},explicit=set())
    assert resolve_spectral_bands(path,{"nir":4,"swir1":5},explicit={"swir1_band"}) == {"nir":4,"swir1":5}


@pytest.mark.asyncio
async def test_real_ocr_default_call_resolves_actual_rgb(monkeypatch,tmp_path):
    import json
    from autogen_core import CancellationToken
    from app.agent.engine.tools import RemoteSensingTool
    from app.agent.engine.turn_context import turn_scope
    from app.agent.tool_registry import TOOLS
    from app.auth import set_current_user_id, reset_current_user_id
    from app.core.settings import get_settings
    owner="00000000-0000-4000-8000-000000000001"
    identity="aaaaaaaaaaaa"
    directory=tmp_path / identity
    directory.mkdir()
    image(directory / "working.tif",["blue","green","red","nir"])
    (directory / "metadata.json").write_text(json.dumps({"owner_user_id":owner,"bounds":[0,0,2,2]}),encoding="utf-8")
    seen=[]
    async def fake_client(self,tool_name,*,source_path,output_dir,arguments):
        seen.append(arguments)
        return {"full_text":"test","block_count":1,"char_count":4,"avg_confidence":.99}
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool",fake_client)
    for key,value in {"DATABASE_ENABLED":"false","STORAGE_BACKEND":"local","RS_DOC_MCP_USE_DOCKER":"true","IMAGERY_UPLOAD_DIR":str(tmp_path)}.items():
        monkeypatch.setenv(key,value)
    get_settings.cache_clear()
    token=set_current_user_id(owner)
    try:
        with turn_scope():
            await RemoteSensingTool(TOOLS["ocr_recognize"]).run_json({"imagery_id":identity},CancellationToken())
        assert {key:seen[0][key] for key in ("red_band","green_band","blue_band")} == {"red_band":3,"green_band":2,"blue_band":1}
    finally:
        reset_current_user_id(token)
        get_settings.cache_clear()


def test_custom_display_channels_do_not_claim_spectral_roles(tmp_path):
    from app.services.raster_semantics import validate_spectral_selection
    path=image(tmp_path / "source.tif",["nir","red","green"])
    validate_spectral_selection(_extract_metadata(path),{"channel_r":1,"channel_g":1,"channel_b":2})


def test_schema_omitted_or_null_defaults_do_not_create_false_duplicates():
    from app.agent.tools.spectral_index.schema import SpectralIndexArguments
    args=SpectralIndexArguments(imagery_id="aaaaaaaaaaaa",index_type="savi",red_band=4)
    assert args.model_fields_set == {"imagery_id","index_type","red_band"}
    args=SpectralIndexArguments(imagery_id="aaaaaaaaaaaa",index_type="ndmi",nir_band=5,swir1_band=None)
    assert args.swir1_band is None


@pytest.mark.asyncio
async def test_same_turn_import_drops_previous_images_band_defaults(monkeypatch,tmp_path):
    import json
    from autogen_core import CancellationToken
    from app.agent.engine.tools import RemoteSensingTool
    from app.agent.engine.turn_context import turn_scope, ToolInvocation
    from app.agent.tool_registry import TOOLS
    from app.agent.types import ToolRunResult
    from app.auth import set_current_user_id, reset_current_user_id
    from app.core.settings import get_settings
    owner="00000000-0000-4000-8000-000000000001"
    identity="bbbbbbbbbbbb"
    directory=tmp_path / identity
    directory.mkdir()
    image(directory / "working.tif",["blue","green","nir","red"])
    (directory / "metadata.json").write_text(json.dumps({"owner_user_id":owner,"bounds":[0,0,2,2]}),encoding="utf-8")
    seen=[]
    async def fake_client(self,tool_name,*,source_path,output_dir,arguments):
        seen.append(arguments)
        return {"min":.5,"max":.5,"mean":.5,"std":0,"output_png":"test.png"}
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool",fake_client)
    for key,value in {"DATABASE_ENABLED":"false","STORAGE_BACKEND":"local","RS_TOOLS_MCP_USE_DOCKER":"true","IMAGERY_UPLOAD_DIR":str(tmp_path)}.items():
        monkeypatch.setenv(key,value)
    get_settings.cache_clear()
    token=set_current_user_id(owner)
    try:
        with turn_scope(trusted_tool_arguments={"calculate_ndvi":{"imagery_id":"aaaaaaaaaaaa","red_band":3,"nir_band":4}}):
            from app.agent.engine.turn_context import current_turn_state
            state=current_turn_state()
            state.record(ToolInvocation(name="fetch_scene",arguments={},result=ToolRunResult(
                tool_context="Imported",geospatial_result={"imagery_id":identity},metadata={"band_roles":{"red":4,"nir":3}})))
            await RemoteSensingTool(TOOLS["calculate_ndvi"]).run_json({"imagery_id":"aaaaaaaaaaaa"},CancellationToken())
        assert seen[0] == {"red_band":4,"nir_band":3}
    finally:
        reset_current_user_id(token)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_real_inspect_tool_reports_qualified_swir_capabilities(monkeypatch,tmp_path):
    import json
    from autogen_core import CancellationToken
    from app.agent.engine.tools import RemoteSensingTool
    from app.agent.engine.turn_context import turn_scope
    from app.agent.tool_registry import TOOLS
    from app.auth import set_current_user_id, reset_current_user_id
    from app.core.settings import get_settings
    identity="aaaaaaaaaaaa"
    owner="00000000-0000-4000-8000-000000000001"
    directory=tmp_path / identity
    directory.mkdir()
    image(directory / "working.tif",["blue","green","red","nir","swir1","swir2"])
    (directory / "metadata.json").write_text(json.dumps({"owner_user_id":owner}),encoding="utf-8")
    async def inspect_client(self,tool_name, *, source_path,**kwargs):
        assert tool_name == "raster_inspect"
        return {"width":2,"height":2,"band_count":6}
    for key,value in {"DATABASE_ENABLED":"false","STORAGE_BACKEND":"local","RS_TOOLS_MCP_USE_DOCKER":"true","IMAGERY_UPLOAD_DIR":str(tmp_path)}.items():
        monkeypatch.setenv(key,value)
    monkeypatch.setattr("app.mcp.rs_tools_client.RSToolsMCPClient.call_tool",inspect_client)
    get_settings.cache_clear()
    token=set_current_user_id(owner)
    try:
        with turn_scope() as state:
            await RemoteSensingTool(TOOLS["raster_inspect"]).run_json({"imagery_id":identity},CancellationToken())
        result=state.invocations[0].result
        assert result.tool_result["capabilities"]["has_swir"]
        assert result.tool_result["capabilities"]["has_swir1"]
        assert result.tool_result["capabilities"]["has_swir2"]
        assert "SWIR1=True" in result.tool_context and "SWIR2=True" in result.tool_context
    finally:
        reset_current_user_id(token)
        get_settings.cache_clear()
