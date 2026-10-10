from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import numpy as np
import pytest
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_origin

from app.agent.stac_search.model import SceneRecord
from app.agent.stac_search.sources import record_from_item, source_spec, StacSearchError
from app.agent.stac_search.raster import compose_scene_tif, SceneRasterError
from app.core.settings import get_settings


def write_band(path, values, *, res=1, dtype="uint16"):
    values=np.asarray(values,dtype=dtype)
    with rasterio.open(path,"w",driver="GTiff",width=values.shape[1],height=values.shape[0],count=1,
                       dtype=dtype,crs="EPSG:4326",transform=from_origin(0,4,res,res)) as dst:
        dst.write(values,1)
    return str(path)


def scene(tmp_path, *, quality=True):
    assets={role:write_band(tmp_path / (role+".tif"),np.full((4,4),value))
            for role,value in {"blue":2000,"green":3000,"red":3000,"nir":5000}.items()}
    qa=write_band(tmp_path / "scl.tif",[[4,6],[8,9]],res=2,dtype="uint8") if quality else None
    calibrations={role:{"scale":.0001,"offset":-.1,"quantity":"surface_reflectance","source":"stac:raster:bands"} for role in assets}
    calibrations["nir"]={**calibrations["nir"],"scale":.0002,"offset":-.2}
    return SceneRecord(key="a"*12,source="sentinel2",item_id="S2_CURRENT",collection="sentinel-2-c1-l2a",
        satellite="Sentinel-2A",datetime="2024-01-01T00:00:00Z",cloud_cover=None,bbox=[0,0,4,4],
        resolution_m=1,band_assets=assets,display_name="test",band_calibration=calibrations,
        reflectance_applied_at_compose=False,quality_assets={"sentinel2_scl":qa} if qa else {})


def test_stac_keeps_per_asset_calibration_not_first_asset():
    assets={}
    for role,scale in {"blue":.0001,"green":.0001,"red":.0001,"nir":.0002}.items():
        assets[role]=NS(href="https://example.org/"+role+".tif",extra_fields={"raster:bands":[{"scale":scale,"offset":-.1}]})
    item=NS(id="test",properties={},datetime="2024-01-01",bbox=[0,0,1,1],assets=assets)
    record=record_from_item(source_spec("sentinel2"),item)
    assert record.band_calibration["nir"]["scale"] == .0002
    assert record.band_calibration["red"]["scale"] == .0001
    assert record.reflectance_scale is None
    assets["nir"].extra_fields={}
    record=record_from_item(source_spec("sentinel2"),item)
    assert "nir" not in record.band_calibration
    assert record.reflectance_scale is None


@pytest.mark.parametrize("scale,offset",[(0,0),(-1,0),(float("nan"),0),(1,float("inf")),("bad",0)])
def test_invalid_asset_calibration_is_explicit_error(scale,offset):
    item=NS(id="test",properties={},datetime="2024-01-01",bbox=[0,0,1,1],
        assets={role:NS(href="https://example.org/"+role,extra_fields={"raster:bands":[{"scale":scale,"offset":offset}]}) for role in ("blue","green","red")})
    with pytest.raises(StacSearchError,match="定标"):
        record_from_item(source_spec("sentinel2"),item)


def test_composed_per_band_calibration_matches_physical_reference(tmp_path):
    record=scene(tmp_path,quality=False)
    output=tmp_path / "composed" / "scene.tif"
    meta=compose_scene_tif(record,output)
    sys.path.insert(0,str(Path(__file__).resolve().parents[3] / "docker" / "rs_tools"))
    from compute_ndvi import compute
    stats=compute(input_path=str(output),output_dir=str(tmp_path / "out"),red_band=record.band_roles["red"],nir_band=record.band_roles["nir"])
    assert stats["mean"] == pytest.approx(.6,abs=1e-6)
    with rasterio.open(output) as src:
        assert src.read(record.band_roles["nir"])[0,0] == 5000
        assert src.tags(record.band_roles["nir"])["REFL_SCALE"] == "0.00020000000000000001"
        assert src.tags(record.band_roles["nir"])["REFL_APPLIED"] == "false"
        assert src.units[0] == "dn"
    assert meta["band_calibration"]["nir"]["source"] == "stac:raster:bands"


def test_quality_sidecar_has_identical_grid_and_nearest_labels(tmp_path):
    record=scene(tmp_path)
    output=tmp_path / "composed" / "scene.tif"
    meta=compose_scene_tif(record,output)
    with rasterio.open(output) as src, rasterio.open(output.parent / "quality.tif") as qa:
        assert (qa.width,qa.height,qa.crs,qa.transform) == (src.width,src.height,src.crs,src.transform)
        assert qa.count == 1 and qa.dtypes == ("uint8",)
        np.testing.assert_array_equal(qa.read(1),np.repeat(np.repeat([[4,6],[8,9]],2,axis=0),2,axis=1))
        assert qa.tags()["QA_ITEM_ID"] == record.item_id
        assert qa.tags()["QA_TYPE"] == "sentinel2_scl"
        assert src.count == 4
    assert meta["quality_mask"]["filename"] == "quality.tif"


def test_quality_failure_does_not_leave_reusable_scene(tmp_path):
    from dataclasses import replace
    record=replace(scene(tmp_path),quality_assets={"sentinel2_scl":str(tmp_path / "missing.tif")})
    output=tmp_path / "composed" / "scene.tif"
    with pytest.raises(SceneRasterError,match="质量"):
        compose_scene_tif(record,output)
    assert not output.exists()
    assert not (output.parent / "quality.tif.pending").exists()


def test_working_copy_preserves_calibration_mask_and_alpha_labels(tmp_path):
    from app.api.routes.imagery import _create_working_tif
    source=tmp_path / "source.tif"
    alpha=np.array([[0,0,255,255],[0,0,255,255],[255,255,0,0],[255,255,0,0]],dtype="uint8")
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(source,"w",driver="GTiff",width=4,height=4,count=4,dtype="uint8",
            crs="EPSG:4326",transform=from_origin(0,4,1,1)) as src:
        src.write(np.stack([np.zeros((4,4),dtype="uint8")]*3+[alpha]))
        src.colorinterp=(ColorInterp.red,ColorInterp.green,ColorInterp.blue,ColorInterp.alpha)
        src.scales=(.1,.2,.3,1)
        src.offsets=(-.1,-.2,-.3,0)
        src.units=("dn","dn","dn","alpha")
        src.update_tags(1,REFL_SCALE="0.1",REFL_OFFSET="-0.1",REFL_APPLIED="false",REFL_QUANTITY="surface_reflectance",REFL_SOURCE="test")
        src.write_mask(alpha)
    with rasterio.open(source) as src:
        expected_mask=src.dataset_mask(out_shape=(2,2),resampling=Resampling.nearest)
    output=tmp_path / "working.tif"
    _create_working_tif(source,output,NS(imagery_working_max_dimension=2,imagery_compression="deflate",imagery_max_band_count=64,imagery_max_working_bytes=1024**3))
    with rasterio.open(source) as src, rasterio.open(output) as dst:
        assert dst.scales == src.scales and dst.offsets == src.offsets and dst.units == src.units
        assert dst.tags(1) == src.tags(1)
        np.testing.assert_array_equal(dst.dataset_mask(),expected_mask)
        assert set(np.unique(dst.read(4))) == {0,255}
    assert not (tmp_path / "working.tif.msk").exists()


@pytest.mark.asyncio
async def test_import_quality_is_published_to_minio_and_staged(monkeypatch,tmp_path):
    from app.agent.stac_search.importer import import_scene_as_imagery
    from app.agent.tools.staging import stage_imagery, staged_imagery_dir
    from app.agent.tools.cloud_mask.runner import _quality_payload
    owner="00000000-0000-4000-8000-000000000001"
    record=scene(tmp_path)
    class Store:
        def __init__(self): self.objects={}
        async def put(self,key,path): self.objects[key]=path.read_bytes()
        async def exists(self,key): return key in self.objects
        async def get_to(self,key,path): path.write_bytes(self.objects[key])
    store=Store()
    class Acquire:
        async def __aenter__(self): return object()
        async def __aexit__(self,*args): return False
    pool=NS(acquire=lambda:Acquire())
    monkeypatch.setattr("app.services.imagery_persist.fetch_optional_pool",AsyncMock(return_value=pool))
    monkeypatch.setattr("app.services.imagery_persist.db_insert_imagery",AsyncMock())
    monkeypatch.setattr("app.services.imagery_persist.get_object_store",lambda:store)
    monkeypatch.setattr("app.agent.tools.staging.fetch_optional_pool",AsyncMock(return_value=pool))
    monkeypatch.setattr("app.agent.tools.staging.db_get_imagery",AsyncMock(return_value={"owner_user_id":owner,"storage_backend":"minio"}))
    monkeypatch.setattr("app.agent.tools.staging.db_get_user",AsyncMock(return_value={"id":owner,"is_active":True}))
    monkeypatch.setattr("app.agent.tools.staging.object_store_for",lambda backend:store)
    for key,value in {"STORAGE_BACKEND":"minio","IMAGERY_UPLOAD_DIR":str(tmp_path / "imagery"),"SCENE_CACHE_DIR":str(tmp_path / "scenes")}.items():
        monkeypatch.setenv(key,value)
    get_settings.cache_clear()
    try:
        result=await import_scene_as_imagery(record,owner)
        identity=result["imagery_id"]
        assert identity+"/quality.tif" in store.objects
        async with stage_imagery(identity, user_id=owner):
            directory=staged_imagery_dir(identity)
            payload=_quality_payload(directory / "working.tif",directory)
            assert payload == {"method":"quality","quality_type":"sentinel2_scl","quality_path":"/data/quality.tif"}
            sys.path.insert(0,str(Path(__file__).resolve().parents[3] / "docker" / "rs_tools"))
            from compute_cloud_mask import compute
            stats=compute(input_path=str(directory / "working.tif"), quality_path=str(directory / "quality.tif"),
                quality_type=payload["quality_type"], output_dir=str(tmp_path / "qa_outputs"))
            assert stats["method"] == "quality_mask"
            assert stats["quality_type"] == "sentinel2_scl"
            assert stats["cloud_pct"] == 50 and stats["clear_pct"] == 50
            for key in ("shadow_pct","unknown_pct","snow_pct","terrain_shadow_pct","nodata_pct"):
                assert stats[key] == 0
            assert stats["total_pixels"] == 16 and stats["valid_pixels"] == 16
        assert not directory.exists()
        reused=await import_scene_as_imagery(record,owner)
        assert reused["imagery_id"] == identity and reused["reused"]
    finally:
        get_settings.cache_clear()


def test_landsat_quality_zero_remains_valid_when_no_nodata(tmp_path):
    from dataclasses import replace
    qa=write_band(tmp_path / "qa_zero.tif",np.zeros((4,4)),dtype="uint16")
    record=replace(scene(tmp_path,quality=False),source="landsat",satellite="Landsat 9",
        collection="landsat-c2-l2",quality_assets={"landsat_c2_qa_pixel":qa})
    output=tmp_path / "composed" / "scene.tif"
    compose_scene_tif(record,output)
    with rasterio.open(output.parent / "quality.tif") as quality:
        assert np.all(quality.read_masks(1) == 255)
        assert np.all(quality.read(1) == 0)
