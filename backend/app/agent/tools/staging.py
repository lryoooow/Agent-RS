"""工具取数 staging：minio 后端下把影像拉到请求级临时目录供 rasterio/docker 读取。

为什么需要：10 个 runner 在调 call_tool 之前就直接读本地文件——
validate_band_indices 用 rasterio 打开 source 读波段数、read_bounds 读 metadata.json、
docker run -v 挂载本地目录。故 source/working/metadata 必须在 runner 整个生命周期本地可用，
不只是 docker 执行那一刻。

设计（最小侵入）：
- 锚点放在 resolve_imagery_paths（10 个 runner 的统一入口，在所有本地读取之前），
  而非 call_tool（那已晚于 validate_band_indices）。
- 用 contextvar 持有"当前影像目录覆盖"：staging 拉取后把临时目录写入 contextvar，
  resolve_imagery_paths 读到覆盖就用临时目录，runner 后续全部透明用临时路径，零改动。
- local 后端：纯 no-op，contextvar 为空，resolve_imagery_paths 走原逻辑，行为零变化。
- 生命周期：请求级临时目录，async with 进出，执行后上传容器新写入的 results/* 回对象存储，
  再清理临时目录（异常路径也清，与现有 per-call --rm 沙盒"用完即焚"哲学一致）。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import AsyncIterator

from app.core.settings import get_settings
from app.storage.object_store import get_object_store

logger = logging.getLogger(__name__)

# 当前工具调用的"影像本地目录覆盖"：imagery_id → 临时目录 Path。
# resolve_imagery_paths 读它决定用临时目录还是原 imagery_root 子目录。
_staged_dir: ContextVar[dict[str, Path] | None] = ContextVar("staged_imagery_dir", default=None)

# staging 时从对象存储拉取的影像文件（存在才拉，working/metadata 可能缺）。
_STAGE_FILES = ("source.tif", "working.tif", "metadata.json")
# 结果上传重试：minio 5xx/连接重置/配额等瞬时异常逐文件重试；全部失败则保留临时目录待恢复。
_UPLOAD_RETRIES = 3
_UPLOAD_BACKOFF_SECONDS = 0.5


def staged_imagery_dir(imagery_id: str) -> Path | None:
    """返回该 imagery_id 的临时目录覆盖（无 staging 时为 None）。"""
    mapping = _staged_dir.get()
    if mapping is None:
        return None
    return mapping.get(imagery_id)


@asynccontextmanager
async def stage_imagery(imagery_id: str) -> AsyncIterator[None]:
    """为一次工具调用 staging 影像（minio 后端）。local 后端为 no-op。

    进入：minio 后端时把 source/working/metadata 拉到临时目录，登记到 contextvar；
    退出：上传容器新写入的 results/* 回对象存储，清理临时目录（异常也清）。
    """
    settings = get_settings()
    if settings.storage_backend.strip().lower() != "minio":
        # 本地后端：什么都不做，resolve_imagery_paths 走原逻辑。
        yield
        return

    store = get_object_store()
    # mkdtemp 不自动清理：上传失败时保留临时目录（GPU 结果的唯一本地副本）供恢复，
    # 成功才 rmtree。改自 TemporaryDirectory——后者 GC/finally 会无条件抹掉，丢结果。
    tmp_root = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix=f"imagery_{imagery_id}_"))
    results_dir = tmp_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    runner_ok = False
    upload_ok = False
    try:
        # 拉取已存在的影像文件（source 必有；working/metadata 尽力）。
        for name in _STAGE_FILES:
            key = f"{imagery_id}/{name}"
            if await store.exists(key):
                await store.get_to(key, tmp_root / name)
        # 登记覆盖：复制现有映射再写，避免污染外层调用的 contextvar。
        current = dict(_staged_dir.get() or {})
        current[imagery_id] = tmp_root
        token = _staged_dir.set(current)
        try:
            yield
            runner_ok = True
        finally:
            _staged_dir.reset(token)
        # runner 正常结束：上传容器新写入的 results/* 回对象存储（带重试）。
        upload_ok = await _upload_results(store, imagery_id, results_dir)
    finally:
        if upload_ok or not runner_ok:
            # 上传成功，或 runner 自身异常（无成功结果可恢复）→ 清理，杜绝临时目录泄漏。
            await asyncio.to_thread(shutil.rmtree, tmp_root, ignore_errors=True)
        else:
            # runner 成功但上传失败：保留临时目录（GPU 结果的唯一本地副本）并告警，待恢复。
            logger.error(
                "影像结果未完整上传到对象存储，已保留临时目录待恢复：%s（imagery_id=%s）",
                tmp_root,
                imagery_id,
            )


async def _upload_results(store, imagery_id: str, results_dir: Path) -> bool:
    """把临时 results 目录下所有文件上传回对象存储 {imagery_id}/results/*。

    逐文件重试；返回是否全部成功。任一文件最终失败则返回 False，调用方据此保留临时目录，
    避免抹掉尚未完整落到对象存储的 GPU 结果。
    """
    if not results_dir.exists():
        return True
    all_ok = True
    for path in results_dir.glob("*"):
        if not path.is_file():
            continue
        key = f"{imagery_id}/results/{path.name}"
        uploaded = False
        for attempt in range(_UPLOAD_RETRIES):
            try:
                await store.put(key, path)
                uploaded = True
                break
            except Exception:
                logger.warning(
                    "上传 %s 第 %d/%d 次失败", key, attempt + 1, _UPLOAD_RETRIES, exc_info=True
                )
                if attempt < _UPLOAD_RETRIES - 1:
                    await asyncio.sleep(_UPLOAD_BACKOFF_SECONDS * (attempt + 1))
        if not uploaded:
            all_ok = False
    return all_ok
