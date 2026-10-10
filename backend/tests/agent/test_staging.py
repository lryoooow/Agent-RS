"""工具取数 staging（minio 后端拉临时目录）测试。

staging 是"先拉临时目录再挂载"的关键洞察落点：minio 后端下把 source/working/metadata
拉到请求级临时目录，登记到 contextvar，runner 经 resolve_imagery_paths 透明用临时路径；
执行后上传 results/* 回对象存储，再清理临时目录（异常路径也清，杜绝泄漏）。

不连真实 MinIO：用内存 fake store（实现 ObjectStore 协议子集），把
app.agent.tools.staging.get_object_store 打成返回它，验证拉取/上传/清理闭环。

五维覆盖（对齐 CLAUDE.md）：
- 常规：minio 后端 staging 拉取已存在文件、contextvar 注册临时目录、results 上传回存储；
- 边界：working/metadata 缺失时只拉 source（不报错）；results 为空时不上传；
- 非法输入：local 后端为纯 no-op，contextvar 始终为空（resolve 走原 imagery_root）；
- 异常分支（防泄漏，历史重复点）：staging 体内抛异常 → 临时目录仍被清理、不上传 results、
  contextvar 复原为退出前状态；
- 嵌套隔离：staging 退出后 contextvar 必须复原（不污染外层调用）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

import app.agent.tools.staging as staging
from app.agent.tools.staging import ArtifactPublicationError, ImageryStagingError, stage_imagery, staged_imagery_dir
from app.auth import user_scope

OWNER = "00000000-0000-4000-8000-000000000011"
OTHER_OWNER = "00000000-0000-4000-8000-000000000022"


class _FakeStore:
    """内存对象存储：key → bytes。实现 staging 用到的 exists/get_to/put。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[str] = []

    def seed(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def get_to(self, key: str, dest: Path) -> None:
        if key not in self.objects:
            raise FileNotFoundError(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.objects[key])

    async def put(self, key: str, path: Path) -> None:
        self.put_calls.append(key)
        self.objects[key] = Path(path).read_bytes()


@pytest.fixture(autouse=True)
def isolate_staging_tempdirs(monkeypatch, tmp_path):
    monkeypatch.setattr(staging, "tempfile", SimpleNamespace(
        mkdtemp=lambda **kwargs: tempfile.mkdtemp(dir=tmp_path, **kwargs),
    ))
    with user_scope(OWNER):
        yield


def fake_pool():
    @asynccontextmanager
    async def acquire():
        yield object()
    return SimpleNamespace(acquire=acquire)


@pytest.fixture
def minio_backend(monkeypatch):
    monkeypatch.setattr(staging, "get_settings", lambda: SimpleNamespace(storage_backend="minio", default_user_id=OWNER, database_enabled=True))
    monkeypatch.setattr(staging, "fetch_optional_pool", AsyncMock(return_value=fake_pool()))
    monkeypatch.setattr(staging, "db_get_imagery", AsyncMock(return_value={"owner_user_id": OWNER, "storage_backend": "minio"}))
    async def active_user(conn, *, user_id):
        return {"id": user_id, "is_active": True}
    monkeypatch.setattr(staging, "db_get_user", AsyncMock(side_effect=active_user))
    store = _FakeStore()
    monkeypatch.setattr(staging, "object_store_for", lambda backend: store)
    return store


@pytest.fixture
def local_backend(monkeypatch):
    monkeypatch.setattr(staging, "get_settings", lambda: SimpleNamespace(storage_backend="local", default_user_id=OWNER, database_enabled=False))
    monkeypatch.setattr(staging, "fetch_optional_pool", AsyncMock(return_value=None))
    monkeypatch.setattr(staging, "read_imagery_metadata", lambda _: {"owner_user_id": OWNER})


@pytest.mark.asyncio
async def test_local_backend_is_noop(local_backend) -> None:
    # 非法输入/回归：local 后端 staging 不动 contextvar，resolve 走原 imagery_root。
    assert staged_imagery_dir("94e758f38ede") is None
    async with stage_imagery("94e758f38ede"):
        assert staged_imagery_dir("94e758f38ede") is None
    assert staged_imagery_dir("94e758f38ede") is None


@pytest.mark.asyncio
async def test_minio_staging_pulls_files_and_registers_contextvar(minio_backend) -> None:
    # 常规：拉取已存在的 source/working/metadata 到临时目录，contextvar 指向它。
    store = minio_backend
    store.seed("94e758f38ede/source.tif", b"SRC")
    store.seed("94e758f38ede/working.tif", b"WORK")
    store.seed("94e758f38ede/metadata.json", b"{}")
    store.seed("94e758f38ede/quality.tif", b"QA")

    async with stage_imagery("94e758f38ede"):
        tmp_dir = staged_imagery_dir("94e758f38ede")
        assert tmp_dir is not None and tmp_dir.exists()
        assert (tmp_dir / "source.tif").read_bytes() == b"SRC"
        assert (tmp_dir / "working.tif").read_bytes() == b"WORK"
        assert (tmp_dir / "metadata.json").read_bytes() == b"{}"
        assert (tmp_dir / "quality.tif").read_bytes() == b"QA"
        captured = tmp_dir

    # 退出后 contextvar 复原、临时目录被清理。
    assert staged_imagery_dir("94e758f38ede") is None
    assert not captured.exists()


@pytest.mark.asyncio
async def test_minio_staging_only_pulls_existing(minio_backend) -> None:
    # 边界：只有 source 存在 → 只拉 source，working/metadata 缺失不报错。
    store = minio_backend
    store.seed("94e758f38ede/source.tif", b"SRC")

    async with stage_imagery("94e758f38ede"):
        tmp_dir = staged_imagery_dir("94e758f38ede")
        assert (tmp_dir / "source.tif").exists()
        assert not (tmp_dir / "working.tif").exists()
        assert not (tmp_dir / "metadata.json").exists()


@pytest.mark.asyncio
async def test_minio_staging_uploads_new_results(minio_backend) -> None:
    # 常规：容器在临时 results 目录新写入的文件，退出时上传回 {id}/results/*。
    store = minio_backend
    store.seed("94e758f38ede/source.tif", b"SRC")

    async with stage_imagery("94e758f38ede"):
        tmp_dir = staged_imagery_dir("94e758f38ede")
        (tmp_dir / "results" / "ndvi_colored.png").write_bytes(b"PNG")
        (tmp_dir / "results" / "ndvi.tif").write_bytes(b"TIF")

    assert "94e758f38ede/results/ndvi_colored.png" in store.put_calls
    assert "94e758f38ede/results/ndvi.tif" in store.put_calls
    assert store.objects["94e758f38ede/results/ndvi_colored.png"] == b"PNG"


@pytest.mark.asyncio
async def test_minio_staging_empty_results_no_upload(minio_backend) -> None:
    # 边界：results 目录为空 → 不发起任何 put（除拉取外零写回）。
    store = minio_backend
    store.seed("94e758f38ede/source.tif", b"SRC")

    async with stage_imagery("94e758f38ede"):
        pass

    assert store.put_calls == []


@pytest.mark.asyncio
async def test_minio_staging_cleans_up_on_exception(minio_backend) -> None:
    # 异常分支（防泄漏，历史重复点）：体内抛异常 → 临时目录仍清理、results 不上传、contextvar 复原。
    store = minio_backend
    store.seed("94e758f38ede/source.tif", b"SRC")
    captured: dict[str, Path] = {}

    with pytest.raises(RuntimeError, match="boom"):
        async with stage_imagery("94e758f38ede"):
            tmp_dir = staged_imagery_dir("94e758f38ede")
            captured["dir"] = tmp_dir
            # 即便写了 results，异常路径也不该上传（正常结束才上传）。
            (tmp_dir / "results" / "half.png").write_bytes(b"X")
            raise RuntimeError("boom")

    assert not captured["dir"].exists()          # 临时目录已清（不泄漏）
    assert store.put_calls == []                  # 异常路径不上传 results
    assert staged_imagery_dir("94e758f38ede") is None  # contextvar 复原


@pytest.mark.asyncio
async def test_minio_staging_preserves_tempdir_on_upload_failure(minio_backend, monkeypatch) -> None:
    # P1-5：runner 成功产出结果但上传对象存储失败时，不得抹掉临时目录（GPU 结果的唯一本地副本）。
    store = minio_backend
    store.seed("94e758f38ede/source.tif", b"SRC")
    monkeypatch.setattr(staging, "_UPLOAD_BACKOFF_SECONDS", 0.0)  # 重试不等，加速测试

    async def fail_put(key: str, path: Path) -> None:
        raise ConnectionError("simulated minio 5xx")

    monkeypatch.setattr(store, "put", fail_put)

    captured: dict[str, Path] = {}
    with pytest.raises(ArtifactPublicationError) as exc:
        async with stage_imagery("94e758f38ede"):
            tmp_dir = staged_imagery_dir("94e758f38ede")
            (tmp_dir / "results" / "ndvi.png").write_bytes(b"PNG")
            captured["dir"] = tmp_dir

    assert exc.value.code == "artifact_publication_failed"
    # 上传失败必须传递为失败，不能发布成功链接；临时目录仍保留（结果可恢复）。
    assert captured["dir"].exists()
    assert (captured["dir"] / "results" / "ndvi.png").read_bytes() == b"PNG"
    assert staged_imagery_dir("94e758f38ede") is None  # contextvar 仍复原


@pytest.mark.asyncio
async def test_minio_staging_restores_outer_contextvar(minio_backend) -> None:
    # 嵌套隔离：外层已有一个 staged 映射时，内层 staging 进出不破坏外层条目。
    store = minio_backend
    store.seed("aaaaaaaaaaaa/source.tif", b"A")
    store.seed("bbbbbbbbbbbb/source.tif", b"B")

    async with stage_imagery("aaaaaaaaaaaa"):
        outer = staged_imagery_dir("aaaaaaaaaaaa")
        assert outer is not None
        async with stage_imagery("bbbbbbbbbbbb"):
            # 内层期间两者都可见。
            assert staged_imagery_dir("aaaaaaaaaaaa") == outer
            assert staged_imagery_dir("bbbbbbbbbbbb") is not None
        # 内层退出：外层条目仍在、内层条目消失。
        assert staged_imagery_dir("aaaaaaaaaaaa") == outer
        assert staged_imagery_dir("bbbbbbbbbbbb") is None


@pytest.mark.asyncio
async def test_publication_retries_transient_failure_then_succeeds(minio_backend, monkeypatch):
    store = minio_backend
    monkeypatch.setattr(staging, "_UPLOAD_BACKOFF_SECONDS", 0)
    calls = 0
    original_put = store.put

    async def transient_put(key, path):
        nonlocal calls
        calls += 1
        if calls < staging._UPLOAD_RETRIES:
            raise ConnectionError("synthetic temporary publication failure")
        await original_put(key, path)

    monkeypatch.setattr(store, "put", transient_put)
    async with stage_imagery("aaaaaaaaaaaa"):
        captured = staged_imagery_dir("aaaaaaaaaaaa")
        (captured / "results" / "complete.tif").write_bytes(b"complete-result")
    assert calls == staging._UPLOAD_RETRIES
    assert store.objects["aaaaaaaaaaaa/results/complete.tif"] == b"complete-result"
    assert not captured.exists()
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_one_failed_file_fails_the_entire_publication(minio_backend, monkeypatch):
    store = minio_backend
    monkeypatch.setattr(staging, "_UPLOAD_BACKOFF_SECONDS", 0)
    original_put = store.put
    attempts = []

    async def partial_put(key, path):
        attempts.append(key)
        if key.endswith("missing.png"):
            raise ConnectionError("synthetic persistent publication failure")
        await original_put(key, path)

    monkeypatch.setattr(store, "put", partial_put)
    with pytest.raises(ArtifactPublicationError, match="artifact_publication_failed"):
        async with stage_imagery("aaaaaaaaaaaa"):
            captured = staged_imagery_dir("aaaaaaaaaaaa")
            (captured / "results" / "complete.tif").write_bytes(b"complete-result")
            (captured / "results" / "missing.png").write_bytes(b"complete-preview")
    assert attempts.count("aaaaaaaaaaaa/results/missing.png") == staging._UPLOAD_RETRIES
    assert (captured / "results" / "complete.tif").read_bytes() == b"complete-result"
    assert (captured / "results" / "missing.png").read_bytes() == b"complete-preview"
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_cancel_during_upload_retains_completed_results(minio_backend, monkeypatch):
    upload_started = asyncio.Event()
    captured = {}

    async def blocked_put(key, path):
        upload_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(minio_backend, "put", blocked_put)

    async def execute():
        async with stage_imagery("aaaaaaaaaaaa"):
            captured["root"] = staged_imagery_dir("aaaaaaaaaaaa")
            (captured["root"] / "results" / "complete.tif").write_bytes(b"complete-result")

    task = asyncio.create_task(execute())
    await upload_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (captured["root"] / "results" / "complete.tif").read_bytes() == b"complete-result"
    assert minio_backend.objects == {}
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_cancel_during_runner_cleans_unpublished_outputs(minio_backend):
    runner_started = asyncio.Event()
    captured = {}

    async def execute():
        async with stage_imagery("aaaaaaaaaaaa"):
            captured["root"] = staged_imagery_dir("aaaaaaaaaaaa")
            (captured["root"] / "results" / "partial.tif").write_bytes(b"partial")
            runner_started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(execute())
    await runner_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not captured["root"].exists()
    assert minio_backend.put_calls == []
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_concurrent_same_imagery_staging_is_isolated(minio_backend):
    ready = asyncio.Queue()
    release = asyncio.Event()
    captured = []

    async def execute(name, payload):
        async with stage_imagery("aaaaaaaaaaaa"):
            root = staged_imagery_dir("aaaaaaaaaaaa")
            captured.append(root)
            (root / "results" / name).write_bytes(payload)
            await ready.put(root)
            await release.wait()
            assert staged_imagery_dir("aaaaaaaaaaaa") == root

    tasks = [asyncio.create_task(execute("one.tif", b"one")), asyncio.create_task(execute("two.tif", b"two"))]
    await ready.get()
    await ready.get()
    assert captured[0] != captured[1]
    release.set()
    await asyncio.gather(*tasks)
    assert minio_backend.objects["aaaaaaaaaaaa/results/one.tif"] == b"one"
    assert minio_backend.objects["aaaaaaaaaaaa/results/two.tif"] == b"two"
    assert all(not root.exists() for root in captured)
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_cancel_during_source_staging_cleans_private_tempdir(minio_backend, monkeypatch):
    minio_backend.seed("aaaaaaaaaaaa/source.tif", b"source")
    download_started = asyncio.Event()
    captured = {}
    release = asyncio.Event()

    async def blocked_download(key, destination):
        captured["root"] = destination.parent
        download_started.set()
        await release.wait()

    monkeypatch.setattr(minio_backend, "get_to", blocked_download)

    async def execute():
        async with stage_imagery("aaaaaaaaaaaa"):
            pytest.fail("Cancelled staging must not start its runner")

    task = asyncio.create_task(execute())
    await download_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert captured["root"].exists()
    release.set()
    await wait_for_private_cleanup(captured["root"])
    assert minio_backend.put_calls == []
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_unexpected_publication_error_is_safe_and_retains_outputs(minio_backend, monkeypatch):
    async def broken_publication(*args):
        raise OSError("synthetic internal storage detail")

    monkeypatch.setattr(staging, "_upload_results", broken_publication)
    with pytest.raises(ArtifactPublicationError) as caught:
        async with stage_imagery("aaaaaaaaaaaa"):
            captured = staged_imagery_dir("aaaaaaaaaaaa")
            (captured / "results" / "complete.tif").write_bytes(b"complete-result")
    assert "synthetic internal storage detail" not in str(caught.value)
    assert caught.value.code == "artifact_publication_failed"
    assert isinstance(caught.value.__cause__, OSError)
    assert (captured / "results" / "complete.tif").read_bytes() == b"complete-result"
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_minio_row_is_staged_when_global_backend_is_local(minio_backend, monkeypatch):
    monkeypatch.setattr(staging, "get_settings", lambda: SimpleNamespace(storage_backend="local", default_user_id=OWNER, database_enabled=False))
    minio_backend.seed("aaaaaaaaaaaa/source.tif", b"owned MinIO source")
    async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
        root = staged_imagery_dir("aaaaaaaaaaaa")
        assert (root / "source.tif").read_bytes() == b"owned MinIO source"
        (root / "results" / "result.tif").write_bytes(b"result")
    assert minio_backend.objects["aaaaaaaaaaaa/results/result.tif"] == b"result"


@pytest.mark.asyncio
async def test_local_row_does_not_use_globally_configured_minio(minio_backend, monkeypatch):
    monkeypatch.setattr(staging, "db_get_imagery", AsyncMock(return_value={"owner_user_id": OWNER, "storage_backend": "local"}))
    store_getter = lambda backend: pytest.fail("A persisted local image must not access MinIO")
    monkeypatch.setattr(staging, "object_store_for", store_getter)
    async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
        assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_row_owner_denial_never_falls_back_to_local_cache(minio_backend, monkeypatch):
    monkeypatch.setattr(staging, "db_get_imagery", AsyncMock(return_value={"owner_user_id": OTHER_OWNER, "storage_backend": "minio"}))
    metadata = lambda _: pytest.fail("Foreign DB ownership must not fall back to local metadata")
    monkeypatch.setattr(staging, "read_imagery_metadata", metadata)
    with pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            pytest.fail("Foreign image runner must not execute")
    assert caught.value.code == "access_denied"
    assert minio_backend.put_calls == []
    staging.db_get_user.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("account", [None, {"is_active": False}])
async def test_db_owned_image_of_deleted_or_inactive_user_is_denied(minio_backend, monkeypatch, account):
    monkeypatch.setattr(staging, "db_get_user", AsyncMock(return_value=account))
    monkeypatch.setattr(staging, "object_store_for", lambda backend: pytest.fail("Inactive account must not download imagery"))
    with pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            pytest.fail("Inactive account runner must not execute")
    assert caught.value.code == "access_denied"


@pytest.mark.asyncio
async def test_backend_lookup_failure_is_not_reinterpreted_as_local(minio_backend, monkeypatch):
    monkeypatch.setattr(staging, "db_get_imagery", AsyncMock(side_effect=OSError("synthetic database error")))
    monkeypatch.setattr(staging, "read_imagery_metadata", lambda _: pytest.fail("Storage failure must not fall back"))
    with pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa"):
            pytest.fail("Unavailable storage must not execute a runner")
    assert caught.value.code == "storage_unavailable"


@pytest.mark.asyncio
async def test_invalid_persisted_backend_is_rejected(minio_backend, monkeypatch):
    monkeypatch.setattr(staging, "db_get_imagery", AsyncMock(return_value={"owner_user_id": OWNER, "storage_backend": "untrusted"}))
    with pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa"):
            pytest.fail("Unknown storage backend must not execute")
    assert caught.value.code == "storage_unavailable"


@pytest.mark.asyncio
async def test_no_row_legacy_local_image_stays_local_when_global_minio(minio_backend, monkeypatch):
    monkeypatch.setattr(staging, "db_get_imagery", AsyncMock(return_value=None))
    monkeypatch.setattr(staging, "read_imagery_metadata", lambda _: {"owner_user_id": OWNER})
    monkeypatch.setattr(staging, "object_store_for", lambda backend: pytest.fail("Legacy local image must not fetch MinIO"))
    async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
        assert staged_imagery_dir("aaaaaaaaaaaa") is None
    staging.db_get_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_database_development_owned_local_image_is_supported(local_backend, monkeypatch):
    monkeypatch.setattr(staging, "get_settings", lambda: SimpleNamespace(storage_backend="minio", default_user_id=OTHER_OWNER, database_enabled=False))
    # The legacy image explicitly belongs to this development user. They need
    # not be the default account or have a DB record when the DB is disabled.
    async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
        assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_legacy_foreign_metadata_is_rejected_without_db(local_backend, monkeypatch):
    monkeypatch.setattr(staging, "read_imagery_metadata", lambda _: {"owner_user_id": OTHER_OWNER})
    with pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            pytest.fail("Foreign legacy image must not execute")
    assert caught.value.code == "access_denied"


@pytest.mark.asyncio
async def test_orphan_minio_object_without_row_or_owned_metadata_is_rejected(minio_backend, monkeypatch):
    minio_backend.seed("aaaaaaaaaaaa/source.tif", b"orphan")
    monkeypatch.setattr(staging, "db_get_imagery", AsyncMock(return_value=None))
    monkeypatch.setattr(staging, "read_imagery_metadata", lambda _: None)
    with pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            pytest.fail("An orphan object is not an authorized image")
    assert caught.value.code == "access_denied"
    assert minio_backend.put_calls == []


@pytest.mark.asyncio
async def test_unbound_user_does_not_become_default_owner(local_backend):
    with user_scope(None), pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa"):
            pytest.fail("No current user must not inherit a default grant")
    assert caught.value.code == "access_denied"


@pytest.mark.asyncio
async def test_explicit_prepared_user_can_be_used_without_ambient_scope(local_backend):
    with user_scope(None):
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_explicit_user_must_not_disagree_with_bound_user(local_backend):
    with pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa", user_id=OTHER_OWNER):
            pytest.fail("Mismatched caller context must not execute")
    assert caught.value.code == "access_denied"


@pytest.mark.asyncio
async def test_concurrent_users_and_backends_do_not_share_staging(minio_backend, monkeypatch):
    async def lookup(conn, *, imagery_id):
        return {"owner_user_id": OWNER, "storage_backend": "minio"} if imagery_id == "aaaaaaaaaaaa" else {"owner_user_id": OTHER_OWNER, "storage_backend": "local"}
    monkeypatch.setattr(staging, "db_get_imagery", lookup)
    minio_backend.seed("aaaaaaaaaaaa/source.tif", b"first user's source")
    started = asyncio.Queue()
    release = asyncio.Event()
    observed = {}
    async def execute(user, image):
        with user_scope(user):
            async with stage_imagery(image, user_id=user):
                root = staged_imagery_dir(image)
                observed[user] = root
                if root is not None:
                    assert (root / "source.tif").read_bytes() == b"first user's source"
                await started.put(user)
                await release.wait()
                assert staged_imagery_dir("aaaaaaaaaaaa") is None if user == OTHER_OWNER else staged_imagery_dir("aaaaaaaaaaaa") == root
    tasks = [asyncio.create_task(execute(OWNER, "aaaaaaaaaaaa")), asyncio.create_task(execute(OTHER_OWNER, "bbbbbbbbbbbb"))]
    await started.get()
    await started.get()
    assert observed[OWNER] is not None and observed[OTHER_OWNER] is None
    release.set()
    await asyncio.gather(*tasks)
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_nested_other_user_cannot_see_inherited_staged_paths(minio_backend, monkeypatch):
    async def lookup(conn, *, imagery_id):
        if imagery_id == "aaaaaaaaaaaa":
            return {"owner_user_id": OWNER, "storage_backend": "minio"}
        return {"owner_user_id": OTHER_OWNER, "storage_backend": "local"}
    monkeypatch.setattr(staging, "db_get_imagery", lookup)
    minio_backend.seed("aaaaaaaaaaaa/source.tif", b"owner's private source")
    async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
        outer = staged_imagery_dir("aaaaaaaaaaaa")
        assert outer is not None
        with user_scope(OTHER_OWNER):
            assert staged_imagery_dir("aaaaaaaaaaaa") is None
            async with stage_imagery("bbbbbbbbbbbb", user_id=OTHER_OWNER):
                assert staged_imagery_dir("aaaaaaaaaaaa") is None
                assert staged_imagery_dir("bbbbbbbbbbbb") is None
        assert staged_imagery_dir("aaaaaaaaaaaa") == outer
    assert staged_imagery_dir("aaaaaaaaaaaa") is None


@pytest.mark.asyncio
async def test_explicit_minio_user_without_ambient_scope_can_resolve_own_stage(minio_backend):
    minio_backend.seed("aaaaaaaaaaaa/source.tif", b"private source")
    with user_scope(None):
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            root = staged_imagery_dir("aaaaaaaaaaaa")
            assert root is not None and (root / "source.tif").read_bytes() == b"private source"
        assert staged_imagery_dir("aaaaaaaaaaaa") is None


async def wait_for_private_cleanup(root):
    for _ in range(100):
        await asyncio.sleep(.01)
        if not root.exists():
            break
    assert not root.exists()
    # Let strong task registries discard completed cleanup callbacks.
    await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("fails_after_release", [False, True])
async def test_actual_threaded_adapter_cancel_cleans_after_file_closed(minio_backend, monkeypatch, fails_after_release):
    from app.storage.object_store import MinioStore
    opened = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    captured = {}
    class Missing(Exception):
        code = "NoSuchKey"
    class FakeSDK:
        def stat_object(self, bucket, key):
            if key.endswith("/source.tif"):
                return object()
            raise Missing()
        def fget_object(self, bucket, key, destination):
            target = Path(destination)
            captured["root"] = target.parent
            partial = Path(str(target) + ".part")
            with partial.open("wb") as handle:
                handle.write(b"started"); handle.flush()
                loop.call_soon_threadsafe(opened.set)
                assert release.wait(5)
                if fails_after_release:
                    raise OSError("synthetic SDK transfer failure after caller cancellation")
                handle.write(b"-completed")
            partial.replace(target)
    store = object.__new__(MinioStore)
    store._bucket = "synthetic-bucket"
    store._get_client = lambda: FakeSDK()
    monkeypatch.setattr(staging, "object_store_for", lambda backend: store)
    async def execute():
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            pytest.fail("Caller cancellation must not start a runner")
    task = asyncio.create_task(execute())
    try:
        await asyncio.wait_for(opened.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert captured["root"].exists()
        assert len(staging._transfers) >= 1
        assert staged_imagery_dir("aaaaaaaaaaaa") is None
    finally:
        release.set()
    await wait_for_private_cleanup(captured["root"])
    assert not staging._transfers and not staging._cleanups


@pytest.mark.asyncio
async def test_cancelled_transfer_cleanup_does_not_touch_parallel_stage(minio_backend, monkeypatch):
    first_opened = asyncio.Event()
    release_transfer = asyncio.Event()
    release_other = asyncio.Event()
    other_ready = asyncio.Event()
    captured = {}
    original = minio_backend.get_to
    minio_backend.seed("aaaaaaaaaaaa/source.tif", b"first")
    minio_backend.seed("bbbbbbbbbbbb/source.tif", b"second")
    async def get_to(key, destination):
        if key.startswith("aaaaaaaaaaaa/"):
            captured["first"] = destination.parent
            first_opened.set()
            await release_transfer.wait()
        await original(key, destination)
    monkeypatch.setattr(minio_backend, "get_to", get_to)
    async def first():
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            pytest.fail("Cancelled stage must not start its runner")
    async def second():
        async with stage_imagery("bbbbbbbbbbbb", user_id=OWNER):
            captured["second"] = staged_imagery_dir("bbbbbbbbbbbb")
            other_ready.set()
            await release_other.wait()
            assert (captured["second"] / "source.tif").read_bytes() == b"second"
    cancelled = asyncio.create_task(first())
    other = asyncio.create_task(second())
    await first_opened.wait(); await other_ready.wait()
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    release_transfer.set()
    await wait_for_private_cleanup(captured["first"])
    assert captured["second"].exists()
    release_other.set()
    await other
    assert not captured["second"].exists()


@pytest.mark.asyncio
async def test_enabled_database_with_failed_pool_never_reads_legacy_cache(local_backend, monkeypatch):
    monkeypatch.setattr(staging, "get_settings", lambda: SimpleNamespace(storage_backend="local", default_user_id=OWNER, database_enabled=True))
    monkeypatch.setattr(staging, "read_imagery_metadata", lambda _: pytest.fail("A configured but unavailable database must not grant legacy access"))
    with pytest.raises(ImageryStagingError) as caught:
        async with stage_imagery("aaaaaaaaaaaa", user_id=OWNER):
            pytest.fail("Unavailable identity storage must not start a runner")
    assert caught.value.code == "storage_unavailable"


@pytest.mark.asyncio
async def test_results_directory_creation_failure_cleans_allocated_root(minio_backend, monkeypatch, tmp_path):
    original_mkdir = Path.mkdir
    def fail_results_directory(path, *args, **kwargs):
        if path.name == "results" and path.parent.name.startswith("imagery_"):
            raise OSError("synthetic results directory failure")
        return original_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", fail_results_directory)
    minio_backend.exists = AsyncMock()
    with pytest.raises(OSError, match="synthetic results directory failure"):
        async with stage_imagery("94e758f38ede"):
            pytest.fail("Directory allocation failure must not start a runner")
    minio_backend.exists.assert_not_awaited()
    assert minio_backend.put_calls == []
    assert staged_imagery_dir("94e758f38ede") is None
    assert list(tmp_path.glob("imagery_*")) == []
