"""Cancellation uses the real MinioStore/to_thread adapter with an offline SDK."""
from __future__ import annotations
import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.services import imagery_persist as persist
from app.storage.object_store import MinioStore
from app.db.repositories._pg.imagery import ImageryOwnershipConflict


class Missing(Exception):
    code = "NoSuchKey"


class SDK:
    def __init__(self):
        self.objects = {"other/keep.tif": b"other", "image/results/keep.json": b"old"}
        self.started, self.release = threading.Event(), threading.Event()
        self.put_keys, self.deleted = [], []
        self.block = "image/working.tif"
        self.fail_after_write = False
        self.source_existed_when_released = False
    def stat_object(self, bucket, key):
        if key not in self.objects: raise Missing()
    def fput_object(self, bucket, key, path):
        self.put_keys.append(key)
        if key == self.block:
            self.started.set()
            assert self.release.wait(3), "test worker was not released"
            self.source_existed_when_released = Path(path).exists()
        self.objects[key] = Path(path).read_bytes()
        if self.fail_after_write and key == self.block: raise RuntimeError("offline error after remote commit")
    def remove_object(self, bucket, key):
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    sdk = SDK()
    store = MinioStore.__new__(MinioStore)
    store._bucket, store._client = "offline", sdk
    class Rows(dict):
        metadata = None
    rows = Rows()
    rows.metadata = {}
    @asynccontextmanager
    async def acquire(): yield None
    async def pool(): return SimpleNamespace(acquire=acquire)
    async def insert(conn, *, imagery_id, owner_user_id, create_only=False, **kwargs):
        if imagery_id in rows and (create_only or rows[imagery_id] != owner_user_id): raise ImageryOwnershipConflict(imagery_id)
        rows[imagery_id] = owner_user_id
        rows.metadata[imagery_id] = dict(kwargs.get("metadata") or {})
        return imagery_id
    async def get(conn, *, imagery_id, owner_user_id=None):
        if imagery_id not in rows:
            return None
        return {"owner_user_id": rows[imagery_id], "metadata": rows.metadata.get(imagery_id, {})}
    async def delete(conn, *, imagery_id, owner_user_id, persistence_attempt_id=None):
        if rows.get(imagery_id) == owner_user_id and (persistence_attempt_id is None or
                rows.metadata.get(imagery_id, {}).get("_persistence_attempt_id") == persistence_attempt_id):
            rows.pop(imagery_id)
            return True
        return False
    monkeypatch.setattr(persist, "get_settings", lambda: SimpleNamespace(storage_backend="minio"))
    monkeypatch.setattr(persist, "fetch_optional_pool", pool)
    monkeypatch.setattr(persist, "db_insert_imagery", insert)
    monkeypatch.setattr(persist, "db_delete_imagery", delete)
    monkeypatch.setattr(persist, "db_get_imagery", get)
    monkeypatch.setattr(persist, "get_object_store", lambda: store)
    dest = tmp_path / "image"
    (dest / "results").mkdir(parents=True)
    for name in ("source.tif", "working.tif", "quality.tif", "metadata.json", "results/preview.png"):
        (dest / name).write_bytes(name.encode())
    return sdk, store, rows, dest


@pytest.mark.asyncio
@pytest.mark.parametrize("twice", [False, True])
async def test_cancel_waits_for_real_sdk_before_owned_rollback(setup, twice):
    sdk, _, rows, dest = setup
    task = asyncio.create_task(persist._persist_imagery_record("image", dest, {}, "alice"))
    try:
        assert await asyncio.to_thread(sdk.started.wait, 2)
        task.cancel()
        await asyncio.sleep(.02)
        if twice:
            task.cancel()
            await asyncio.sleep(.02)
        assert not task.done()  # caller must not yet delete the SDK input directory
        assert dest.exists()
    finally:
        sdk.release.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert sdk.source_existed_when_released
    assert sdk.put_keys == ["image/source.tif", "image/working.tif"]
    assert rows == {}
    assert sdk.objects == {"other/keep.tif": b"other", "image/results/keep.json": b"old"}


@pytest.mark.asyncio
async def test_existing_same_owner_row_cannot_be_overwritten_or_rolled_back(setup):
    sdk, _, rows, dest = setup
    sdk.block = None
    rows["image"] = "alice"
    with pytest.raises(HTTPException) as error: await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.status_code == 409
    assert rows == {"image": "alice"} and sdk.put_keys == [] and sdk.deleted == []


@pytest.mark.asyncio
async def test_success_preserves_prior_objects_and_uploads_complete_owned_set(setup):
    sdk, _, rows, dest = setup
    sdk.block = None
    await persist._persist_imagery_record("image", dest, {}, "alice")
    assert rows == {"image": "alice"}
    assert len(sdk.put_keys) == 5 and sdk.deleted == []
    assert sdk.objects["image/results/keep.json"] == b"old"


@pytest.mark.asyncio
async def test_existing_object_is_not_overwritten_or_removed_on_compensation(setup):
    sdk, _, rows, dest = setup
    sdk.objects["image/working.tif"] = b"prior-owner-object"
    with pytest.raises(HTTPException) as error: await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.status_code == 409
    assert rows == {} and sdk.put_keys == ["image/source.tif"]
    assert sdk.objects["image/working.tif"] == b"prior-owner-object"
    assert sdk.deleted == ["image/source.tif"]


@pytest.mark.asyncio
async def test_sdk_commit_then_error_is_settled_before_owned_compensation(setup):
    sdk, _, rows, dest = setup
    sdk.fail_after_write = True
    sdk.release.set()
    with pytest.raises(HTTPException) as error: await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.status_code == 502
    assert sdk.put_keys == ["image/source.tif", "image/working.tif"] and rows == {}
    assert sdk.objects == {"other/keep.tif": b"other", "image/results/keep.json": b"old"}


@pytest.mark.asyncio
async def test_cancel_at_db_commit_keeps_created_row_marker_and_rolls_back(monkeypatch, setup):
    sdk, _, rows, dest = setup
    committed, release = asyncio.Event(), asyncio.Event()
    async def insert(conn, *, imagery_id, owner_user_id, **kwargs):
        assert kwargs["create_only"] is True
        rows[imagery_id] = owner_user_id
        rows.metadata[imagery_id] = dict(kwargs["metadata"])
        committed.set()
        await release.wait()
        return imagery_id
    monkeypatch.setattr(persist, "db_insert_imagery", insert)
    task = asyncio.create_task(persist._persist_imagery_record("image", dest, {}, "alice"))
    await committed.wait()
    task.cancel()
    await asyncio.sleep(.01)
    task.cancel()
    await asyncio.sleep(.01)
    assert not task.done() and rows == {"image": "alice"} and not sdk.put_keys
    release.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert rows == {} and sdk.put_keys == [] and sdk.deleted == []


@pytest.mark.asyncio
async def test_cancel_at_sdk_completion_does_not_start_remaining_uploads(setup):
    sdk, _, rows, dest = setup
    task = asyncio.create_task(persist._persist_imagery_record("image", dest, {}, "alice"))
    assert await asyncio.to_thread(sdk.started.wait, 2)
    sdk.release.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert sdk.put_keys == ["image/source.tif", "image/working.tif"]
    assert rows == {} and "image/working.tif" not in sdk.objects


@pytest.mark.asyncio
async def test_repeated_cancel_during_rollback_does_not_abort_owned_db_delete(monkeypatch, setup):
    sdk, _, rows, dest = setup
    deleting, release_delete = asyncio.Event(), asyncio.Event()
    async def delete(conn, *, imagery_id, owner_user_id, persistence_attempt_id=None):
        deleting.set()
        await release_delete.wait()
        if rows.get(imagery_id) == owner_user_id: rows.pop(imagery_id)
    monkeypatch.setattr(persist, "db_delete_imagery", delete)
    task = asyncio.create_task(persist._persist_imagery_record("image", dest, {}, "alice"))
    assert await asyncio.to_thread(sdk.started.wait, 2)
    task.cancel()
    sdk.release.set()
    await deleting.wait()
    task.cancel()
    await asyncio.sleep(.01)
    assert not task.done()
    release_delete.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert rows == {} and sdk.put_keys == ["image/source.tif", "image/working.tif"]


@pytest.mark.asyncio
async def test_create_only_repo_uses_atomic_conflict_refusal():
    from app.db.repositories._pg.imagery import insert_imagery
    class Conn:
        def __init__(self): self.queries = []
        async def fetchrow(self, query, *args):
            self.queries.append(query)
            return None
    conn = Conn()
    with pytest.raises(ImageryOwnershipConflict):
        await insert_imagery(conn, imagery_id="a" * 12, owner_user_id="alice", create_only=True)
    assert "ON CONFLICT (imagery_id) DO NOTHING" in conn.queries[0]
    assert "DO UPDATE" not in conn.queries[0]


@pytest.mark.asyncio
async def test_api_upload_existing_directory_is_rejected_before_any_write(monkeypatch, tmp_path):
    from app.api.routes import imagery as route
    settings = SimpleNamespace(imagery_max_file_bytes=100, imagery_max_band_count=8, imagery_working_max_dimension=8, imagery_max_working_bytes=1024)
    temp = tmp_path / "upload.tif"
    temp.write_bytes(b"new")
    existing = tmp_path / "old-image"
    existing.mkdir()
    (existing / "source.tif").write_bytes(b"preserve-old")
    async def uploaded(*args): return temp
    monkeypatch.setattr(route, "get_settings", lambda: settings)
    monkeypatch.setattr(route, "get_current_user_id", lambda: "alice")
    monkeypatch.setattr(route, "_write_upload_to_temp", uploaded)
    monkeypatch.setattr(route, "_extract_metadata", lambda path: {"band_count": 3, "width": 1, "height": 1, "dtype": "uint8"})
    monkeypatch.setattr(route, "_imagery_dir", lambda image_id: existing)
    with pytest.raises(HTTPException) as error:
        await route.upload_imagery(SimpleNamespace(filename="new.tif"))
    assert error.value.status_code == 409
    assert (existing / "source.tif").read_bytes() == b"preserve-old"
    assert not temp.exists()


@pytest.mark.asyncio
async def test_api_upload_waits_for_sdk_then_removes_only_new_local_directory(monkeypatch, setup, tmp_path):
    from app.api.routes import imagery as route
    sdk, _, rows, _ = setup
    image_id = "a" * 12
    sdk.block = f"{image_id}/working.tif"
    settings = SimpleNamespace(imagery_max_file_bytes=100, imagery_preview_max_dimension=8, imagery_max_band_count=8, imagery_working_max_dimension=8, imagery_max_working_bytes=1024)
    temp = tmp_path / "upload.tif"
    temp.write_bytes(b"new")
    dest = tmp_path / "api-created"
    async def uploaded(*args): return temp
    def working(source, output, settings):
        output.write_bytes(source.read_bytes())
        return {"working_width": 1, "working_height": 1}
    def preview(source, output, dimension): output.write_bytes(b"png")
    monkeypatch.setattr(route, "get_settings", lambda: settings)
    monkeypatch.setattr(route, "get_current_user_id", lambda: "alice")
    monkeypatch.setattr(route, "_write_upload_to_temp", uploaded)
    monkeypatch.setattr(route, "_extract_metadata", lambda path: {"band_count": 3, "width": 1, "height": 1, "dtype": "uint8"})
    monkeypatch.setattr(route, "_create_working_tif", working)
    monkeypatch.setattr(route, "_generate_preview", preview)
    monkeypatch.setattr(route, "_imagery_dir", lambda _id: dest)
    monkeypatch.setattr(route.uuid, "uuid4", lambda: SimpleNamespace(hex=image_id))
    task = asyncio.create_task(route.upload_imagery(SimpleNamespace(filename="new.tif")))
    try:
        assert await asyncio.to_thread(sdk.started.wait, 2)
        task.cancel()
        await asyncio.sleep(.02)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done() and dest.exists()
    finally:
        sdk.release.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert sdk.source_existed_when_released and not dest.exists() and rows == {}
    assert sdk.put_keys == [f"{image_id}/source.tif", f"{image_id}/working.tif"]
    assert sdk.objects == {"other/keep.tif": b"other", "image/results/keep.json": b"old"}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["metadata", "working", "preview", "hash"])
async def test_api_cancel_during_processing_waits_for_current_thread_before_cleanup(monkeypatch, tmp_path, phase):
    from app.api.routes import imagery as route
    started, release = threading.Event(), threading.Event()
    reads = []
    temp, dest = tmp_path / "upload.tif", tmp_path / "owned-dest"
    temp.write_bytes(b"image")
    settings = SimpleNamespace(imagery_max_file_bytes=100, imagery_preview_max_dimension=8, imagery_max_band_count=8, imagery_working_max_dimension=8, imagery_max_working_bytes=1024)
    async def uploaded(*args): return temp
    def hold(path):
        started.set()
        assert release.wait(3)
        reads.append(Path(path).exists())
    def metadata(path):
        if phase == "metadata": hold(path)
        return {"band_count": 3, "width": 1, "height": 1, "dtype": "uint8"}
    def working(source, output, settings):
        if phase == "working": hold(source)
        output.write_bytes(source.read_bytes())
        return {"working_width": 1, "working_height": 1}
    def preview(source, output, size):
        if phase == "preview": hold(source)
        output.write_bytes(b"png")
    def file_hash(path):
        if phase == "hash": hold(path)
        return "offline-hash"
    monkeypatch.setattr(route, "get_settings", lambda: settings)
    monkeypatch.setattr(route, "get_current_user_id", lambda: "alice")
    monkeypatch.setattr(route, "_write_upload_to_temp", uploaded)
    monkeypatch.setattr(route, "_extract_metadata", metadata)
    monkeypatch.setattr(route, "_create_working_tif", working)
    monkeypatch.setattr(route, "_generate_preview", preview)
    monkeypatch.setattr(route, "_file_sha256", file_hash)
    monkeypatch.setattr(route, "_imagery_dir", lambda _id: dest)
    async def must_not_persist(*args): raise AssertionError("cancel must not start a later persistence step")
    monkeypatch.setattr(route, "_persist_imagery_record", must_not_persist)
    task = asyncio.create_task(route.upload_imagery(SimpleNamespace(filename="sample.tif")))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(.01)
        task.cancel()
        await asyncio.sleep(.01)
        assert not task.done()
        assert temp.exists() if phase == "metadata" else dest.exists()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert reads == [True] and not temp.exists() and not dest.exists()


@pytest.mark.asyncio
async def test_db_commit_then_ack_loss_compensates_only_matching_attempt(monkeypatch, setup):
    sdk, _, rows, dest = setup
    stored = {}
    async def insert(conn, *, imagery_id, owner_user_id, metadata, **kwargs):
        rows[imagery_id] = owner_user_id
        stored.update(metadata)
        rows.metadata[imagery_id] = dict(metadata)
        raise ConnectionError("offline ack loss after commit")
    async def get(conn, *, imagery_id, owner_user_id=None):
        if imagery_id not in rows:
            return None
        return {"owner_user_id": rows[imagery_id], "metadata": stored}
    monkeypatch.setattr(persist, "db_insert_imagery", insert)
    monkeypatch.setattr(persist, "db_get_imagery", get, raising=False)
    with pytest.raises(HTTPException) as error:
        await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.status_code == 503
    assert rows == {} and sdk.put_keys == []


@pytest.mark.asyncio
async def test_failed_compensation_retains_private_cleanup_record(monkeypatch, setup):
    import json
    sdk, store, rows, dest = setup
    sdk.release.set()
    sdk.fail_after_write = True
    async def delete_failure(keys):
        raise ConnectionError("offline cleanup unavailable")
    monkeypatch.setattr(store, "delete_keys", delete_failure)
    with pytest.raises(HTTPException) as error:
        await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.detail["code"] == "IMAGERY_CLEANUP_PENDING"
    pending = list(dest.parent.glob(".imagery-cleanup-pending/*/cleanup.json"))
    assert len(pending) == 1
    record = json.loads(pending[0].read_text(encoding="utf-8"))
    assert record["owner_user_id"] == "alice"
    assert record["object_keys"] == ["image/source.tif", "image/working.tif"]
    assert record["pending_steps"] == ["delete_objects"]
    assert (pending[0].parent / "image" / "source.tif").is_file()
    assert not dest.exists()
    assert rows == {}


@pytest.mark.asyncio
async def test_local_registration_cannot_replace_same_owner_minio_row(monkeypatch, setup):
    sdk, _, rows, dest = setup
    rows["image"] = "alice"
    monkeypatch.setattr(persist, "get_settings", lambda: SimpleNamespace(storage_backend="local"))
    with pytest.raises(HTTPException) as error:
        await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.status_code == 409
    assert rows == {"image": "alice"} and not sdk.put_keys


@pytest.mark.asyncio
async def test_lost_ack_does_not_delete_old_same_owner_row(monkeypatch, setup):
    sdk, _, rows, dest = setup
    rows["image"] = "alice"
    rows.metadata["image"] = {"_persistence_attempt_id": "prior-attempt"}
    async def failed_insert(*args, **kwargs):
        raise ConnectionError("commit outcome not acknowledged")
    monkeypatch.setattr(persist, "db_insert_imagery", failed_insert)
    with pytest.raises(HTTPException) as error:
        await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.status_code == 503
    assert rows == {"image": "alice"} and not sdk.deleted and not sdk.put_keys
    assert not list(dest.parent.glob(".imagery-cleanup-pending/*/cleanup.json"))


@pytest.mark.asyncio
async def test_unknown_commit_is_recorded_without_blind_deletion(monkeypatch, setup):
    import json
    sdk, _, rows, dest = setup
    rows["image"] = "alice"
    async def unavailable(*args, **kwargs):
        raise ConnectionError("database temporarily unavailable")
    monkeypatch.setattr(persist, "db_insert_imagery", unavailable)
    monkeypatch.setattr(persist, "db_get_imagery", unavailable)
    with pytest.raises(HTTPException) as error:
        await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.detail["code"] == "IMAGERY_CLEANUP_PENDING"
    assert rows == {"image": "alice"} and not sdk.deleted and not sdk.put_keys
    record_path = next(dest.parent.glob(".imagery-cleanup-pending/*/cleanup.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["pending_steps"] == ["confirm_registration"]
    assert record["attempt_id"] and record["object_keys"] == []


@pytest.mark.asyncio
async def test_newer_nonce_protects_newer_objects_and_row(monkeypatch, setup):
    import json
    sdk, store, rows, dest = setup
    sdk.block = None
    original_put = store.put
    async def replace_registration(key, path):
        await original_put(key, path)
        rows.metadata["image"] = {"_persistence_attempt_id": "newer-attempt"}
        sdk.objects[key] = b"newer-registration-data"
        raise ConnectionError("offline failure")
    monkeypatch.setattr(store, "put", replace_registration)
    with pytest.raises(HTTPException) as error:
        await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.detail["code"] == "IMAGERY_CLEANUP_PENDING"
    assert rows["image"] == "alice" and sdk.deleted == []
    assert sdk.objects["image/source.tif"] == b"newer-registration-data"
    record_path = next(dest.parent.glob(".imagery-cleanup-pending/*/cleanup.json"))
    assert json.loads(record_path.read_text(encoding="utf-8"))["pending_steps"] == ["confirm_resource_ownership"]


@pytest.mark.asyncio
async def test_record_write_failure_preserves_local_evidence(monkeypatch, setup):
    sdk, store, _, dest = setup
    sdk.release.set()
    sdk.fail_after_write = True
    async def failed_delete(keys): raise ConnectionError("offline cleanup failure")
    def failed_record(*args, **kwargs): raise PermissionError("offline disk failure")
    monkeypatch.setattr(store, "delete_keys", failed_delete)
    monkeypatch.setattr(persist, "_retain_pending_cleanup", failed_record)
    with pytest.raises(HTTPException) as error:
        await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.detail["code"] == "IMAGERY_CLEANUP_PENDING"
    assert error.value.preserve_local_directory
    assert (dest / "source.tif").exists()


@pytest.mark.asyncio
async def test_cancel_with_failed_rollback_remains_cancelled_and_retains_evidence(monkeypatch, setup):
    sdk, store, _, dest = setup
    async def failed_delete(keys): raise ConnectionError("offline cleanup failure")
    monkeypatch.setattr(store, "delete_keys", failed_delete)
    task = asyncio.create_task(persist._persist_imagery_record("image", dest, {}, "alice"))
    try:
        assert await asyncio.to_thread(sdk.started.wait, 2)
        task.cancel()
    finally:
        sdk.release.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert list(dest.parent.glob(".imagery-cleanup-pending/*/cleanup.json"))
    assert sdk.put_keys == ["image/source.tif", "image/working.tif"]


@pytest.mark.asyncio
async def test_db_compensation_failure_lists_pending_db_step(monkeypatch, setup):
    import json
    sdk, _, rows, dest = setup
    sdk.release.set()
    sdk.fail_after_write = True
    async def failed_delete(*args, **kwargs): raise ConnectionError("DB deletion unavailable")
    monkeypatch.setattr(persist, "db_delete_imagery", failed_delete)
    with pytest.raises(HTTPException) as error:
        await persist._persist_imagery_record("image", dest, {}, "alice")
    assert error.value.detail["code"] == "IMAGERY_CLEANUP_PENDING"
    record_path = next(dest.parent.glob(".imagery-cleanup-pending/*/cleanup.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["pending_steps"] == ["delete_db_row"] and rows == {"image": "alice"}
    assert "image/source.tif" not in sdk.objects and "image/working.tif" not in sdk.objects


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["directory_lookup", "directory_create", "results_create", "hash", "metadata_write"])
async def test_api_disk_failure_cleans_new_upload_without_registration(monkeypatch, tmp_path, phase):
    from app.api.routes import imagery as route
    temp, dest = tmp_path / "upload.tif", tmp_path / "owned-dest"
    temp.write_bytes(b"image")
    settings = SimpleNamespace(imagery_max_file_bytes=100, imagery_preview_max_dimension=8,
        imagery_max_band_count=8, imagery_working_max_dimension=8, imagery_max_working_bytes=1024)
    async def uploaded(*args): return temp
    def fail(*args, **kwargs): raise OSError("offline disk failure")
    original_mkdir = Path.mkdir
    def mkdir(path, *args, **kwargs):
        if (phase == "directory_create" and path == dest) or (
                phase == "results_create" and path == dest / "results"):
            fail()
        return original_mkdir(path, *args, **kwargs)
    def working(source, output, settings):
        output.write_bytes(source.read_bytes())
        return {"working_width": 1, "working_height": 1}
    def preview(source, output, size): output.write_bytes(b"png")
    async def must_not_persist(*args): raise AssertionError("failed disk preparation must not register imagery")
    monkeypatch.setattr(route, "get_settings", lambda: settings)
    monkeypatch.setattr(route, "get_current_user_id", lambda: "alice")
    monkeypatch.setattr(route, "_write_upload_to_temp", uploaded)
    monkeypatch.setattr(route, "_extract_metadata", lambda path: {"band_count": 3, "width": 1, "height": 1, "dtype": "uint8"})
    monkeypatch.setattr(route, "_create_working_tif", working)
    monkeypatch.setattr(route, "_generate_preview", preview)
    monkeypatch.setattr(route, "_imagery_dir", fail if phase == "directory_lookup" else lambda _id: dest)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(route, "_persist_imagery_record", must_not_persist)
    if phase == "metadata_write": monkeypatch.setattr(route, "_write_json_atomic", fail)
    if phase == "hash": monkeypatch.setattr(route, "_file_sha256", fail)
    with pytest.raises(HTTPException) as error:
        await route.upload_imagery(SimpleNamespace(filename="sample.tif"))
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "STORAGE_UNAVAILABLE"
    assert "offline disk" not in error.value.detail["message"]
    assert not temp.exists() and not dest.exists()
