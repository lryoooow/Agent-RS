from io import BytesIO
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.main import create_app
from app.core.settings import Settings, get_settings
from app.db.repositories._pg.imagery import ImageryOwnershipConflict


def make_client(monkeypatch, tmp_path: Path, *, admin: bool = False) -> TestClient:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("IMAGERY_WORKING_MAX_DIMENSION", "4")
    monkeypatch.setenv("IMAGERY_PREVIEW_MAX_DIMENSION", "3")
    get_settings.cache_clear()
    app = create_app()
    if admin:
        # 2026-10-07 require_admin 收紧（auth 关闭不再匿名放行，见 test_admin.py）。
        # cleanup 用例只测清理逻辑，管理员语义经标准依赖覆盖注入。
        from app.api.deps import require_admin

        app.dependency_overrides[require_admin] = lambda: {"id": "admin-test"}
    return TestClient(app)


def make_geotiff(*, width: int = 6, height: int = 4, count: int = 4) -> bytes:
    buffer = BytesIO()
    data = np.zeros((count, height, width), dtype=np.uint16)
    for band in range(count):
        data[band] = np.arange(width * height, dtype=np.uint16).reshape(height, width) + band
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(100, 20, 0.01, 0.01),
    ) as dst:
        dst.write(data)
    return buffer.getvalue()


def test_imagery_upload_generates_working_raster_and_preview(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )

    assert response.status_code == 200
    body = response.json()
    imagery_dir = tmp_path / "imagery" / body["imagery_id"]
    assert body["preview_url"] == f"/api/imagery/{body['imagery_id']}/results/preview.png"
    assert body["working_width"] == 4
    assert body["working_height"] == 3
    assert body["compressed"] is True
    assert body["sha256"]
    assert body["source_size_bytes"] > 0
    assert body["working_size_bytes"] > 0
    assert (imagery_dir / "source.tif").exists()
    assert (imagery_dir / "working.tif").exists()
    assert (imagery_dir / "results" / "preview.png").exists()
    with rasterio.open(imagery_dir / "working.tif") as src:
        assert src.width == 4
        assert src.height == 3
        assert src.count == 4
        assert src.compression.value.lower() == "deflate"


def test_imagery_upload_rejects_invalid_geotiff_without_500(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("broken.tif", b"not a geotiff", "image/tiff")},
    )

    assert response.status_code == 422
    assert "GeoTIFF" in response.json()["error"]["message"]
    assert "not a geotiff" not in response.json()["error"]["message"]


def test_imagery_upload_propagates_processing_exception_through_to_thread(
    monkeypatch, tmp_path: Path
) -> None:
    # 验证：_create_working_tif 经 asyncio.to_thread offload 后，其内部异常仍被
    # 原 try/except 捕获 → 返回 422（非 500），且失败时清理 dest 目录（异常分支）。
    client = make_client(monkeypatch, tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic working-tif failure")

    monkeypatch.setattr("app.api.routes.imagery._create_working_tif", boom)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )

    assert response.status_code == 422
    assert "synthetic" not in response.json()["error"]["message"]  # 异常细节不外泄
    # 失败清理：imagery 根目录下不应残留任何影像子目录
    imagery_root = tmp_path / "imagery"
    leftover = [p for p in imagery_root.iterdir() if p.is_dir()] if imagery_root.exists() else []
    assert leftover == []


def test_imagery_upload_rejects_oversized_file_after_closing_handle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("IMAGERY_MAX_FILE_BYTES", "8")
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("large.tif", b"0123456789", "image/tiff")},
    )

    assert response.status_code == 413
    imagery_root = tmp_path / "imagery"
    assert not imagery_root.exists() or list(imagery_root.iterdir()) == []


def test_imagery_result_rejects_invalid_id(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)

    response = client.get("/api/imagery/..invalid/results/preview.png")

    assert response.status_code == 400


def test_imagery_result_serves_preview_from_safe_path(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    upload = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )
    imagery_id = upload.json()["imagery_id"]

    response = client.get(f"/api/imagery/{imagery_id}/results/preview.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")


def test_imagery_list_hides_other_user_metadata(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    other_dir = tmp_path / "imagery" / "94e758f38ede"
    other_dir.mkdir(parents=True)
    (other_dir / "metadata.json").write_text(
        json.dumps({"filename": "other.tif", "owner_user_id": "other-user"}),
        encoding="utf-8",
    )

    response = client.get("/api/imagery")

    assert response.status_code == 200
    assert response.json() == []


def test_imagery_detail_and_result_reject_other_owner(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    other_dir = tmp_path / "imagery" / "94e758f38ede"
    results_dir = other_dir / "results"
    results_dir.mkdir(parents=True)
    (other_dir / "metadata.json").write_text(
        json.dumps({"filename": "other.tif", "owner_user_id": "other-user"}),
        encoding="utf-8",
    )
    (results_dir / "preview.png").write_bytes(b"png")

    detail = client.get("/api/imagery/94e758f38ede")
    result = client.get("/api/imagery/94e758f38ede/results/preview.png")
    delete = client.delete("/api/imagery/94e758f38ede")

    assert detail.status_code == 404
    assert result.status_code == 404
    assert delete.status_code == 404
    assert other_dir.exists()


def test_imagery_list_skips_broken_metadata(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    broken_dir = tmp_path / "imagery" / "94e758f38ede"
    broken_dir.mkdir(parents=True)
    (broken_dir / "metadata.json").write_text("{bad json", encoding="utf-8")

    response = client.get("/api/imagery")

    assert response.status_code == 200
    assert response.json() == []


def test_imported_metadata_id_does_not_break_list_or_detail(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    image_id = '94e758f38ede'
    image_dir = tmp_path / 'imagery' / image_id
    image_dir.mkdir(parents=True)
    (image_dir / 'metadata.json').write_text(json.dumps({
        'imagery_id': image_id, 'filename': 'map.tif', 'source_origin': 'map_roi',
        'owner_user_id': get_settings().default_user_id,
    }), encoding='utf-8')
    listing = client.get('/api/imagery')
    detail = client.get('/api/imagery/' + image_id)
    assert listing.status_code == detail.status_code == 200
    assert listing.json()[0]['imagery_id'] == detail.json()['imagery_id'] == image_id
    assert detail.json()['source_origin'] == 'map_roi'


def test_imagery_delete_removes_directory(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path)
    upload = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )
    imagery_id = upload.json()["imagery_id"]
    imagery_dir = tmp_path / "imagery" / imagery_id

    response = client.delete(f"/api/imagery/{imagery_id}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert not imagery_dir.exists()


def test_imagery_cleanup_removes_old_orphan_directory(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, admin=True)
    orphan_dir = tmp_path / "imagery" / "94e758f38ede"
    orphan_dir.mkdir(parents=True)
    old_timestamp = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()
    orphan_dir.touch()
    import os

    os.utime(orphan_dir, (old_timestamp, old_timestamp))

    response = client.post("/api/imagery/cleanup")

    assert response.status_code == 200
    assert response.json()["removed"] == ["94e758f38ede"]
    assert not orphan_dir.exists()


# ───────────────────────── MinIO 后端分支（fake store + fake DB，不连真实 MinIO/PG）─────────────────────────
class _FakeObjectStore:
    """内存对象存储：覆盖 imagery 路由 minio 分支用到的 put/open_stream/delete_prefix/exists。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_prefixes: list[str] = []
        self.fail_put = False

    async def put(self, key: str, path: Path) -> None:
        if self.fail_put:
            raise RuntimeError("synthetic object-store put failure")
        self.objects[key] = Path(path).read_bytes()

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def open_stream(self, key: str):
        if key not in self.objects:
            raise FileNotFoundError(key)
        data = self.objects[key]

        async def _iter():
            yield data

        return _iter()

    async def delete_keys(self, keys: list[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)

    async def delete_prefix(self, key_prefix: str) -> None:
        self.deleted_prefixes.append(key_prefix)
        for key in [k for k in self.objects if k.startswith(f"{key_prefix}/")]:
            self.objects.pop(key, None)


class _FakeImageryDB:
    """内存 imagery 归属表：复刻 #2/#4 后的 DB 语义（owner 不可转移、按属主过滤），
    让 TestClient（无法共享 session-loop 绑定的 pg_pool）也能验证 minio 的 DB 硬依赖路径。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.fail_insert = False

    async def insert(self, conn, *, imagery_id, owner_user_id, workspace_id=None,
                     filename=None, sha256=None, bounds=None, bands=None,
                     storage_backend="local", metadata=None, create_only=False) -> str:
        if self.fail_insert:
            raise RuntimeError("synthetic DB insert failure")
        existing = self.rows.get(imagery_id)
        if existing and (create_only or existing["owner_user_id"] != owner_user_id):
            raise ImageryOwnershipConflict(imagery_id)  # #4：归属不可转移
        self.rows[imagery_id] = {
            "id": imagery_id, "imagery_id": imagery_id, "owner_user_id": owner_user_id,
            "storage_backend": storage_backend, "metadata": dict(metadata or {}),
            "filename": filename,
        }
        return imagery_id

    async def get(self, conn, *, imagery_id, owner_user_id=None):
        row = self.rows.get(imagery_id)
        if row is None:
            return None
        if owner_user_id is not None and row["owner_user_id"] != owner_user_id:
            return None
        return dict(row)

    async def delete(self, conn, *, imagery_id, owner_user_id, persistence_attempt_id=None) -> bool:
        row = self.rows.get(imagery_id)
        if (row and row["owner_user_id"] == owner_user_id and
                (persistence_attempt_id is None or row["metadata"].get("_persistence_attempt_id") == persistence_attempt_id)):
            del self.rows[imagery_id]
            return True
        return False

    async def list(self, conn, *, owner_user_id, limit=200):
        return [dict(r) for r in self.rows.values() if r["owner_user_id"] == owner_user_id]


def _wrap(value):
    """把值包成 fetch_optional_pool 期望的 awaitable。"""
    async def _inner():
        return value
    return _inner()


class _FakePool:
    """最小 asyncpg 池替身：仅支持 `async with pool.acquire() as conn`（conn 不被 fake DB 使用）。"""

    def acquire(self):
        return _FakeAcquire()


class _FakeAcquire:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def make_minio_client(
    monkeypatch, tmp_path: Path, *, backend: str = "minio", with_db: bool = True
) -> tuple[TestClient, _FakeObjectStore, _FakeImageryDB]:
    """minio 路由测试夹具：fake 对象存储 + fake DB 层（per-row 路由 + DB 硬依赖）。

    backend：全局 STORAGE_BACKEND（验证 per-row 路由时可设 local 而行按 minio 读）。
    with_db=False：模拟 DB 不可用（fetch_optional_pool 返 None），验证 #2 的 503 + 不留孤儿。
    object_store_for（#3 per-row 路由用）与 get_object_store 都打成同一 fake store。
    """
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("IMAGERY_WORKING_MAX_DIMENSION", "4")
    monkeypatch.setenv("IMAGERY_PREVIEW_MAX_DIMENSION", "3")
    monkeypatch.setenv("STORAGE_BACKEND", backend)
    get_settings.cache_clear()
    store = _FakeObjectStore()
    db = _FakeImageryDB()
    monkeypatch.setattr("app.api.routes.imagery.get_object_store", lambda: store)
    monkeypatch.setattr("app.services.imagery_persist.get_object_store", lambda: store)
    monkeypatch.setattr("app.api.routes.imagery.object_store_for", lambda b: store)
    if with_db:
        monkeypatch.setattr("app.api.routes.imagery.fetch_optional_pool", lambda: _wrap(_FakePool()))
        monkeypatch.setattr("app.api.routes.imagery.db_insert_imagery", db.insert)
        # 持久化逻辑下沉后，patch 面向服务模块
        monkeypatch.setattr("app.services.imagery_persist.fetch_optional_pool", lambda: _wrap(_FakePool()))
        monkeypatch.setattr("app.services.imagery_persist.db_insert_imagery", db.insert)
        monkeypatch.setattr("app.services.imagery_persist.db_get_imagery", db.get)
        monkeypatch.setattr("app.api.routes.imagery.db_get_imagery", db.get)
        monkeypatch.setattr("app.api.routes.imagery.db_delete_imagery", db.delete)
        monkeypatch.setattr("app.services.imagery_persist.db_delete_imagery", db.delete)
        monkeypatch.setattr("app.api.routes.imagery.db_list_imagery", db.list)
    else:
        monkeypatch.setattr("app.api.routes.imagery.fetch_optional_pool", lambda: _wrap(None))
        monkeypatch.setattr("app.services.imagery_persist.fetch_optional_pool", lambda: _wrap(None))
    client = TestClient(create_app())
    return client, store, db


def test_minio_upload_pushes_objects_and_registers_db_row(monkeypatch, tmp_path: Path) -> None:
    # 常规：minio 后端上传 → 对象推到存储 + DB 登记 owner 行（storage_backend=minio）。
    client, store, db = make_minio_client(monkeypatch, tmp_path)

    upload = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )
    assert upload.status_code == 200
    imagery_id = upload.json()["imagery_id"]

    assert f"{imagery_id}/source.tif" in store.objects
    assert f"{imagery_id}/working.tif" in store.objects
    assert f"{imagery_id}/metadata.json" in store.objects
    assert f"{imagery_id}/results/preview.png" in store.objects
    # DB owner 行已登记，且后端标记为 minio（#2 硬依赖、#3 per-row 路由依据）。
    assert imagery_id in db.rows
    assert db.rows[imagery_id]["storage_backend"] == "minio"
    # 本地 metadata.json 仍写（同实例兜底；多实例靠 DB）。
    assert (tmp_path / "imagery" / imagery_id / "metadata.json").exists()


def test_minio_upload_without_db_returns_503_and_no_orphan_objects(monkeypatch, tmp_path: Path) -> None:
    # #2 根因：minio 模式 DB 不可用 → 503，且绝不产生孤儿对象 / 残留本地目录。
    client, store, _db = make_minio_client(monkeypatch, tmp_path, with_db=False)

    upload = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )
    assert upload.status_code == 503
    assert store.objects == {}  # 未上传任何对象（DB-first，先检查库）
    imagery_root = tmp_path / "imagery"
    leftover = [p for p in imagery_root.iterdir() if p.is_dir()] if imagery_root.exists() else []
    assert leftover == []  # 本地目录已清，无"上传成功"假象


def test_minio_upload_db_insert_failure_returns_503_no_objects(monkeypatch, tmp_path: Path) -> None:
    # #2 异常分支：DB 写入失败（DB-first 的第①步）→ 503，未上传对象、无残留。
    client, store, db = make_minio_client(monkeypatch, tmp_path)
    db.fail_insert = True

    upload = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )
    assert upload.status_code == 503
    assert store.objects == {}
    assert db.rows == {}
    imagery_root = tmp_path / "imagery"
    leftover = [p for p in imagery_root.iterdir() if p.is_dir()] if imagery_root.exists() else []
    assert leftover == []


def test_minio_upload_object_put_failure_rolls_back_db_and_objects(monkeypatch, tmp_path: Path) -> None:
    # #2 原子性：DB 行写成功但对象上传失败 → 回滚 DB 行 + 已传对象 → 502，无孤儿。
    client, store, db = make_minio_client(monkeypatch, tmp_path)
    store.fail_put = True

    upload = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    )
    assert upload.status_code == 502
    assert store.objects == {}   # 已传对象被回滚清理
    assert db.rows == {}         # DB 行被回滚删除（不留"有行无对象"的孤儿）
    imagery_root = tmp_path / "imagery"
    leftover = [p for p in imagery_root.iterdir() if p.is_dir()] if imagery_root.exists() else []
    assert leftover == []


def test_minio_result_proxy_streams_with_owner_auth(monkeypatch, tmp_path: Path) -> None:
    # 常规：minio 后端读结果走代理流式，内容来自对象存储、保留 owner 校验（DB 优先）。
    client, store, _db = make_minio_client(monkeypatch, tmp_path)
    imagery_id = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    ).json()["imagery_id"]

    response = client.get(f"/api/imagery/{imagery_id}/results/preview.png")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == store.objects[f"{imagery_id}/results/preview.png"]


def test_minio_result_missing_object_returns_404(monkeypatch, tmp_path: Path) -> None:
    # 边界：对象存储无此结果文件 → open_stream 抛 FileNotFoundError → 404（非 500）。
    client, _store, _db = make_minio_client(monkeypatch, tmp_path)
    imagery_id = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    ).json()["imagery_id"]

    response = client.get(f"/api/imagery/{imagery_id}/results/missing.png")
    assert response.status_code == 404


def test_minio_result_rejects_other_owner(monkeypatch, tmp_path: Path) -> None:
    # 历史重复点（租户隔离靠约定）：他人 imagery_id 经代理流式端点 → DB owner 校验拒绝（不泄漏字节）。
    client, store, db = make_minio_client(monkeypatch, tmp_path)
    other_id = "94e758f38ede"
    # 直接在 DB 登记一条属于他人的 minio 影像 + 在对象存储放结果。
    db.rows[other_id] = {
        "id": other_id, "imagery_id": other_id, "owner_user_id": "other-user",
        "storage_backend": "minio", "metadata": {"filename": "other.tif"}, "filename": "other.tif",
    }
    store.objects[f"{other_id}/results/preview.png"] = b"secret-bytes"

    response = client.get(f"/api/imagery/{other_id}/results/preview.png")
    assert response.status_code == 404
    assert b"secret-bytes" not in response.content


def test_minio_delete_clears_object_store_db_and_local(monkeypatch, tmp_path: Path) -> None:
    # 常规：minio 后端删除 → delete_prefix 清对象存储 + 删 DB 行 + 删本地目录。
    client, store, db = make_minio_client(monkeypatch, tmp_path)
    imagery_id = client.post(
        "/api/imagery/upload",
        files={"file": ("sample.tif", make_geotiff(), "image/tiff")},
    ).json()["imagery_id"]
    imagery_dir = tmp_path / "imagery" / imagery_id

    response = client.delete(f"/api/imagery/{imagery_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert imagery_id in store.deleted_prefixes
    assert f"{imagery_id}/source.tif" not in store.objects
    assert imagery_id not in db.rows
    assert not imagery_dir.exists()


def test_per_row_backend_routes_read_independent_of_global(monkeypatch, tmp_path: Path) -> None:
    # #3 根因：全局 STORAGE_BACKEND=local，但某影像 DB 行标 minio → 读仍走对象存储（不按全局误判 404）。
    # 反向也覆盖：另一影像行标 local → 走本地 FileResponse。
    client, store, db = make_minio_client(monkeypatch, tmp_path, backend="local")
    current = get_settings().default_user_id

    # ① 行标 minio 的影像：结果只在对象存储，本地无文件。
    minio_id = "aaaaaaaaaaaa"
    db.rows[minio_id] = {
        "id": minio_id, "imagery_id": minio_id, "owner_user_id": current,
        "storage_backend": "minio", "metadata": {"filename": "m.tif"}, "filename": "m.tif",
    }
    store.objects[f"{minio_id}/results/ndvi.png"] = b"PNGDATA"

    resp_minio = client.get(f"/api/imagery/{minio_id}/results/ndvi.png")
    assert resp_minio.status_code == 200          # 按行后端走 minio，未因全局 local 而 404
    assert resp_minio.content == b"PNGDATA"

    # ② 行标 local 的影像：结果在本地盘。
    local_id = "bbbbbbbbbbbb"
    db.rows[local_id] = {
        "id": local_id, "imagery_id": local_id, "owner_user_id": current,
        "storage_backend": "local", "metadata": {"filename": "l.tif"}, "filename": "l.tif",
    }
    local_results = tmp_path / "imagery" / local_id / "results"
    local_results.mkdir(parents=True)
    (local_results / "ndvi.png").write_bytes(b"LOCALPNG")
    (tmp_path / "imagery" / local_id / "metadata.json").write_text(
        json.dumps({"filename": "l.tif", "owner_user_id": current}), encoding="utf-8"
    )

    resp_local = client.get(f"/api/imagery/{local_id}/results/ndvi.png")
    assert resp_local.status_code == 200
    assert resp_local.content == b"LOCALPNG"      # 行标 local → 本地读，未误走对象存储


def test_per_row_backend_routes_delete_minio_row_under_local_global(monkeypatch, tmp_path: Path) -> None:
    # #3：全局 local 下删除一条 minio 行影像 → 仍删对象存储前缀（不漏删孤儿对象）。
    client, store, db = make_minio_client(monkeypatch, tmp_path, backend="local")
    current = get_settings().default_user_id
    minio_id = "cccccccccccc"
    db.rows[minio_id] = {
        "id": minio_id, "imagery_id": minio_id, "owner_user_id": current,
        "storage_backend": "minio", "metadata": {"filename": "m.tif"}, "filename": "m.tif",
    }
    store.objects[f"{minio_id}/source.tif"] = b"SRC"

    response = client.delete(f"/api/imagery/{minio_id}")
    assert response.status_code == 200
    assert minio_id in store.deleted_prefixes          # 按行后端删了对象存储
    assert f"{minio_id}/source.tif" not in store.objects
    assert minio_id not in db.rows


# ───────────────────────── G2 波段预算校验与逐波段工作图（bugfix-plan-G，2026-10-09）─────────────────────────
# 历史 bug：_create_working_tif 无波段数/体积上限且一次性 src.read 全部波段——
# 517KB 的 1000 波段 deflate 全零上传即迫使后端分配 750MB（tracemalloc 复现）；
# 放大到 4096 工作上限 × 64+ 波段可数 GB 拖垮进程。
# 修复：_validate_band_budget 在 _extract_metadata 后校验（count ≤ 64 且
# count×工作宽×工作高×itemsize ≤ 1GB，均可配置）→ 413；工作图逐波段读写。

from fastapi import HTTPException  # noqa: E402

from app.api.routes.imagery import (  # noqa: E402
    _create_working_tif as _g2_create_working_tif,
)
from app.api.routes.imagery import _validate_band_budget  # noqa: E402


def _make_zero_tif(*, count: int, width: int, height: int, dtype: str = "uint16") -> bytes:
    """全零 deflate 小 TIFF：文件极小、解压后 count×W×H×itemsize，用于波段预算复现。"""
    buffer = BytesIO()
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype=dtype,
        crs="EPSG:4326",
        transform=from_origin(100, 20, 0.01, 0.01),
        compress="deflate",
    ) as dst:
        dst.write(np.zeros((count, height, width), dtype=dtype))
    return buffer.getvalue()


def test_imagery_upload_rejects_thousand_band_tiff_413(monkeypatch, tmp_path: Path) -> None:
    """非法：1000 波段 deflate 全零小 TIFF → 413 IMAGERY_TOO_MANY_BANDS（修复前会整读 512MB+）。"""
    client = make_client(monkeypatch, tmp_path)
    bomb = _make_zero_tif(count=1000, width=6, height=4)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("many_bands.tif", bomb, "image/tiff")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMAGERY_TOO_MANY_BANDS"
    imagery_root = tmp_path / "imagery"
    assert not imagery_root.exists() or list(imagery_root.iterdir()) == []  # 无残留目录


def test_imagery_upload_rejects_oversized_working_budget_413(monkeypatch, tmp_path: Path) -> None:
    """非法：波段数合规但 count×工作宽×工作高×itemsize 超限 → 413 IMAGERY_WORKING_TOO_LARGE。

    make_client 固定 WORKING_MAX_DIMENSION=4：6x4 源 → 工作 4x3；5 波段 uint16
    = 5×4×3×2 = 120 字节 > 上限 100。
    """
    monkeypatch.setenv("IMAGERY_MAX_WORKING_BYTES", "100")
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("budget.tif", make_geotiff(count=5), "image/tiff")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMAGERY_WORKING_TOO_LARGE"
    imagery_root = tmp_path / "imagery"
    assert not imagery_root.exists() or list(imagery_root.iterdir()) == []


def test_imagery_upload_working_budget_boundary_passes(monkeypatch, tmp_path: Path) -> None:
    """边界：预算恰好等于上限（120 == 120）放行——上限含边界值。"""
    monkeypatch.setenv("IMAGERY_MAX_WORKING_BYTES", "120")
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/imagery/upload",
        files={"file": ("exact.tif", make_geotiff(count=5), "image/tiff")},
    )

    assert response.status_code == 200
    assert response.json()["band_count"] == 5


def test_validate_band_budget_unit_boundaries(tmp_path: Path) -> None:
    """单元级：波段数 64 过/65 拒；体积恰等上限过；元数据缺失字段不炸（视为 0）。"""
    settings = get_settings()
    meta_ok = {"band_count": 64, "width": 4, "height": 4, "dtype": "uint8"}
    _validate_band_budget(meta_ok, settings)  # 64×4×4×1 = 1024B，两项均在上限内

    with pytest.raises(HTTPException) as exc:
        _validate_band_budget({**meta_ok, "band_count": 65}, settings)
    assert exc.value.status_code == 413
    assert exc.value.detail["code"] == "IMAGERY_TOO_MANY_BANDS"

    # 体积恰等上限：63 波段 × 4×4 × uint16 = 2016 == 上限
    exact = Settings(_env_file=None, imagery_max_working_bytes=2016)
    _validate_band_budget({"band_count": 63, "width": 4, "height": 4, "dtype": "uint16"}, exact)
    # 超一字节即拒
    with pytest.raises(HTTPException) as exc:
        _validate_band_budget({"band_count": 63, "width": 5, "height": 4, "dtype": "uint16"}, exact)
    assert exc.value.detail["code"] == "IMAGERY_WORKING_TOO_LARGE"

    # Missing dimensions must fail closed with 422, not bypass the budget.
    with pytest.raises(HTTPException) as error:
        _validate_band_budget({"dtype": "uint16"}, settings)
    assert error.value.status_code == 422


def _reference_working_bands(source_path: Path, working_width: int, working_height: int, resampled: bool) -> np.ndarray:
    """参考实现 = 修复前的整读语义（git 历史 1afc02c 之前）：整栈 read + alpha 波段
    nearest 覆写。独立于被测的逐波段新实现，用于逐像素等价对照。"""
    from rasterio.enums import Resampling

    with rasterio.open(source_path) as src:
        data = src.read(
            out_shape=(src.count, working_height, working_width),
            resampling=Resampling.bilinear if resampled else Resampling.nearest,
        )
        if resampled:
            for index, interpretation in enumerate(src.colorinterp, 1):
                if interpretation.name == "alpha":
                    data[index - 1] = src.read(
                        index, out_shape=(working_height, working_width), resampling=Resampling.nearest
                    )
    return data


def test_working_tif_matches_pre_fix_reference_pixels(tmp_path: Path) -> None:
    """回归：逐波段写入与修复前整读算法逐像素一致（含缩放与非 alpha 波段）。

    24x16 源、工作上限 4 → 工作 4x3，bilinear 重采样路径；3 波段非平凡值。
    """
    source = tmp_path / "src_ref.tif"
    count, width, height = 3, 24, 16
    rng = np.random.default_rng(20261009)
    data = rng.integers(0, 4000, (count, height, width), dtype=np.uint16)
    with rasterio.open(
        source, "w", driver="GTiff", height=height, width=width, count=count,
        dtype="uint16", crs="EPSG:4326", transform=from_origin(100.0, 20.0, 0.01, 0.01),
    ) as dst:
        dst.write(data)

    settings = Settings(_env_file=None, imagery_working_max_dimension=4)
    working = tmp_path / "working_ref.tif"
    _g2_create_working_tif(source, working, settings)

    reference = _reference_working_bands(source, 4, 3, resampled=True)
    with rasterio.open(working) as got:
        assert (got.width, got.height, got.count) == (4, 3, count)
        actual = got.read()
    assert np.array_equal(actual, reference), "逐波段写入与整读参考实现逐像素不一致"


def test_working_tif_no_rescale_rgba_pixels_identical(monkeypatch, tmp_path: Path) -> None:
    """回归：不缩放时工作图波段值与源逐像素一致（nearest 恒等），含 RGBA alpha 波段。"""
    source = tmp_path / "src_rgba.tif"
    count, width, height = 4, 8, 8
    rng = np.random.default_rng(20261010)
    data = rng.integers(0, 255, (count, height, width), dtype=np.uint8)
    with rasterio.open(
        source, "w", driver="GTiff", height=height, width=width, count=count,
        dtype="uint8", crs="EPSG:4326", transform=from_origin(100.0, 20.0, 0.01, 0.01),
        photometric="rgb",
    ) as dst:
        # colorinterp（含 alpha ExtraSamples）须在写数据之前设置，GDAL 不允许写后改
        dst.colorinterp = (
            rasterio.enums.ColorInterp.red,
            rasterio.enums.ColorInterp.green,
            rasterio.enums.ColorInterp.blue,
            rasterio.enums.ColorInterp.alpha,
        )
        dst.write(data)

    settings = Settings(_env_file=None, imagery_working_max_dimension=16)  # 8<16 不缩放
    working = tmp_path / "working_rgba.tif"
    _g2_create_working_tif(source, working, settings)

    with rasterio.open(working) as got:
        assert [c.name for c in got.colorinterp] == ["red", "green", "blue", "alpha"]
        actual = got.read()
    with rasterio.open(source) as src:
        expected = src.read()
    assert np.array_equal(actual, expected)


def test_working_tif_mask_equals_dataset_mask(tmp_path: Path) -> None:
    """G2 等价性：逐波段累积 mask 与 dataset_mask 逐位一致（无 nodata/命中/alpha/缩放）。

    期望值独立来源：dataset_mask 本身（修复前实现写入工作图的数据）。
    """
    from rasterio.enums import Resampling

    def build(path: Path, *, nodata=None, alpha=False, fill=None) -> None:
        count = 4 if alpha else 3
        data = np.full((count, 8, 8), 7, dtype="uint16")
        if fill is not None:
            data[:, :4, :] = fill  # 左半为无效值
        kwargs = dict(driver="GTiff", height=8, width=8, count=count, dtype="uint16",
                      crs="EPSG:4326", transform=from_origin(100, 20, 0.01, 0.01))
        if nodata is not None:
            kwargs["nodata"] = nodata
        if alpha:
            kwargs["photometric"] = "rgb"
        with rasterio.open(path, "w", **kwargs) as dst:
            if alpha:
                dst.colorinterp = (rasterio.enums.ColorInterp.red, rasterio.enums.ColorInterp.green,
                                   rasterio.enums.ColorInterp.blue, rasterio.enums.ColorInterp.alpha)
            dst.write(data)

    cases = {
        "no_nodata": dict(),
        "nodata_left_half": dict(nodata=99, fill=99),
        "nodata_miss": dict(nodata=99),
        "alpha": dict(alpha=True),
    }
    for name, kwargs in cases.items():
        source = tmp_path / f"{name}.tif"
        build(source, **kwargs)
        working = tmp_path / f"{name}_working.tif"
        _g2_create_working_tif(source, working, Settings(_env_file=None, imagery_working_max_dimension=16))
        with rasterio.open(source) as src, rasterio.open(working) as got:
            expected = src.dataset_mask(resampling=Resampling.nearest)
            # write_mask 将非二值 mask（alpha 派生值）归一化为 255/0——修复前同款行为，
            # 对比基准做同样的二值归一。
            expected = np.where(expected > 0, 255, 0).astype("uint8")
            actual = got.read_masks(1)
            assert np.array_equal(actual, expected), f"mask 不一致：{name}"

    # 缩放路径（8x8 → 4x4 nearest 重采样 mask）
    source = tmp_path / "nodata_left_half.tif"
    working = tmp_path / "resampled_working.tif"
    _g2_create_working_tif(source, working, Settings(_env_file=None, imagery_working_max_dimension=4))
    with rasterio.open(source) as src, rasterio.open(working) as got:
        expected = src.dataset_mask(out_shape=(4, 4), resampling=Resampling.nearest)
        assert np.array_equal(got.read_masks(1), expected)


def test_working_tif_band_by_band_memory_bounded(tmp_path: Path) -> None:
    """G2 内存回归：多波段工作图生成不整读全栈——峰值远小于 count×H×W（tracemalloc）。

    120 波段 × 512x512 uint16：整栈 = 60MB（修复前整读 + mask 栈会 ≥60MB）；
    逐波段实现峰值应为单波段量级（~0.5MB × 少量常数）。
    """
    import tracemalloc

    source = tmp_path / "stack.tif"
    buffer = _make_zero_tif(count=120, width=512, height=512)
    source.write_bytes(buffer)
    del buffer

    settings = Settings(_env_file=None, imagery_max_band_count=128)  # Explicit 120-band resource test; default upload remains capped at 64.
    working = tmp_path / "stack_working.tif"
    tracemalloc.start()
    tracemalloc.reset_peak()
    _g2_create_working_tif(source, working, settings)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    full_stack_bytes = 120 * 512 * 512 * 2
    assert peak < full_stack_bytes // 4, (
        f"peak {peak / 1024 / 1024:.1f}MB 不应超过整栈 {full_stack_bytes / 1024 / 1024:.0f}MB 的 1/4——疑似回退为整读"
    )
    with rasterio.open(working) as got:  # 产物完整可用（非空壳）
        assert (got.count, got.width, got.height) == (120, 512, 512)
        assert got.read(1, out_shape=(8, 8)).max() == 0


@pytest.mark.parametrize("max_dimension", [2, 1])
def test_working_mask_preserves_per_dataset_union_of_partial_band_nodata(tmp_path, max_dimension):
    from app.api.routes.imagery import _create_working_tif
    from rasterio.enums import Resampling
    source, working = tmp_path / "partial.tif", tmp_path / "working.tif"
    data = np.full((3, 2, 2), 7, dtype="uint16")
    data[0, :, :] = 0  # only the unused blue band is missing; red/NIR remain valid
    with rasterio.open(source, "w", driver="GTiff", width=2, height=2, count=3,
                       dtype="uint16", nodata=0, transform=from_origin(100, 20, .01, .01)) as dst:
        dst.write(data)
    _create_working_tif(source, working, Settings(_env_file=None, imagery_working_max_dimension=max_dimension))
    with rasterio.open(source) as original, rasterio.open(working) as result:
        expected = original.dataset_mask(out_shape=(max_dimension, max_dimension), resampling=Resampling.nearest)
        assert np.all(expected == 255)
        np.testing.assert_array_equal(result.dataset_mask(), expected)


def test_preview_rejects_over_budget_before_allocating_output(monkeypatch,tmp_path):
    from app.api.routes.imagery import _generate_preview
    from fastapi import HTTPException
    source=tmp_path/"source.tif";source.write_bytes(_make_zero_tif(count=3,width=16,height=16))
    monkeypatch.setenv("IMAGERY_PREPROCESS_MAX_BYTES","1048576");get_settings.cache_clear()
    with pytest.raises(HTTPException) as caught:
        _generate_preview(source,tmp_path/"preview.png",16)
    assert caught.value.status_code==413 and caught.value.detail["code"]=="IMAGERY_MEMORY_BUDGET"
    assert not (tmp_path/"preview.png").exists()
