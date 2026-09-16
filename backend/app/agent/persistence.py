from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TypeAlias

from app.agent.embedding.service import get_embedding_service
from app.agent.errors import AIError, map_provider_error
from app.agent.memory_judge import maybe_store_memory
from app.auth import get_current_user_id
from app.db.errors import is_missing_schema_error
from app.db.pool import fetch_optional_pool
from app.db.repositories.conversation import create_conversation, get_conversation, touch_conversation
from app.db.repositories.identity import ensure_default_identity
from app.db.repositories.message import (
    add_embedding_retry,
    append_message,
    set_embedding,
    update_message_complete,
)
from app.schemas.chat import ChatRequest
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

EmbeddingTarget: TypeAlias = tuple[str, str]

# 后台任务（embedding/memory）强引用集合：asyncio.create_task 只持弱引用，不持有则可能被 GC，
# 收尾逻辑跑不完（O1）。create 进集、done 出集。
_background_tasks: set[asyncio.Task] = set()


@dataclass
class PersistenceContext:
    user_id: str
    conversation_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    user_content: str = ""


async def prepare_persistence(
    request: ChatRequest,
    *,
    model_name: str,
    create_streaming_assistant: bool = False,
) -> PersistenceContext:
    user_id = get_current_user_id()
    context = PersistenceContext(user_id=user_id, user_content=latest_user_content(request))
    settings = get_settings()
    if not settings.storage_active:
        context.conversation_id = request.conversation_id
        return context

    pool = await fetch_optional_pool()
    if pool is None:
        context.conversation_id = request.conversation_id
        return context

    selection_metadata = {}
    if request.analysis_roi is not None:
        selection_metadata['analysis_roi'] = request.analysis_roi.model_dump(exclude_none=True)
        source = (request.metadata or {}).get('analysis_source')
        if source in {'current_map','selected_imagery'}:
            selection_metadata['analysis_source'] = source
    selected_id = (request.metadata or {}).get("active_imagery_id")
    if "active_imagery_id" in (request.metadata or {}) and selected_id is None:
        selection_metadata["active_imagery_id"] = None
    if isinstance(selected_id, str):
        from app.agent.imagery_access import user_owns_imagery
        if await user_owns_imagery(selected_id, user_id):
            selection_metadata["active_imagery_id"] = selected_id
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await ensure_default_identity(conn, settings)
                conversation_id = request.conversation_id
                if conversation_id and not await get_conversation(conn, conversation_id, user_id):
                    conversation_id = None
                if not conversation_id:
                    conversation_id = await create_conversation(
                        conn,
                        user_id=user_id,
                        settings=settings,
                        model_name=model_name,
                    )
                context.conversation_id = conversation_id
                context.user_message_id = await append_message(
                    conn,
                    conversation_id=conversation_id,
                    role="user",
                    content=context.user_content,
                    status="complete",
                    metadata=selection_metadata or None,
                )
                if create_streaming_assistant:
                    context.assistant_message_id = await append_message(
                        conn,
                        conversation_id=conversation_id,
                        role="assistant",
                        content="",
                        status="streaming",
                    )
                await touch_conversation(conn, conversation_id)
    except Exception as exc:
        if is_missing_schema_error(exc):
            raise AIError(
                "数据库 schema 未就绪，请运行 backend/sql/apply.py 并重启后端。",
                status_code=503,
            ) from exc
        # 操作性 DB 错误（死锁/连接掉/约束冲突）不再静默降级为无状态——否则整轮问答会被
        # 永久丢弃且客户端只收到 200。向上抛出 AIError(503)，由流式/非流式错误路径告知客户端本轮未保存。
        logger.exception("Database persistence setup failed; surfacing error (no silent stateless downgrade).")
        raise AIError("聊天持久化暂时不可用，请稍后重试。", status_code=503) from exc
    return context


async def save_assistant_response(
    persistence: PersistenceContext,
    *,
    content: str,
    usage: dict,
    finish_reason: str | None,
    active_imagery_id: str | None = None,
    geospatial_result: dict | None = None,
    tool_result: dict | None = None,
) -> str | None:
    if not persistence.conversation_id:
        return None
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            message_id = await append_message(
                conn,
                conversation_id=persistence.conversation_id,
                role="assistant",
                content=content,
                status="complete",
                metadata=_assistant_metadata(
                    finish_reason=finish_reason,
                    active_imagery_id=active_imagery_id,
                    geospatial_result=geospatial_result,
                    tool_result=tool_result,
                ),
                tokens_in=_optional_int(usage.get("input_tokens")),
                tokens_out=_optional_int(usage.get("output_tokens")),
            )
            await touch_conversation(conn, persistence.conversation_id)
            return message_id
    except Exception:
        logger.exception("Failed to save assistant response.")
        return None


async def save_streamed_assistant(
    persistence: PersistenceContext,
    *,
    content: str,
    done_payload: dict,
    geospatial_result: dict | None = None,
    tool_result: dict | None = None,
) -> None:
    if not persistence.assistant_message_id:
        return
    pool = await fetch_optional_pool()
    if pool is None:
        return
    usage = done_payload.get("usage") or {}
    try:
        async with pool.acquire() as conn:
            await update_message_complete(
                conn,
                message_id=persistence.assistant_message_id,
                content=content,
                status="complete",
                metadata=_assistant_metadata(
                    finish_reason=done_payload.get("finish_reason"),
                    active_imagery_id=done_payload.get("active_imagery_id"),
                    geospatial_result=geospatial_result,
                    tool_result=tool_result,
                ),
                tokens_in=_optional_int(usage.get("input_tokens")),
                tokens_out=_optional_int(usage.get("output_tokens")),
            )
            if persistence.conversation_id:
                await touch_conversation(conn, persistence.conversation_id)
    except Exception:
        logger.exception("Failed to save streamed assistant response.")


async def mark_assistant_failed(
    persistence: PersistenceContext, exc: Exception, *, content: str = ""
) -> None:
    pool = await fetch_optional_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            if persistence.assistant_message_id:
                await update_message_complete(
                    conn,
                    message_id=persistence.assistant_message_id,
                    content=content,
                    status="failed",
                    metadata=_failure_metadata(exc),
                )
            elif persistence.conversation_id:
                # 非流式路径未预建 assistant 行（O2）：失败时补一条 failed 行留痕，
                # 否则失败轮在库里无任何 assistant 记录、按 status='failed' 统计的监控永远为 0。
                persistence.assistant_message_id = await append_message(
                    conn,
                    conversation_id=persistence.conversation_id,
                    role="assistant",
                    content=content,
                    status="failed",
                    metadata=_failure_metadata(exc),
                )
    except Exception:
        logger.exception("Failed to mark assistant message as failed.")


def schedule_after_response(
    persistence: PersistenceContext,
    *,
    assistant_content: str,
) -> None:
    if not persistence.conversation_id:
        return
    embedding_targets: list[EmbeddingTarget] = [
        (message_id, content)
        for message_id, content in (
            (persistence.user_message_id, persistence.user_content),
            (persistence.assistant_message_id, assistant_content),
        )
        if message_id and content.strip()
    ]
    if embedding_targets:
        _track_background_task(
            asyncio.create_task(_embed_messages(embedding_targets)),
            "message embedding",
        )
    if persistence.assistant_message_id:
        _track_background_task(
            asyncio.create_task(
                maybe_store_memory(
                    user_id=persistence.user_id,
                    conversation_id=persistence.conversation_id,
                    user_content=persistence.user_content,
                    assistant_content=assistant_content,
                    source_message_id=persistence.assistant_message_id,
                )
            ),
            "memory extraction",
        )


def persistence_meta(persistence: PersistenceContext) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "conversation_id": persistence.conversation_id,
            "user_message_id": persistence.user_message_id,
            "assistant_message_id": persistence.assistant_message_id,
        }.items()
        if value
    }


def request_for_context(request: ChatRequest, persistence: PersistenceContext) -> ChatRequest:
    if not request.conversation_id:
        return request
    if request.conversation_id == persistence.conversation_id:
        return request
    return request.model_copy(update={"conversation_id": persistence.conversation_id})


def latest_user_content(request: ChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return request.messages[-1].content


def _failure_metadata(exc: Exception) -> dict[str, str]:
    """失败记录只保存类别，不落异常原文（供应商异常可能携带请求/响应正文）。"""
    return {
        "error_code": map_provider_error(exc).code,
        "error_type": type(exc).__name__,
    }


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _assistant_metadata(
    *,
    finish_reason: str | None,
    active_imagery_id: str | None = None,
    geospatial_result: dict | None,
    tool_result: dict | None,
) -> dict:
    """组装助手消息 metadata：在 finish_reason 之外，把结构化工具结果一并落库。

    地物分类/检测/NDVI 等结果此前只活在临时 SSE 卡片，下一轮无从回看，
    导致同对话内"否认已执行分析"。这里把它存进 metadata（写入侧 json_patch/`||` 合并），
    供 list_recent_analysis_results 跨轮回注与报告生成读取。None 值不写键，保持 metadata 精简。
    """
    metadata: dict = {"finish_reason": finish_reason}
    if active_imagery_id:
        metadata["active_imagery_id"] = active_imagery_id
    if geospatial_result:
        metadata["geospatial_result"] = geospatial_result
    if tool_result:
        metadata["tool_result"] = tool_result
    return metadata


async def _embed_messages(targets: list[EmbeddingTarget]) -> None:
    pool = await fetch_optional_pool()
    if pool is None:
        return
    message_ids = [message_id for message_id, _ in targets]
    contents = [content for _, content in targets]
    try:
        vectors = await get_embedding_service().embed_batch(contents)
    except Exception as exc:
        try:
            async with pool.acquire() as conn:
                for message_id in message_ids:
                    await add_embedding_retry(conn, message_id=message_id, error=str(exc))
        except Exception:
            logger.exception("Failed to enqueue embedding retry.")
        return
    if len(vectors) != len(message_ids):
        logger.error(
            "Embedding count mismatch; skipping message embedding save. expected=%s actual=%s",
            len(message_ids),
            len(vectors),
        )
        try:
            async with pool.acquire() as conn:
                for message_id in message_ids:
                    await add_embedding_retry(
                        conn,
                        message_id=message_id,
                        error=f"embedding_count_mismatch:{len(vectors)}",
                    )
        except Exception:
            logger.exception("Failed to enqueue embedding retry after count mismatch.")
        return
    try:
        async with pool.acquire() as conn:
            for message_id, vector in zip(message_ids, vectors, strict=True):
                await set_embedding(conn, message_id=message_id, embedding=vector)
    except Exception:
        logger.exception("Failed to save message embeddings.")


def _track_background_task(task: asyncio.Task, label: str) -> None:
    if not hasattr(task, "add_done_callback"):
        logger.debug("Background task handle has no callback support: %s", label)
        return

    _background_tasks.add(task)  # 强引用，防被 GC（asyncio 仅持弱引用）

    def _log_failure(done: asyncio.Task) -> None:
        _background_tasks.discard(done)
        try:
            done.result()
        except asyncio.CancelledError:
            logger.info("Background task cancelled: %s", label)
        except Exception:
            logger.exception("Background task failed: %s", label)

    task.add_done_callback(_log_failure)


async def drain_persistence_tasks(timeout: float = 10.0) -> None:
    """lifespan 关闭前排空 embedding/memory 后台任务（O1）。

    必须在 close_db_pool 之前调用：这些任务要用连接池，先排空再关池，否则任务因池已关而失败。
    """
    pending = [t for t in _background_tasks if not t.done()]
    if not pending:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True), timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Draining %d persistence background tasks timed out after %ss", len(pending), timeout
        )
