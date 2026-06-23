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

from pathlib import Path

import pytest

import app.agent.tools.staging as staging
from app.agent.tools.staging import stage_imagery, staged_imagery_dir


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


@pytest.fixture
def minio_backend(monkeypatch):
    """切到 minio 后端 + fake store。返回 fake store 供断言。"""
    from app.core.settings import get_settings

    monkeypatch.setenv("STORAGE_BACKEND", "minio")
    get_settings.cache_clear()
    store = _FakeStore()
    monkeypatch.setattr(staging, "get_object_store", lambda: store)
    yield store
    get_settings.cache_clear()


@pytest.fixture
def local_backend(monkeypatch):
    from app.core.settings import get_settings

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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

    async with stage_imagery("94e758f38ede"):
        tmp_dir = staged_imagery_dir("94e758f38ede")
        assert tmp_dir is not None and tmp_dir.exists()
        assert (tmp_dir / "source.tif").read_bytes() == b"SRC"
        assert (tmp_dir / "working.tif").read_bytes() == b"WORK"
        assert (tmp_dir / "metadata.json").read_bytes() == b"{}"
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
