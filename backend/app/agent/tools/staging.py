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
  再清理临时目录；执行异常清理，发布失败或发布中取消保留完整结果供诊断。
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

from app.agent.imagery_access import IMAGERY_ID_PATTERN, read_imagery_metadata
from app.auth import peek_current_user_id
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool
from app.db.repositories.imagery import get_imagery as db_get_imagery
from app.db.repositories.auth import get_user_by_id as db_get_user
from app.storage.object_store import object_store_for

logger = logging.getLogger(__name__)


class ArtifactPublicationError(RuntimeError):
    """Inference finished, but its outputs are not durably available to users."""

    code = "artifact_publication_failed"

    def __init__(self) -> None:
        super().__init__(
            "artifact_publication_failed: 分析结果保存失败，尚未生成可用下载入口。"
        )

class ImageryStagingError(RuntimeError):
    """Storage/ownership changed after preparation; never try a different tenant."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


async def _imagery_backend(imagery_id: str, user_id: str | None) -> tuple[str, str]:
    current_user = peek_current_user_id()
    actor = user_id if user_id is not None else current_user
    if (not actor or not IMAGERY_ID_PATTERN.fullmatch(imagery_id)
            or (current_user is not None and user_id is not None and current_user != user_id)):
        raise ImageryStagingError("access_denied", "无法确认当前影像的访问权限。")
    try:
        pool = await fetch_optional_pool()
        if pool is None and getattr(get_settings(), "database_enabled", False):
            raise ImageryStagingError("storage_unavailable", "影像存储暂时不可用，本次未执行分析。")
        row = None
        if pool is not None:
            async with pool.acquire() as conn:
                row = await db_get_imagery(conn, imagery_id=imagery_id)
                if row is not None:
                    if str(row["owner_user_id"]) != actor:
                        raise ImageryStagingError("access_denied", "未找到该影像或无权访问。")
                    # A DB-owned image belongs to an account, not a cached claim.
                    # Reject deleted/disabled accounts before fetching any bytes.
                    user = await db_get_user(conn, user_id=actor)
                    if user is None or not user.get("is_active"):
                        raise ImageryStagingError("access_denied", "当前账户不可用，无法执行影像分析。")
    except ImageryStagingError:
        raise
    except Exception as exc:
        raise ImageryStagingError("storage_unavailable", "影像存储暂时不可用，本次未执行分析。") from exc
    if row is not None:
        backend = str(row.get("storage_backend") or "local").strip().lower()
        if backend not in {"local", "minio"}:
            raise ImageryStagingError("storage_unavailable", "影像存储配置不可用，本次未执行分析。")
        return backend, actor
    # Existing no-DB/development and legacy-image ownership semantics: only an
    # owned local metadata record permits access. No global MinIO guess can turn
    # an orphan/unowned object into an image (downloads also default to local).
    meta = await asyncio.to_thread(read_imagery_metadata, imagery_id)
    owner = str((meta or {}).get("owner_user_id") or get_settings().default_user_id)
    if meta is None or owner != actor:
        raise ImageryStagingError("access_denied", "未找到该影像或无权访问。")
    return "local", actor


# 当前工具调用的"影像本地目录覆盖"：imagery_id → 临时目录 Path。
# resolve_imagery_paths 读它决定用临时目录还是原 imagery_root 子目录。
_staged_dir: ContextVar[dict[str, tuple[str, Path]] | None] = ContextVar("staged_imagery_dir", default=None)
_staged_actor: ContextVar[str | None] = ContextVar("staged_imagery_actor", default=None)

# staging 时从对象存储拉取的影像文件（存在才拉，working/metadata 可能缺）。
_STAGE_FILES = ("source.tif", "working.tif", "metadata.json", "quality.tif")
# 结果上传重试：minio 5xx/连接重置/配额等瞬时异常逐文件重试；全部失败则保留临时目录待恢复。
_UPLOAD_RETRIES = 3
_UPLOAD_BACKOFF_SECONDS = 0.5
# Own non-cancellable SDK transfers and their deferred cleanup until completion.
# Cancellation stops the tool caller immediately; it cannot stop a running thread.
_transfers: set[asyncio.Task] = set()
_cleanups: set[asyncio.Task] = set()


async def _cleanup_stage_root(tmp_root: Path) -> None:
    # The exact absolute directory was resolved immediately after mkdtemp. A
    # later symlink replacement must not redirect recursive deletion elsewhere.
    if tmp_root.resolve() != tmp_root:
        logger.error("Refusing redirected staging cleanup: %s", tmp_root)
        return
    try:
        await asyncio.to_thread(shutil.rmtree, tmp_root)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Staging directory could not be cleaned: %s", tmp_root, exc_info=True)


def _cleanup_after_transfer(tmp_root: Path, transfer: asyncio.Task) -> None:
    def completed(task):
        if not task.cancelled():
            task.exception()  # The disconnected caller no longer observes it.
        cleanup = asyncio.create_task(_cleanup_stage_root(tmp_root), name="imagery-stage-cleanup")
        _cleanups.add(cleanup)
        cleanup.add_done_callback(_cleanups.discard)
    transfer.add_done_callback(completed)


def staged_imagery_dir(imagery_id: str) -> Path | None:
    """返回该 imagery_id 的临时目录覆盖（无 staging 时为 None）。"""
    mapping = _staged_dir.get()
    if mapping is None:
        return None
    entry = mapping.get(imagery_id)
    actor = peek_current_user_id() or _staged_actor.get()
    return entry[1] if entry is not None and entry[0] == actor else None


@asynccontextmanager
async def stage_imagery(imagery_id: str, *, user_id: str | None = None) -> AsyncIterator[None]:
    """为一次工具调用 staging 影像（minio 后端）。local 后端为 no-op。

    进入：minio 后端时把 source/working/metadata 拉到临时目录，登记到 contextvar；
    退出：完整上传后才算成功；上传失败抛明确错误，保留临时结果供诊断。
    """
    backend, actor = await _imagery_backend(imagery_id, user_id)
    actor_token = _staged_actor.set(actor)
    try:
        if backend == "local":
            # The owned image's persisted backend governs, including mixed deployments.
            yield
            return

        store = object_store_for(backend)
        # mkdtemp 不自动清理：上传失败时保留临时目录（GPU 结果的唯一本地副本）供恢复，
        # 成功才 rmtree。改自 TemporaryDirectory——后者 GC/finally 会无条件抹掉，丢结果。
        # One tiny directory allocation has no cancellable await: an abandoned
        # to_thread(mkdtemp) result could otherwise leak an untracked directory.
        tmp_root = Path(tempfile.mkdtemp(prefix=f"imagery_{imagery_id}_")).resolve()
        results_dir = tmp_root / "results"
        runner_ok = False
        upload_ok = False
        active_transfer = None
        try:
            results_dir.mkdir(parents=True, exist_ok=True)
            # 拉取已存在的影像文件（source 必有；working/metadata 尽力）。
            for name in _STAGE_FILES:
                key = f"{imagery_id}/{name}"
                if await store.exists(key):
                    task = asyncio.create_task(store.get_to(key, tmp_root / name))
                    _transfers.add(task)
                    task.add_done_callback(_transfers.discard)
                    active_transfer = task
                    try:
                        await asyncio.shield(task)
                    finally:
                        if task.done():
                            active_transfer = None
            # 登记覆盖：复制现有映射再写，避免污染外层调用的 contextvar。
            current = dict(_staged_dir.get() or {})
            current[imagery_id] = (actor, tmp_root)
            token = _staged_dir.set(current)
            try:
                yield
                runner_ok = True
            finally:
                _staged_dir.reset(token)
            # A normally returned runner is not a published result. Never allow the
            # caller to persist complete or expose links before every upload succeeds.
            try:
                upload_ok = await _upload_results(store, imagery_id, results_dir)
            except asyncio.CancelledError:
                # The completed local outputs are the only recoverable copy. Keep
                # them in finally, and propagate cancellation to the owning task.
                raise
            except Exception as exc:
                raise ArtifactPublicationError() from exc
            if not upload_ok:
                raise ArtifactPublicationError()
        finally:
            if upload_ok or not runner_ok:
                # 上传成功，或 runner 自身异常（无成功结果可恢复）→ 清理，杜绝临时目录泄漏。
                if active_transfer is not None and not active_transfer.done():
                    # SDK get_to may still hold an open .part file on Windows.
                    # Wait for that private transfer before cleaning, without
                    # waiting in or resuming the cancelled tool/runner itself.
                    _cleanup_after_transfer(tmp_root, active_transfer)
                else:
                    await _cleanup_stage_root(tmp_root)
            else:
                # runner 成功但上传失败：保留临时目录（GPU 结果的唯一本地副本）并告警，待恢复。
                logger.error(
                    "影像结果未完整上传到对象存储，已保留临时目录待恢复：%s（imagery_id=%s）",
                    tmp_root,
                    imagery_id,
                )
    finally:
        _staged_actor.reset(actor_token)


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
