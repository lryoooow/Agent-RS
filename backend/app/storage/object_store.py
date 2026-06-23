"""对象存储抽象层：本地文件系统（默认）与 MinIO 两实现，按 settings.storage_backend 选择。

为什么要这层：
- 保留本地兜底＝不破坏已验证的 storage/imagery/ 逻辑，测试无需依赖 MinIO；
- storage_backend 字段支持逐景灰度（老影像 local、新影像 minio），平滑迁移；
- 工具取数"先拉临时目录再挂载"只依赖本抽象的 get_to，runner 与 docker 隔离不变。

Key 方案镜像现目录结构，可预测：
  {imagery_id}/source.tif、{imagery_id}/working.tif、
  {imagery_id}/metadata.json、{imagery_id}/results/ndvi_colored.png

注意：minio sdk 是同步阻塞的，本仓库是 asyncio，故所有 minio 调用经 asyncio.to_thread 包装
（与 imagery.py 上传链路 asyncio.to_thread(_extract_metadata, ...) 同范式），避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import AsyncIterator, Protocol

from app.core.paths import imagery_root
from app.core.settings import get_settings


class ObjectStore(Protocol):
    """影像二进制的存取契约。key 形如 "{imagery_id}/source.tif"。"""

    async def put(self, key: str, path: Path) -> None:
        """把本地文件 path 上传到 key（覆盖写）。"""
        ...

    async def get_to(self, key: str, dest: Path) -> None:
        """把 key 下载到本地 dest（供 rasterio/docker 读取）。key 不存在抛 FileNotFoundError。"""
        ...

    async def exists(self, key: str) -> bool:
        """key 是否存在。"""
        ...

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """以分块字节流读取 key（读端点代理流式用）。key 不存在抛 FileNotFoundError。"""
        ...

    async def delete_prefix(self, key_prefix: str) -> None:
        """删除 key_prefix 下所有对象（删整景影像用）。"""
        ...

    async def list_keys(self, key_prefix: str) -> list[str]:
        """列出 key_prefix 下所有对象 key（staging 拉取 results 用）。"""
        ...


_CHUNK_SIZE = 1024 * 1024
_NOT_FOUND_CODES = ("NoSuchKey", "NoSuchObject")


def _is_object_not_found(exc: Exception) -> bool:
    """判定 minio 异常是否表示"对象不存在"。

    按 .code 属性鸭子类型判，而非 isinstance(S3Error)：
    避免在异常处理里硬 import minio（未安装/测试 fake 时不该触发真实 import）；
    真实 minio.error.S3Error 与测试 fake 异常都带 .code，契约一致。
    """
    return getattr(exc, "code", None) in _NOT_FOUND_CODES


class LocalFileSystemStore:
    """本地文件系统实现：key 即 imagery_root 下的相对路径。封装现有 storage/imagery/ 行为。

    默认后端：行为与迁移前完全一致（回归保护）。同步文件 I/O 经 to_thread 包，与 minio 一致地不阻塞 loop。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or imagery_root(create=True)

    def _abs(self, key: str) -> Path:
        # key 用 posix 风格 '/' 分隔；Path 在 Windows 下也能正确解析。
        # 防穿越：解析后必须仍在 root 内（幻觉/恶意 key 含 ../ 时拒绝）。
        target = (self._root / key).resolve()
        root = self._root.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"非法对象 key（越出存储根）：{key}") from exc
        return target

    async def put(self, key: str, path: Path) -> None:
        dest = self._abs(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, str(path), str(dest))

    async def get_to(self, key: str, dest: Path) -> None:
        src = self._abs(key)
        if not src.exists():
            raise FileNotFoundError(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, str(src), str(dest))

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._abs(key).exists)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        src = self._abs(key)
        if not src.exists():
            raise FileNotFoundError(key)

        async def _iter() -> AsyncIterator[bytes]:
            # 文件句柄在线程里开/读/关；每块 read 经 to_thread 不阻塞 loop。
            handle = await asyncio.to_thread(open, src, "rb")
            try:
                while True:
                    chunk = await asyncio.to_thread(handle.read, _CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(handle.close)

        return _iter()

    async def delete_prefix(self, key_prefix: str) -> None:
        target = self._abs(key_prefix)
        await asyncio.to_thread(shutil.rmtree, target, True)  # ignore_errors=True

    async def list_keys(self, key_prefix: str) -> list[str]:
        base = self._abs(key_prefix)
        if not base.exists():
            return []
        root = self._root.resolve()

        def _walk() -> list[str]:
            return [
                p.resolve().relative_to(root).as_posix()
                for p in base.rglob("*")
                if p.is_file()
            ]

        return await asyncio.to_thread(_walk)


class MinioStore:
    """MinIO 实现。minio sdk 同步阻塞，全部经 to_thread 包装。

    懒建 client：避免 import 期连接、便于测试替换；endpoint/凭据来自 settings。
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.minio_bucket
        self._endpoint = settings.minio_endpoint
        self._access_key = settings.minio_access_key
        self._secret_key = settings.minio_secret_key
        self._secure = settings.minio_secure
        self._client = None

    def _get_client(self):
        if self._client is None:
            from minio import Minio

            self._client = Minio(
                self._endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
            )
        return self._client

    async def ensure_bucket(self) -> None:
        """幂等建桶（启动时调）。"""
        def _ensure() -> None:
            client = self._get_client()
            if not client.bucket_exists(self._bucket):
                client.make_bucket(self._bucket)

        await asyncio.to_thread(_ensure)

    async def put(self, key: str, path: Path) -> None:
        await asyncio.to_thread(
            lambda: self._get_client().fput_object(self._bucket, key, str(path))
        )

    async def get_to(self, key: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _download() -> None:
            try:
                self._get_client().fget_object(self._bucket, key, str(dest))
            except Exception as exc:
                if _is_object_not_found(exc):
                    raise FileNotFoundError(key) from exc
                raise

        await asyncio.to_thread(_download)

    async def exists(self, key: str) -> bool:
        def _stat() -> bool:
            try:
                self._get_client().stat_object(self._bucket, key)
                return True
            except Exception as exc:
                if _is_object_not_found(exc):
                    return False
                raise

        return await asyncio.to_thread(_stat)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        def _open():
            try:
                return self._get_client().get_object(self._bucket, key)
            except Exception as exc:
                if _is_object_not_found(exc):
                    raise FileNotFoundError(key) from exc
                raise

        response = await asyncio.to_thread(_open)

        async def _iter() -> AsyncIterator[bytes]:
            # urllib3 response：必须 close + release_conn 还连接，否则连接池泄漏。
            try:
                while True:
                    chunk = await asyncio.to_thread(response.read, _CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(response.close)
                await asyncio.to_thread(response.release_conn)

        return _iter()

    async def delete_prefix(self, key_prefix: str) -> None:
        def _delete() -> None:
            client = self._get_client()
            # 列出前缀下全部对象逐个删；recursive 列出所有层级。
            objects = client.list_objects(self._bucket, prefix=f"{key_prefix}/", recursive=True)
            for obj in objects:
                client.remove_object(self._bucket, obj.object_name)

        await asyncio.to_thread(_delete)

    async def list_keys(self, key_prefix: str) -> list[str]:
        def _list() -> list[str]:
            client = self._get_client()
            objects = client.list_objects(self._bucket, prefix=f"{key_prefix}/", recursive=True)
            return [obj.object_name for obj in objects]

        return await asyncio.to_thread(_list)


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    """返回当前后端的对象存储单例（懒初始化）。

    settings.storage_backend == 'minio' → MinioStore，否则 LocalFileSystemStore（默认）。
    单例避免重复建 minio client；reset_object_store 供测试切换后端。
    """
    global _store
    if _store is None:
        backend = get_settings().storage_backend.strip().lower()
        _store = MinioStore() if backend == "minio" else LocalFileSystemStore()
    return _store


def reset_object_store() -> None:
    """重置单例（测试切换后端 / teardown 用）。"""
    global _store
    _store = None


def object_store_for(backend: str) -> ObjectStore:
    """按指定后端返回对象存储实例（per-row 路由用，#3 根因修复）。

    与 get_object_store()（按全局 settings 选单例）不同：本函数按传入 backend 选，
    供读/删端点按每景 imagery 行的 storage_backend 列路由——全局后端切换（local↔minio）时，
    老影像/新影像各按自己写入时的真实后端读写，不致读 404 或漏删对象。

    minio：若全局单例恰为 MinioStore 则复用（连接池不浪费）；否则现建一个（lazy client，
    仅 mixed-mode 边缘场景走到，廉价）。local：直接 new（无状态、廉价）。
    """
    normalized = (backend or "local").strip().lower()
    if normalized == "minio":
        if isinstance(_store, MinioStore):
            return _store
        return MinioStore()
    return LocalFileSystemStore()
