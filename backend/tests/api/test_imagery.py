from io import BytesIO
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.main import create_app
from app.core.settings import get_settings
from app.db.repositories._pg.imagery import ImageryOwnershipConflict


def make_client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("IMAGERY_WORKING_MAX_DIMENSION", "4")
    monkeypatch.setenv("IMAGERY_PREVIEW_MAX_DIMENSION", "3")
    get_settings.cache_clear()
    return TestClient(create_app())


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
    assert "GeoTIFF" in response.json()["detail"]
    assert "not a geotiff" not in response.json()["detail"]


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
    assert "synthetic" not in response.json()["detail"]  # 异常细节不外泄
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
    client = make_client(monkeypatch, tmp_path)
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
                     storage_backend="local", metadata=None) -> str:
        if self.fail_insert:
            raise RuntimeError("synthetic DB insert failure")
        existing = self.rows.get(imagery_id)
        if existing and existing["owner_user_id"] != owner_user_id:
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

    async def delete(self, conn, *, imagery_id, owner_user_id) -> bool:
        row = self.rows.get(imagery_id)
        if row and row["owner_user_id"] == owner_user_id:
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
    monkeypatch.setattr("app.api.routes.imagery.object_store_for", lambda b: store)
    if with_db:
        monkeypatch.setattr("app.api.routes.imagery.fetch_optional_pool", lambda: _wrap(_FakePool()))
        monkeypatch.setattr("app.api.routes.imagery.db_insert_imagery", db.insert)
        monkeypatch.setattr("app.api.routes.imagery.db_get_imagery", db.get)
        monkeypatch.setattr("app.api.routes.imagery.db_delete_imagery", db.delete)
        monkeypatch.setattr("app.api.routes.imagery.db_list_imagery", db.list)
    else:
        monkeypatch.setattr("app.api.routes.imagery.fetch_optional_pool", lambda: _wrap(None))
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
