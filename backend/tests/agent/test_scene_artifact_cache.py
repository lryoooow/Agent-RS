from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.agent.stac_search.model import SceneRecord
from app.agent.stac_search.cache import put_scenes, clear_all
from app.core.settings import get_settings


@pytest.fixture
def cached_scene(monkeypatch,tmp_path):
    assets={}
    for role in ("red","green","blue","nir"):
        path=tmp_path / (role+".tif")
        with rasterio.open(path,"w",driver="GTiff",count=1,width=4,height=4,dtype="uint16",
                crs="EPSG:4326",transform=from_origin(0,4,1,1)) as dst:
            dst.write(np.arange(16,dtype="uint16").reshape(4,4)+1000,1)
        assets[role]=str(path)
    record=SceneRecord(key="a"*12,source="sentinel2",item_id="CACHE_TEST",collection="sentinel-2-c1-l2a",
        satellite="Sentinel-2A",datetime="2024-01-01",cloud_cover=None,bbox=[0,0,4,4],resolution_m=1,
        band_assets=assets,display_name="test",reflectance_scale=.0001,reflectance_offset=0,reflectance_applied_at_compose=False)
    for key,value in {"SCENE_CACHE_DIR":str(tmp_path / "scenes"),"IMAGERY_UPLOAD_DIR":str(tmp_path / "imagery"),
                      "STORAGE_BACKEND":"local","DATABASE_ENABLED":"false"}.items():
        monkeypatch.setenv(key,value)
    get_settings.cache_clear()
    clear_all()
    yield record
    clear_all()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_download_different_bbox_does_not_reuse_first_roi(monkeypatch,cached_scene):
    from app.api.routes.scenes import scene_download
    import app.api.routes.scenes as routes
    owner="00000000-0000-4000-8000-000000000001"
    put_scenes(owner,[cached_scene])
    monkeypatch.setattr(routes,"_HEAVY_WINDOWS",{})
    first=await scene_download(cached_scene.key,bbox=[0,0,2,4],user_id=owner)
    second=await scene_download(cached_scene.key,bbox=[2,0,4,4],user_id=owner)
    with rasterio.open(first.path) as a, rasterio.open(second.path) as b:
        assert list(a.bounds) == [0,0,2,4]
        assert list(b.bounds) == [2,0,4,4]
        assert a.transform != b.transform


@pytest.mark.parametrize("bbox",[[0,0,0,1],[2,0,1,1],[0,1,1,0],[181,0,182,1],[0,-91,1,1],[float("nan"),0,1,1],[0,0,float("inf"),1],[True,0,1,1],[0,0,1]])
def test_invalid_bbox_rejected_before_work(bbox):
    from app.agent.stac_search.composition_cache import normalize_bbox
    with pytest.raises(ValueError): normalize_bbox(bbox)


def test_identity_is_normalized_and_includes_processing_contract(cached_scene):
    from dataclasses import replace
    from app.agent.stac_search.composition_cache import composition_identity
    first,spec=composition_identity(cached_scene,"alice",[0,0,2,4])
    assert first == composition_identity(cached_scene,"alice",[0.0,-0.0,2.0,4.0])[0]
    assert first != composition_identity(cached_scene,"bob",[0,0,2,4])[0]
    assert first != composition_identity(cached_scene,"alice",None)[0]
    assert first != composition_identity(replace(cached_scene,reflectance_offset=-.1),"alice",[0,0,2,4])[0]
    assert first != composition_identity(replace(cached_scene,band_assets={**cached_scene.band_assets,"swir1":"new.tif"}),"alice",[0,0,2,4])[0]
    assert spec["target_crs"] == "native:red_asset" and spec["version"] >= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt",range(10))
async def test_parallel_same_roi_compiles_once_and_other_roi_and_user_isolated(monkeypatch,cached_scene,attempt):
    import asyncio
    import app.agent.stac_search.composition_cache as cache
    original=cache.compose_scene_tif
    calls=[]
    def spy(record,path,**kwargs):
        calls.append((str(path),kwargs["bbox"]))
        return original(record,path,**kwargs)
    monkeypatch.setattr(cache,"compose_scene_tif",spy)
    results=await asyncio.gather(*(cache.get_composed_scene(cached_scene,"alice",[0,0,2,4]) for _ in range(3)))
    assert len(calls) == 1 and len({str(result[0]) for result in results}) == 1
    others=await asyncio.gather(cache.get_composed_scene(cached_scene,"alice",[2,0,4,4]),cache.get_composed_scene(cached_scene,"bob",[0,0,2,4]))
    assert len(calls) == 3
    assert len({str(result[0]) for result in results+others}) == 3


@pytest.mark.asyncio
async def test_download_and_import_share_exact_roi_and_full_never_uses_crop(monkeypatch,cached_scene):
    from app.api.routes.scenes import scene_download
    import app.api.routes.scenes as routes
    from app.agent.stac_search.importer import import_scene_as_imagery
    from app.agent.stac_search.composition_cache import get_composed_scene
    from app.core.paths import imagery_root
    owner="00000000-0000-4000-8000-000000000001"
    put_scenes(owner,[cached_scene])
    monkeypatch.setattr(routes,"_HEAVY_WINDOWS",{})
    bbox=[0,0,2,4]
    response=await scene_download(cached_scene.key,bbox=bbox,user_id=owner)
    imported=await import_scene_as_imagery(cached_scene,owner,bbox=[0.0,0.0,2.0,4.0])
    copied=imagery_root() / imported["imagery_id"] / "source.tif"
    assert copied.read_bytes() == Path(response.path).read_bytes()
    again=await import_scene_as_imagery(cached_scene,owner,bbox=bbox)
    assert again["imagery_id"] == imported["imagery_id"]
    full=await import_scene_as_imagery(cached_scene,owner)
    assert full["imagery_id"] != imported["imagery_id"]
    with rasterio.open(imagery_root() / full["imagery_id"] / "source.tif") as src:
        assert list(src.bounds) == [0,0,4,4]
    meta=__import__("json").loads(copied.with_name("metadata.json").read_text(encoding="utf-8"))
    assert meta["requested_bbox"] == [0,0,2,4]


@pytest.mark.asyncio
async def test_truncated_cache_rebuilt_without_touching_registered_image(cached_scene):
    from app.agent.stac_search.composition_cache import get_composed_scene
    from app.agent.stac_search.importer import import_scene_as_imagery
    from app.core.paths import imagery_root
    owner="alice"
    path,_,_=await get_composed_scene(cached_scene,owner)
    imported=await import_scene_as_imagery(cached_scene,owner)
    original=imagery_root() / imported["imagery_id"] / "source.tif"
    saved=original.read_bytes()
    path.write_bytes(b"partial")
    repaired,_,_=await get_composed_scene(cached_scene,owner)
    with rasterio.open(repaired) as src: assert src.width == 4
    assert original.read_bytes() == saved
    assert (await import_scene_as_imagery(cached_scene,owner))["imagery_id"] == imported["imagery_id"]


@pytest.mark.asyncio
async def test_failed_half_write_is_never_a_valid_cache(monkeypatch,cached_scene):
    import app.agent.stac_search.composition_cache as cache
    from app.agent.stac_search.raster import SceneRasterError
    original=cache.compose_scene_tif
    def broken(record,path,**kwargs):
        path.write_bytes(b"partial")
        raise SceneRasterError("synthetic failed source")
    monkeypatch.setattr(cache,"compose_scene_tif",broken)
    with pytest.raises(SceneRasterError): await cache.get_composed_scene(cached_scene,"alice")
    directory=cache.composition_directory(cached_scene,"alice")
    assert not directory.exists()
    assert not list(directory.parent.glob(".building-*"))
    monkeypatch.setattr(cache,"compose_scene_tif",original)
    path,_,_=await cache.get_composed_scene(cached_scene,"alice")
    assert path.is_file() and (path.parent / "manifest.json").is_file()


def test_os_file_lock_excludes_other_process_and_releases(tmp_path):
    import os, subprocess, sys
    from app.agent.stac_search.composition_cache import file_lock
    lock=tmp_path / "process.lock"
    script="from pathlib import Path; import sys; from app.agent.stac_search.composition_cache import file_lock; from app.agent.stac_search.raster import SceneRasterError\ntry:\n with file_lock(Path(sys.argv[1]),timeout=.1): print('ENTERED')\nexcept SceneRasterError: print('BLOCKED')"
    env={**os.environ,"PYTHONPATH":str(Path(__file__).resolve().parents[2])}
    def child():
        return subprocess.check_output([sys.executable,"-B","-c",script,str(lock)],env=env,timeout=10,text=True).strip()
    with file_lock(lock): assert child() == "BLOCKED"
    assert child() == "ENTERED"


@pytest.mark.asyncio
async def test_cap_only_evicts_complete_old_bundles_and_keeps_registered_images(cached_scene):
    import os,time
    from app.agent.stac_search.composition_cache import get_composed_scene,prune_compositions,user_cache_root
    from app.agent.stac_search.importer import import_scene_as_imagery
    from app.core.paths import imagery_root
    a,_,_=await get_composed_scene(cached_scene,"alice",[0,0,2,4])
    imported=await import_scene_as_imagery(cached_scene,"alice",bbox=[0,0,2,4])
    b,_,_=await get_composed_scene(cached_scene,"alice",[2,0,4,4])
    os.utime(a.parent / "manifest.json",(time.time()-3600,)*2)
    prune_compositions("alice",protected=b.parent,max_files=2)
    assert not a.parent.exists() and b.is_file()
    assert (imagery_root() / imported["imagery_id"] / "source.tif").is_file()
    assert len(list((user_cache_root("alice") / ".locks").glob("*"))) <= 512


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel",[False,True])
async def test_response_read_lease_survives_pruning_before_open_and_during_transfer(monkeypatch,cached_scene,cancel):
    import asyncio
    from app.api.routes.scenes import scene_download
    import app.api.routes.scenes as routes
    from app.agent.stac_search.composition_cache import prune_compositions
    owner="alice"
    put_scenes(owner,[cached_scene])
    monkeypatch.setattr(routes,"_HEAVY_WINDOWS",{})
    response=await scene_download(cached_scene.key,user_id=owner)
    path=Path(response.path)
    prune_compositions(owner,max_files=0)
    assert path.is_file()  # FileResponse has not even opened the TIFF yet.
    entered,release=asyncio.Event(),asyncio.Event()
    bodies=[]
    async def send(message):
        if message["type"] == "http.response.body":
            entered.set()
            await release.wait()
            bodies.append(message.get("body",b""))
    async def receive(): return {"type":"http.disconnect"}
    task=asyncio.create_task(response({"type":"http","method":"GET","headers":[],"extensions":{}},receive,send))
    await asyncio.wait_for(entered.wait(),2)
    prune_compositions(owner,max_files=0)
    assert path.is_file()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    else:
        release.set()
        await task
        assert b"".join(bodies)
    assert response.lease.fd.closed
    prune_compositions(owner,max_files=0)
    assert not path.parent.exists()


def test_signed_url_tokens_do_not_change_identity_or_enter_manifest(cached_scene):
    from dataclasses import replace
    from app.agent.stac_search.composition_cache import composition_identity
    first=replace(cached_scene,band_assets={"red":"https://user:private-password@example.org/a.tif?sv=one&se=now&sig=SECRET_A&versionId=v1"})
    second=replace(cached_scene,band_assets={"red":"https://example.org/a.tif?versionId=v1&se=later&sig=SECRET_B&sv=two"})
    identity,spec=composition_identity(first,"alice")
    assert identity == composition_identity(second,"alice")[0]
    text=__import__("json").dumps(spec)
    assert "SECRET_" not in text and "private-password" not in text and "example.org" not in text


@pytest.mark.asyncio
async def test_failed_cache_marker_never_deletes_published_imagery(monkeypatch,cached_scene):
    from app.agent.stac_search.importer import import_scene_as_imagery
    from app.core.paths import imagery_root
    def broken(*args): raise OSError("synthetic marker failure")
    monkeypatch.setattr("app.agent.stac_search.importer._write_import_marker",broken)
    result=await import_scene_as_imagery(cached_scene,"alice")
    source=imagery_root() / result["imagery_id"] / "source.tif"
    assert source.is_file()
    reused=await import_scene_as_imagery(cached_scene,"alice")
    assert reused["imagery_id"] == result["imagery_id"]


@pytest.mark.asyncio
async def test_parallel_imports_use_one_id_per_user_and_roi(cached_scene):
    import asyncio,json
    from app.agent.stac_search.importer import import_scene_as_imagery
    from app.core.paths import imagery_root
    values=await asyncio.gather(*(import_scene_as_imagery(cached_scene,"alice",bbox=[0,0,2,4]) for _ in range(3)),
        import_scene_as_imagery(cached_scene,"alice",bbox=[2,0,4,4]),
        import_scene_as_imagery(cached_scene,"bob",bbox=[0,0,2,4]))
    assert len({v["imagery_id"] for v in values[:3]}) == 1
    assert len({v["imagery_id"] for v in values}) == 3
    for result,owner in zip(values,("alice","alice","alice","alice","bob")):
        metadata=json.loads((imagery_root() / result["imagery_id"] / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["owner_user_id"] == owner


def test_two_real_processes_import_same_identity_once(cached_scene):
    import os,subprocess,sys,json
    from dataclasses import asdict
    from app.core.paths import imagery_root
    script="import asyncio,json,sys; from app.agent.stac_search.model import SceneRecord; from app.agent.stac_search.importer import import_scene_as_imagery; r=asyncio.run(import_scene_as_imagery(SceneRecord(**json.loads(sys.argv[1])),'alice',bbox=[0,0,2,4])); print(r['imagery_id'])"
    env={**os.environ,"PYTHONPATH":str(Path(__file__).resolve().parents[2])}
    args=[sys.executable,"-B","-c",script,json.dumps(asdict(cached_scene))]
    processes=[subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    try:
        results=[process.communicate(timeout=15) for process in processes]
        assert all(process.returncode == 0 for process in processes), results
        identities=[stdout.strip() for stdout,stderr in results]
        assert identities[0] == identities[1]
        directories=list(imagery_root().iterdir())
        assert len(directories) == 1 and directories[0].name == identities[0]
    finally:
        for process in processes:
            if process.poll() is None: process.kill(); process.communicate()


def test_http_invalid_bbox_returns_controlled_error_before_work(monkeypatch,cached_scene):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import require_authenticated_user
    import app.api.routes.scenes as routes
    owner="alice"
    put_scenes(owner,[cached_scene])
    monkeypatch.setattr(routes,"_HEAVY_WINDOWS",{})
    monkeypatch.setitem(app.dependency_overrides,require_authenticated_user,lambda:owner)
    with TestClient(app) as client:
        assert client.get(f"/api/scenes/{cached_scene.key}/download",params=[("bbox","nan"),("bbox",0),("bbox",1),("bbox",1)]).status_code == 400
        assert client.post(f"/api/scenes/{cached_scene.key}/import",json={"bbox":[0,0,0,1]}).status_code == 422
        assert client.post(f"/api/scenes/{cached_scene.key}/import",content='{"bbox":[NaN,0,1,1]}',headers={"content-type":"application/json"}).status_code == 422
    assert not routes._HEAVY_WINDOWS


@pytest.mark.asyncio
async def test_preview_partial_write_is_private_and_concurrent_request_waits(monkeypatch,cached_scene):
    import asyncio, threading
    from PIL import Image
    import app.api.routes.scenes as routes
    owner="alice"
    put_scenes(owner,[cached_scene])
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def slow_preview(record,path):
        calls.append(path)
        if path.exists(): return path
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b"partial PNG")
        entered.set()
        assert release.wait(2)
        Image.new("RGB",(4,4)).save(path)
        return path
    monkeypatch.setattr(routes,"render_scene_preview",slow_preview)
    first=asyncio.create_task(routes.scene_preview(cached_scene.key,user_id=owner))
    assert await asyncio.to_thread(entered.wait,2)
    second=asyncio.create_task(routes.scene_preview(cached_scene.key,user_id=owner))
    try:
        await asyncio.sleep(.05)
        assert not second.done(), "the second response exposed a partial PNG"
    finally:
        release.set()
        responses=await asyncio.gather(first,second)
        for response in responses:
            if hasattr(response,"lease"): await response.lease.release()
    assert len(calls) == 1
    assert Path(responses[0].path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel",[False,True])
async def test_preview_read_lease_protects_png_until_response_finishes(monkeypatch,cached_scene,cancel):
    import asyncio
    import app.api.routes.scenes as routes
    from app.agent.stac_search.composition_cache import prune_compositions
    owner="alice"
    put_scenes(owner,[cached_scene])
    response=await routes.scene_preview(cached_scene.key,user_id=owner)
    path=Path(response.path)
    prune_compositions(owner,max_files=0)
    assert path.is_file()
    entered,release=asyncio.Event(),asyncio.Event()
    bodies=[]
    async def send(message):
        if message["type"] == "http.response.body":
            entered.set()
            await release.wait()
            bodies.append(message.get("body",b""))
    async def receive(): return {"type":"http.disconnect"}
    task=asyncio.create_task(response({"type":"http","method":"GET","headers":[],"extensions":{}},receive,send))
    await asyncio.wait_for(entered.wait(),2)
    prune_compositions(owner,max_files=0)
    assert path.is_file()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    else:
        release.set()
        await task
        assert b"".join(bodies)[:8] == b"\x89PNG\r\n\x1a\n"
    assert response.lease.fd.closed
    prune_compositions(owner,max_files=0)
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_png_and_tiff_share_file_cap_and_bad_png_is_rebuilt(monkeypatch,cached_scene):
    import json,os,time
    import app.api.routes.scenes as routes
    from app.agent.stac_search.composition_cache import get_composed_scene,prune_compositions,user_cache_root
    owner="alice"
    put_scenes(owner,[cached_scene])
    preview=await routes.scene_preview(cached_scene.key,user_id=owner)
    path=Path(preview.path)
    original=path.read_bytes()
    await preview.lease.release()
    path.write_bytes(b"partial PNG")
    repaired=await routes.scene_preview(cached_scene.key,user_id=owner)
    assert Path(repaired.path).read_bytes() == original
    await repaired.lease.release()
    tif,_,_=await get_composed_scene(cached_scene,owner)
    os.utime(path.parent / "manifest.json",(time.time()-3600,)*2)
    prune_compositions(owner,protected=tif.parent,max_files=2)
    assert not path.parent.exists() and tif.is_file()
    assert len(list(user_cache_root(owner).rglob("preview.png"))) == 0


@pytest.mark.asyncio
async def test_failed_or_cancelled_preview_never_publishes_partial_file(monkeypatch,cached_scene):
    import asyncio,threading
    import app.api.routes.scenes as routes
    from app.agent.stac_search.composition_cache import user_cache_root
    from app.agent.stac_search.raster import SceneRasterError
    owner="alice"
    put_scenes(owner,[cached_scene])
    def broken(record,path):
        path.write_bytes(b"partial PNG")
        raise SceneRasterError("synthetic preview failure")
    monkeypatch.setattr(routes,"render_scene_preview",broken)
    with pytest.raises(Exception) as exc:
        await routes.scene_preview(cached_scene.key,user_id=owner)
    assert getattr(exc.value,"status_code",None) == 502
    root=user_cache_root(owner)
    assert not list(root.rglob("preview.png")) and not list(root.rglob("manifest.json"))
    entered,release,finished=threading.Event(),threading.Event(),threading.Event()
    def slow(record,path):
        try:
            path.write_bytes(b"partial PNG")
            entered.set()
            assert release.wait(2)
        finally:
            finished.set()
    monkeypatch.setattr(routes,"render_scene_preview",slow)
    request=asyncio.create_task(routes.scene_preview(cached_scene.key,user_id=owner))
    assert await asyncio.to_thread(entered.wait,2)
    request.cancel()
    with pytest.raises(asyncio.CancelledError): await request
    release.set()
    assert await asyncio.to_thread(finished.wait,2)
    for _ in range(100):
        if not list(root.rglob(".building-*")): break
        await asyncio.sleep(.01)
    assert not list(root.rglob(".building-*")) and not list(root.rglob("preview.png"))


def test_invalid_asset_url_is_controlled_error(cached_scene):
    from dataclasses import replace
    from app.agent.stac_search.composition_cache import composition_identity
    from app.agent.stac_search.raster import SceneRasterError
    record=replace(cached_scene,band_assets={"red":"https://example.org:not-a-port/file.tif"})
    with pytest.raises(SceneRasterError,match="地址非法"):
        composition_identity(record,"alice")


@pytest.mark.asyncio
@pytest.mark.parametrize("step",["preview","metadata","grid"])
async def test_cancelled_import_waits_for_owned_file_worker_before_cleanup(monkeypatch,cached_scene,step):
    import asyncio,threading
    from unittest.mock import AsyncMock
    import app.agent.stac_search.importer as importer
    from app.core.paths import imagery_root
    entered,release,finished=threading.Event(),threading.Event(),threading.Event()
    paths=[]
    if step == "preview":
        target="app.services.raster_preview.generate_preview"
        def original(*args): return None
    elif step == "metadata":
        target="app.agent.stac_search.importer._extract_metadata"
        original=importer._extract_metadata
    else:
        from app.services.raster_semantics import grid_context
        target="app.services.raster_semantics.grid_context"
        original=grid_context
    def slow(*args):
        path=Path(args[0])
        paths.append(path)
        entered.set()
        try:
            assert release.wait(2)
            assert path.exists(), "the input was deleted while its worker was still using it"
            return original(*args)
        finally:
            finished.set()
    publish=AsyncMock()
    monkeypatch.setattr(target,slow)
    monkeypatch.setattr(importer,"_persist_imagery_record",publish)
    task=asyncio.create_task(importer.import_scene_as_imagery(cached_scene,"alice"))
    assert await asyncio.to_thread(entered.wait,2)
    try:
        task.cancel()
        await asyncio.sleep(.02)
        task.cancel()  # Repeated disconnect/cancel must not bypass the file lifetime.
        await asyncio.sleep(.02)
        assert not task.done(), "cancel returned before the owned file worker settled"
        assert paths[0].exists()
    finally:
        release.set()
        results=await asyncio.gather(task,return_exceptions=True)
        assert await asyncio.to_thread(finished.wait,2)
    assert isinstance(results[0],asyncio.CancelledError)
    assert not list(imagery_root().iterdir())
    publish.assert_not_awaited()


@pytest.mark.parametrize("kind",["compositions","previews"])
def test_abandoned_build_removed_only_after_its_process_releases_lock(cached_scene,kind):
    import os,subprocess,sys,time
    from uuid import uuid4
    from app.agent.stac_search.composition_cache import composition_identity,composition_lock_path,prune_compositions,user_cache_root
    identity,_=composition_identity(cached_scene,"alice")
    root=user_cache_root("alice")
    pending=root / cached_scene.key / kind / (".building-"+identity+"-"+uuid4().hex)
    ready=root / "test-worker-ready"
    lock=composition_lock_path("alice",identity)
    script="from pathlib import Path; import sys,time; from app.agent.stac_search.composition_cache import file_lock\nwith file_lock(Path(sys.argv[1])):\n p=Path(sys.argv[2]); p.mkdir(parents=True); (p/'partial.tif').write_bytes(b'partial'); Path(sys.argv[3]).touch(); time.sleep(30)"
    env={**os.environ,"PYTHONPATH":str(Path(__file__).resolve().parents[2])}
    process=subprocess.Popen([sys.executable,"-B","-c",script,str(lock),str(pending),str(ready)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline: time.sleep(.01)
        assert ready.exists(), process.communicate(timeout=1)
        prune_compositions("alice",max_files=0)
        assert pending.exists()  # Active native worker owns the exclusive process lock.
        process.kill()
        process.communicate(timeout=5)
        prune_compositions("alice",max_files=0)
        assert not pending.exists()
    finally:
        if process.poll() is None: process.kill(); process.communicate(timeout=5)
        ready.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_import_random_id_collision_never_overwrites_or_deletes_existing_image(monkeypatch,cached_scene):
    import json
    from app.agent.stac_search.importer import import_scene_as_imagery,SceneImportError
    from app.core.paths import imagery_root
    existing=imagery_root(create=True) / ("b"*12)
    existing.mkdir()
    source=existing / "source.tif"
    source.write_bytes(b"existing user source must remain")
    meta=existing / "metadata.json"
    meta.write_text(json.dumps({"owner_user_id":"bob"}),encoding="utf-8")
    monkeypatch.setattr("app.agent.stac_search.importer.secrets.token_hex",lambda _:"b"*12)
    with pytest.raises(SceneImportError): await import_scene_as_imagery(cached_scene,"alice")
    assert source.read_bytes() == b"existing user source must remain"
    assert json.loads(meta.read_text(encoding="utf-8"))["owner_user_id"] == "bob"
