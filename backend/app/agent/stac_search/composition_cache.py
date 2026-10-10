"""Complete, immutable scene/QA bundles shared by download and import."""
from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from uuid import uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.agent.stac_search.model import SceneRecord
from app.agent.stac_search.raster import SceneRasterError, compose_scene_tif, render_scene_preview
from app.core.paths import scenes_root
from app.core.settings import get_settings

COMPOSITION_VERSION = 3
LOCK_WAIT_SECONDS = 30.0


def normalize_bbox(bbox):
    if bbox is None:
        return None
    if not isinstance(bbox,(list,tuple)) or len(bbox) != 4 or any(isinstance(x,bool) for x in bbox):
        raise ValueError("bbox必须为[w,s,e,n]四个有限数字。")
    try:
        values=[float(x) for x in bbox]
    except (TypeError,ValueError) as exc:
        raise ValueError("bbox必须为四个有限数字。") from exc
    if not all(math.isfinite(x) for x in values):
        raise ValueError("bbox不能包含NaN或Inf。")
    w,s,e,n=values
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("bbox经纬度超出范围、倒置或面积为零。")
    return [0.0 if x == 0 else x for x in values]


def user_cache_root(user_id: str) -> Path:
    root=scenes_root(create=True).resolve()
    if not user_id or user_id in {".",".."} or any(c in user_id for c in "/\\"):
        raise SceneRasterError("无效场景缓存属主。")
    target=(root / user_id).resolve()
    if not target.is_relative_to(root):
        raise SceneRasterError("场景缓存路径越界。")
    target.mkdir(exist_ok=True)
    return target.resolve()


def _asset_identity(href: str) -> str:
    try:
        parts=urlsplit(href)
        port=parts.port
    except ValueError as exc:
        raise SceneRasterError("场景资产地址非法。") from exc
    if parts.scheme in {"http", "https"}:
        secret_keys={"sig","token","access_token","key","api_key","st","se","sp","sv","sr","spr","sip","skoid","sktid","skt","ske","sks","skv"}
        query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True)
               if k.lower() not in secret_keys and not k.lower().startswith(("x-amz-","x-goog-"))]
        host=parts.hostname or ""
        if port: host += f":{port}"
        href=urlunsplit((parts.scheme,host,parts.path,urlencode(sorted(query)),""))
    return hashlib.sha256(href.encode("utf-8")).hexdigest()


def composition_identity(record: SceneRecord,user_id: str, bbox=None) -> tuple[str,dict]:
    if not re.fullmatch(r"[a-f0-9]{12}",record.key):
        raise SceneRasterError("无效场景缓存标识。")
    user_cache_root(user_id)
    spec={"version":COMPOSITION_VERSION,"user_id":user_id,"scene_key":record.key,
        "source":record.source,"collection":record.collection,"item_id":record.item_id,
        "satellite":record.satellite,"acquired_at":record.datetime,"bbox":normalize_bbox(bbox),
        "target_crs":"native:red_asset","native_resolution_m":record.resolution_m,
        "max_dimension":get_settings().agent_scene_window_max_pixels,
        "band_assets":{role:_asset_identity(href) for role,href in record.band_assets.items()},"band_order":sorted(record.band_assets),
        "band_calibration":record.band_calibration,
        "legacy_scale":record.reflectance_scale,"legacy_offset":record.reflectance_offset,
        "reflectance_applied":record.reflectance_applied_at_compose,"quality_assets":{role:_asset_identity(href) for role,href in record.quality_assets.items()}}
    try:
        data=json.dumps(spec,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
    except (ValueError,TypeError) as exc:
        raise SceneRasterError("场景合成元数据非法。") from exc
    return hashlib.sha256(data).hexdigest(),spec


def composition_directory(record,user_id: str,bbox=None) -> Path:
    identity,_=composition_identity(record,user_id,bbox)
    root=user_cache_root(user_id)
    directory=root / record.key / "compositions" / identity
    if not directory.resolve().is_relative_to(root):
        raise SceneRasterError("场景缓存路径越界。")
    return directory


def composition_lock_path(user_id: str, identity: str, *, importing=False) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise SceneRasterError("无效合成身份。")
    root=user_cache_root(user_id)
    # Fixed stripes bound lock-file count; collisions serialize safely, they never share cached data.
    kind="import" if importing else "compose"
    lock_root=root / ".locks"
    if not lock_root.resolve().is_relative_to(root):
        raise SceneRasterError("场景缓存锁路径越界。")
    lock_root.mkdir(exist_ok=True)
    path=lock_root / f"{kind}-{int(identity[:8],16) % 256:03d}.lock"
    if path.is_symlink() or not path.parent.resolve().is_relative_to(root):
        raise SceneRasterError("场景缓存锁路径越界。")
    return path


def _windows_lock(fd, *, unlock=False, shared=False):
    import ctypes
    from ctypes import wintypes
    import msvcrt
    class Overlapped(ctypes.Structure):
        _fields_=[("Internal",ctypes.c_size_t),("InternalHigh",ctypes.c_size_t),
                  ("Offset",wintypes.DWORD),("OffsetHigh",wintypes.DWORD),("hEvent",wintypes.HANDLE)]
    api=ctypes.WinDLL("kernel32",use_last_error=True)
    record=Overlapped()
    handle=msvcrt.get_osfhandle(fd.fileno())
    if unlock:
        call=api.UnlockFileEx
        call.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(Overlapped)]
        call.restype=wintypes.BOOL
        ok=call(handle,0,1,0,ctypes.byref(record))
    else:
        call=api.LockFileEx
        call.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(Overlapped)]
        call.restype=wintypes.BOOL
        ok=call(handle,1 | (0 if shared else 2),0,1,0,ctypes.byref(record))
    if not ok:
        error=ctypes.get_last_error()
        if error in {32,33}: raise OSError(errno.EACCES,"cache lock is held")
        raise ctypes.WinError(error)


def _lock_fd(fd, *, shared=False):
    if os.name == "nt":
        _windows_lock(fd,shared=shared)
    else:
        import fcntl
        fcntl.flock(fd.fileno(),(fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)


def _unlock_fd(fd):
    if fd.closed:
        return
    try:
        if os.name == "nt":
            _windows_lock(fd,unlock=True)
        else:
            import fcntl
            fcntl.flock(fd.fileno(),fcntl.LOCK_UN)
    finally:
        fd.close()


def _open_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    # Both OS APIs allow locking a range past EOF. Never initialize byte 0 before
    # locking: concurrent Windows opens can lock it while another writer flushes.
    return path.open("a+b")


@contextmanager
def file_lock(path: Path, *, timeout=LOCK_WAIT_SECONDS,cancel=None,shared=False):
    fd=_open_lock(path)
    start=time.monotonic()
    acquired=False
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise SceneRasterError("场景合成已取消。")
            try:
                _lock_fd(fd,shared=shared)
                acquired=True
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES,errno.EAGAIN,errno.EDEADLK}:
                    raise
                if time.monotonic()-start >= timeout:
                    raise SceneRasterError("同一场景范围的处理仍在进行，请稍后查询任务状态。") from None
                time.sleep(.025)
        yield fd
    finally:
        if acquired:
            _unlock_fd(fd)
        else:
            fd.close()


@asynccontextmanager
async def async_file_lock(path: Path, *, timeout=LOCK_WAIT_SECONDS,shared=False):
    fd=_open_lock(path)
    start=time.monotonic()
    acquired=False
    try:
        while True:
            try:
                _lock_fd(fd,shared=shared)
                acquired=True
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES,errno.EAGAIN,errno.EDEADLK}:
                    raise
                if time.monotonic()-start >= timeout:
                    raise SceneRasterError("同一场景范围的导入仍在进行，请稍后查询任务状态。") from None
                await asyncio.sleep(.025)
        yield fd
    finally:
        if acquired:
            _unlock_fd(fd)
        else:
            fd.close()


def _digest(path):
    value=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            value.update(block)
    return value.hexdigest()


def _remove_cache_dir(path,root):
    resolved=path.resolve()
    if resolved == root.resolve() or not resolved.is_relative_to(root.resolve()) or path.is_symlink():
        raise SceneRasterError("拒绝清理缓存根目录之外的路径。")
    if path.exists():
        shutil.rmtree(path)


def _complete_bundle(path,identity,spec, *, verify_hash=True):
    import rasterio
    try:
        manifest_path = path / "manifest.json"
        if manifest_path.is_symlink(): return None
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete" or manifest.get("identity") != identity or manifest.get("spec") != spec:
            return None
        expected={"scene.tif","quality.tif"} if spec["quality_assets"] else {"scene.tif"}
        if set(manifest["files"]) != expected:
            return None
        for name,proof in manifest["files"].items():
            file=path / name
            if file.is_symlink() or not file.is_file() or file.stat().st_size != proof["size"] or (verify_hash and _digest(file) != proof["sha256"]):
                return None
        with rasterio.open(path / "scene.tif") as src:
            if src.count != len(spec["band_order"]) or list(src.descriptions) != spec["band_order"] or not src.crs:
                return None
            if spec["quality_assets"]:
                with rasterio.open(path / "quality.tif") as qa:
                    if (qa.width,qa.height,qa.crs,qa.transform) != (src.width,src.height,src.crs,src.transform):
                        return None
        (path / "manifest.json").touch()
        return manifest["metadata"]
    except (OSError,ValueError,KeyError,TypeError,rasterio.errors.RasterioError):
        return None


def _get_composition(record,user_id,bbox,cancel):
    identity,spec=composition_identity(record,user_id,bbox)
    root=user_cache_root(user_id)
    directory=composition_directory(record,user_id,bbox)
    lock=composition_lock_path(user_id,identity)
    with file_lock(lock,cancel=cancel,shared=True):
        metadata=_complete_bundle(directory,identity,spec)
        if metadata is not None:
            return directory / "scene.tif",metadata,identity
    with file_lock(lock,cancel=cancel):
        metadata=_complete_bundle(directory,identity,spec)
        if metadata is not None:
            return directory / "scene.tif",metadata,identity
        if directory.exists():
            _remove_cache_dir(directory,root)  # Only reconstructible cache; registered imagery is elsewhere.
        pending=directory.parent / (".building-"+identity+"-"+uuid4().hex)
        pending.mkdir(parents=True)
        try:
            metadata=compose_scene_tif(record,pending / "scene.tif",bbox=spec["bbox"],cancellation_event=cancel)
            if cancel.is_set():
                raise SceneRasterError("场景合成已取消。")
            files={name:{"size":(pending / name).stat().st_size,"sha256":_digest(pending / name)}
                   for name in ("scene.tif","quality.tif") if (pending / name).is_file()}
            metadata={**metadata,"composition_version":COMPOSITION_VERSION,"composition_identity":identity,"requested_bbox":spec["bbox"]}
            manifest={"status":"complete","identity":identity,"spec":spec,"files":files,"metadata":metadata}
            (pending / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,allow_nan=False),encoding="utf-8")
            if _complete_bundle(pending,identity,spec) is None or cancel.is_set():
                raise SceneRasterError("场景合成未完成验证或已取消。")
            pending.replace(directory)
        finally:
            if pending.exists():
                _remove_cache_dir(pending,root)
        return directory / "scene.tif",metadata,identity


async def get_composed_scene(record: SceneRecord,user_id: str,bbox=None):
    normalized=normalize_bbox(bbox)
    cancel=threading.Event()
    task=asyncio.create_task(asyncio.to_thread(_get_composition,record,user_id,normalized,cancel))
    try:
        return await asyncio.shield(task)
    except OSError as exc:
        raise SceneRasterError("场景缓存读取或写入失败。") from exc
    except asyncio.CancelledError:
        cancel.set()
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        raise


def _remove_abandoned_builds(user_id: str, root: Path):
    # A live builder holds this identity's OS lock for its entire private build.
    # A killed process releases that lock automatically; only then is removal safe.
    for kind in ("compositions", "previews"):
        for directory in root.glob(f"*/{kind}/.building-*"):
            match=re.fullmatch(r"\.building-([a-f0-9]{64})-([a-f0-9]{32})",directory.name)
            if not match or not re.fullmatch(r"[a-f0-9]{12}",directory.parent.parent.name) or directory.is_symlink():
                continue
            try:
                with file_lock(composition_lock_path(user_id,match[1]),timeout=0):
                    _remove_cache_dir(directory,root)
            except (OSError,SceneRasterError):
                continue


def prune_compositions(user_id: str, *, protected: Path | None=None,max_files=60):
    """Evict complete PNG/TIFF bundles only while holding their exclusive OS lock."""
    root=user_cache_root(user_id)
    _remove_abandoned_builds(user_id,root)
    entries=[]
    for kind in ("compositions", "previews"):
        for manifest in root.glob(f"*/{kind}/*/manifest.json"):
            directory=manifest.parent
            if not re.fullmatch(r"[a-f0-9]{64}",directory.name) or directory.is_symlink() or manifest.is_symlink():
                continue
            try:
                count=sum(child.is_file() for child in directory.iterdir())
                entries.append((manifest.stat().st_mtime,manifest,count))
            except OSError:
                continue
    entries.sort(key=lambda entry:entry[0])
    total=sum(count for _,_,count in entries)
    for _,manifest,count in entries:
        if total <= max_files:
            break
        directory=manifest.parent
        if directory == protected:
            continue
        try:
            with file_lock(composition_lock_path(user_id,directory.name),timeout=0):
                _remove_cache_dir(directory,root)
                total-=count
        except (OSError,SceneRasterError):
            continue


class CompositionLease:
    def __init__(self,path,metadata,identity,context,fd):
        self.path,self.metadata,self.identity=path,metadata,identity
        self.context,self.fd=context,fd

    async def release(self):
        try:
            _unlock_fd(self.fd)  # Release before any cancellation point.
            await self.context.__aexit__(None,None,None)
        finally:
            if not self.fd.closed: self.fd.close()

    def __del__(self):
        if not self.fd.closed: self.fd.close()


async def acquire_composition_lease(record,user_id,bbox=None):
    identity,spec=composition_identity(record,user_id,bbox)
    for _ in range(3):
        path,_,_=await get_composed_scene(record,user_id,bbox)
        context=async_file_lock(composition_lock_path(user_id,identity),shared=True)
        fd=await context.__aenter__()
        try:
            metadata=await asyncio.to_thread(_complete_bundle,path.parent,identity,spec,verify_hash=False)
            if metadata is not None:
                return CompositionLease(path,metadata,identity,context,fd)
        except BaseException:
            await context.__aexit__(None,None,None)
            raise
        await context.__aexit__(None,None,None)
    raise SceneRasterError("场景缓存正在并发更新，请稍后查询任务状态。")


def _preview_identity(record,user_id):
    _,composition=composition_identity(record,user_id)
    spec={"version":1,"kind":"preview","composition":composition,
          "preview_size":get_settings().agent_scene_preview_size}
    identity=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
    directory=user_cache_root(user_id) / record.key / "previews" / identity
    if not directory.resolve().is_relative_to(user_cache_root(user_id)):
        raise SceneRasterError("场景预览缓存路径越界。")
    return identity,spec,directory


def _complete_preview(directory,identity,spec, *, verify_hash=True):
    from PIL import Image
    try:
        manifest_path=directory / "manifest.json"
        if manifest_path.is_symlink(): return False
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete" or manifest.get("identity") != identity or manifest.get("spec") != spec:
            return False
        path=directory / "preview.png"
        proof=manifest["files"]["preview.png"]
        if set(manifest["files"]) != {"preview.png"} or path.is_symlink() or path.stat().st_size != proof["size"]:
            return False
        if verify_hash and _digest(path) != proof["sha256"]: return False
        with Image.open(path) as image:
            if image.format != "PNG" or image.mode != "RGB" or min(image.size) < 1 or max(image.size) > spec["preview_size"]:
                return False
            image.verify()
        manifest_path.touch()
        return True
    except (OSError,ValueError,KeyError,TypeError,SyntaxError,Image.DecompressionBombError):
        return False


def _get_preview(record,user_id,cancel,renderer):
    identity,spec,directory=_preview_identity(record,user_id)
    root=user_cache_root(user_id)
    lock=composition_lock_path(user_id,identity)
    with file_lock(lock,cancel=cancel,shared=True):
        if _complete_preview(directory,identity,spec): return directory / "preview.png",identity
    with file_lock(lock,cancel=cancel):
        if _complete_preview(directory,identity,spec): return directory / "preview.png",identity
        if directory.exists(): _remove_cache_dir(directory,root)
        pending=directory.parent / (".building-"+identity+"-"+uuid4().hex)
        pending.mkdir(parents=True)
        try:
            renderer(record,pending / "preview.png")
            if cancel.is_set(): raise SceneRasterError("场景预览已取消。")
            path=pending / "preview.png"
            manifest={"status":"complete","identity":identity,"spec":spec,
                      "files":{"preview.png":{"size":path.stat().st_size,"sha256":_digest(path)}}}
            (pending / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf-8")
            if not _complete_preview(pending,identity,spec) or cancel.is_set():
                raise SceneRasterError("场景预览未完成验证或已取消。")
            pending.replace(directory)
        finally:
            if pending.exists(): _remove_cache_dir(pending,root)
    return directory / "preview.png",identity


async def acquire_preview_lease(record,user_id, *, renderer=render_scene_preview):
    identity,spec,directory=_preview_identity(record,user_id)
    for _ in range(3):
        cancel=threading.Event()
        task=asyncio.create_task(asyncio.to_thread(_get_preview,record,user_id,cancel,renderer))
        try:
            path,_=await asyncio.shield(task)
        except OSError as exc:
            raise SceneRasterError("场景预览缓存读取或写入失败。") from exc
        except asyncio.CancelledError:
            cancel.set()
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
            raise
        context=async_file_lock(composition_lock_path(user_id,identity),shared=True)
        fd=await context.__aenter__()
        try:
            if await asyncio.to_thread(_complete_preview,directory,identity,spec,verify_hash=False):
                return CompositionLease(path,{},identity,context,fd)
        except BaseException:
            await context.__aexit__(None,None,None)
            raise
        await context.__aexit__(None,None,None)
    raise SceneRasterError("场景预览缓存正在并发更新，请稍后重试。")
