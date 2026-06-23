"""对象存储抽象层测试：LocalFileSystemStore 真实文件往返 + MinioStore 用 fake client。

覆盖维度（对齐 CLAUDE.md 全维度要求）：
- 常规：put/get_to/exists/open_stream/list_keys/delete_prefix 往返一致；
- 边界：空前缀 list 返回 []、delete 不存在的前缀不报错、大文件分块流式；
- 非法输入：含 ../ 的越界 key 被拒（防穿越）；
- 异常分支：get_to/open_stream 对不存在的 key 抛 FileNotFoundError（统一契约，上层据此返 imagery_not_found）；
- 两后端契约一致：MinioStore 用 fake 内存 client 跑同一组语义断言，证明两实现可互换。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.object_store import LocalFileSystemStore, MinioStore


async def _drain(stream) -> bytes:
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


# ───────────────────────── LocalFileSystemStore ─────────────────────────
@pytest.mark.asyncio
async def test_local_put_get_roundtrip(tmp_path: Path) -> None:
    store = LocalFileSystemStore(root=tmp_path / "store")
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello-imagery")

    await store.put("abc123/source.tif", src)
    assert await store.exists("abc123/source.tif") is True

    dest = tmp_path / "out" / "source.tif"
    await store.get_to("abc123/source.tif", dest)
    assert dest.read_bytes() == b"hello-imagery"


@pytest.mark.asyncio
async def test_local_open_stream_reassembles_content(tmp_path: Path) -> None:
    store = LocalFileSystemStore(root=tmp_path / "store")
    src = tmp_path / "src.bin"
    payload = b"x" * (1024 * 1024 * 2 + 17)  # 跨 2 个多分块，验证分块拼接无丢字节
    src.write_bytes(payload)
    await store.put("k/big.tif", src)

    assert await _drain(await store.open_stream("k/big.tif")) == payload


@pytest.mark.asyncio
async def test_local_list_keys_and_delete_prefix(tmp_path: Path) -> None:
    store = LocalFileSystemStore(root=tmp_path / "store")
    for name in ("source.tif", "working.tif", "results/ndvi.png"):
        src = tmp_path / "tmp.bin"
        src.write_bytes(b"d")
        await store.put(f"img1/{name}", src)

    keys = sorted(await store.list_keys("img1"))
    assert keys == ["img1/results/ndvi.png", "img1/source.tif", "img1/working.tif"]

    await store.delete_prefix("img1")
    assert await store.list_keys("img1") == []
    assert await store.exists("img1/source.tif") is False


@pytest.mark.asyncio
async def test_local_get_missing_raises_file_not_found(tmp_path: Path) -> None:
    store = LocalFileSystemStore(root=tmp_path / "store")
    with pytest.raises(FileNotFoundError):
        await store.get_to("nope/source.tif", tmp_path / "x.tif")
    with pytest.raises(FileNotFoundError):
        await store.open_stream("nope/source.tif")


@pytest.mark.asyncio
async def test_local_empty_and_idempotent_edges(tmp_path: Path) -> None:
    store = LocalFileSystemStore(root=tmp_path / "store")
    assert await store.list_keys("ghost") == []  # 不存在前缀 → []
    await store.delete_prefix("ghost")  # 删不存在 → 不报错
    assert await store.exists("ghost/source.tif") is False


@pytest.mark.asyncio
async def test_local_rejects_path_traversal_key(tmp_path: Path) -> None:
    store = LocalFileSystemStore(root=tmp_path / "store")
    src = tmp_path / "s.bin"
    src.write_bytes(b"d")
    for bad in ("../escape.tif", "a/../../escape.tif"):
        with pytest.raises(ValueError):
            await store.put(bad, src)
        with pytest.raises(ValueError):
            await store.exists(bad)


# ───────────────────────── MinioStore（fake client）─────────────────────────
class _FakeS3Error(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _FakeMinioClient:
    """内存版 minio client：object_name → bytes。语义对齐真实 sdk 的 NoSuchKey 抛错。"""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.buckets: set[str] = set()

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        self.buckets.add(bucket)

    def fput_object(self, bucket: str, key: str, path: str) -> None:
        self.store[key] = Path(path).read_bytes()

    def fget_object(self, bucket: str, key: str, path: str) -> None:
        if key not in self.store:
            raise _FakeS3Error("NoSuchKey")
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(self.store[key])

    def stat_object(self, bucket: str, key: str):
        if key not in self.store:
            raise _FakeS3Error("NoSuchKey")
        return object()

    def get_object(self, bucket: str, key: str):
        if key not in self.store:
            raise _FakeS3Error("NoSuchKey")
        return _FakeResponse(self.store[key])

    def remove_object(self, bucket: str, key: str) -> None:
        self.store.pop(key, None)

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [_FakeObj(k) for k in list(self.store) if k.startswith(prefix)]


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.closed = False
        self.released = False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _FakeObj:
    def __init__(self, object_name: str) -> None:
        self.object_name = object_name


@pytest.fixture
def minio_store(monkeypatch) -> MinioStore:
    """构造一个绑定 fake client 的 MinioStore，避免连真实 MinIO。"""
    store = MinioStore()
    fake = _FakeMinioClient()
    monkeypatch.setattr(store, "_get_client", lambda: fake)
    store._bucket = "test-bucket"
    return store


@pytest.mark.asyncio
async def test_minio_ensure_bucket_idempotent(minio_store: MinioStore) -> None:
    await minio_store.ensure_bucket()
    await minio_store.ensure_bucket()  # 二次不报错
    assert minio_store._get_client().bucket_exists("test-bucket") is True


@pytest.mark.asyncio
async def test_minio_put_get_roundtrip(minio_store: MinioStore, tmp_path: Path) -> None:
    src = tmp_path / "src.tif"
    src.write_bytes(b"minio-bytes")
    await minio_store.put("img/source.tif", src)
    assert await minio_store.exists("img/source.tif") is True

    dest = tmp_path / "dl" / "source.tif"
    await minio_store.get_to("img/source.tif", dest)
    assert dest.read_bytes() == b"minio-bytes"


@pytest.mark.asyncio
async def test_minio_open_stream_and_release(minio_store: MinioStore, tmp_path: Path) -> None:
    src = tmp_path / "s.tif"
    src.write_bytes(b"abcdefg" * 1000)
    await minio_store.put("img/working.tif", src)

    fake = minio_store._get_client()
    response_holder = {}
    orig_get = fake.get_object

    def _capture(bucket, key):
        resp = orig_get(bucket, key)
        response_holder["resp"] = resp
        return resp

    fake.get_object = _capture
    data = await _drain(await minio_store.open_stream("img/working.tif"))
    assert data == b"abcdefg" * 1000
    # 连接必须 close + release（防 urllib3 连接池泄漏）
    assert response_holder["resp"].closed is True
    assert response_holder["resp"].released is True


@pytest.mark.asyncio
async def test_minio_missing_key_raises_file_not_found(minio_store: MinioStore, tmp_path: Path) -> None:
    assert await minio_store.exists("ghost/source.tif") is False
    with pytest.raises(FileNotFoundError):
        await minio_store.get_to("ghost/source.tif", tmp_path / "x.tif")
    with pytest.raises(FileNotFoundError):
        await minio_store.open_stream("ghost/source.tif")


@pytest.mark.asyncio
async def test_minio_list_and_delete_prefix(minio_store: MinioStore, tmp_path: Path) -> None:
    src = tmp_path / "s.tif"
    src.write_bytes(b"d")
    for name in ("source.tif", "results/ndvi.png"):
        await minio_store.put(f"imgX/{name}", src)

    keys = sorted(await minio_store.list_keys("imgX"))
    assert keys == ["imgX/results/ndvi.png", "imgX/source.tif"]

    await minio_store.delete_prefix("imgX")
    assert await minio_store.list_keys("imgX") == []
