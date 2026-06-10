import logging
import time
import asyncio
from dataclasses import dataclass

from app.agent.imagery_access import iter_user_imagery_metadata
from app.agent.context.assembler import assemble_context
from app.agent.context.history import normalize_chat_message_for_provider
from app.agent.context.summarizer import build_context_summaries
from app.agent.context.types import ContextAssembly
from app.agent.embedding.service import get_embedding_service
from app.agent.prompting.renderer import render_prompt_context
from app.agent.prompting.scenarios import latest_user_text
from app.agent.rag.formatter import format_retrieved_blocks
from app.agent.rag.service import retrieve_rag_context
from app.db.pool import fetch_optional_pool
from app.db.repositories.memory import list_relevant_memories
from app.db.repositories.message import list_recent_messages
from app.db.repositories.vector_search import search_hybrid_rrf
from app.schemas.chat import ChatRequest
from app.core.logging import log_event
from app.core.settings import get_settings

logger = logging.getLogger(__name__)
PLANNING_CONTEXT_RECENT_MESSAGES = 3
PLANNING_CONTEXT_MESSAGE_CHARS = 400


@dataclass(frozen=True)
class RetrievedContext:
    memory_context: str | None = None
    rag_context: str | None = None
    retrieved_chunks: int = 0
    rag_trace: dict | None = None


@dataclass(frozen=True)
class ProviderRequestContext:
    context: ContextAssembly
    messages: list[dict[str, str]]
    retrieved_chunks: int = 0
    rag_trace: dict | None = None
    retrieved_context: RetrievedContext | None = None


async def build_provider_context(request: ChatRequest, *, user_id: str | None = None) -> ContextAssembly:
    return (await build_provider_request_context(request, user_id=user_id)).context


async def build_provider_request_context(
    request: ChatRequest,
    *,
    user_id: str | None = None,
    tool_context: str | None = None,
    retrieved_context: RetrievedContext | None = None,
    skip_retrieval: bool = False,
) -> ProviderRequestContext:
    settings = get_settings()
    messages = await _resolve_context_messages(request, user_id=user_id)
    query = latest_user_text(request.messages)
    if retrieved_context is None:
        if skip_retrieval:
            retrieved_context = RetrievedContext(
                rag_trace={
                    "use_rag": request.use_rag,
                    "use_memory": request.use_memory,
                    "skipped": True,
                    "reason": "direct_chat_route",
                }
            )
        else:
            retrieved_context = await _resolve_retrieved_context(
                request,
                query=query,
                user_id=user_id,
            )
    memory_context = retrieved_context.memory_context
    rag_context = retrieved_context.rag_context
    retrieved_chunks = retrieved_context.retrieved_chunks
    rag_trace = retrieved_context.rag_trace
    summaries = build_context_summaries(
        messages,
        max_recent_messages=settings.context_max_recent_messages,
        max_recent_chars=settings.ai_context_max_recent_chars,
        max_summary_chars=settings.ai_context_max_summary_chars,
        max_memory_chars=settings.ai_context_max_memory_chars,
    )
    prompt_context = render_prompt_context(
        messages=messages,
        profile=settings.ai_prompt_profile,
        language=settings.ai_system_prompt_language,
        assistant_name=settings.ai_assistant_name,
        enable_dynamic_modules=settings.ai_prompt_enable_dynamic_modules,
        include_reasoning_boundary=settings.ai_prompt_include_reasoning_boundary,
        has_conversation_summary=bool(summaries.conversation_summary),
        has_memory=bool(summaries.memory),
        has_rag_context=bool(rag_context),
        has_tool_context=bool(tool_context),
        max_core_chars=settings.ai_prompt_max_core_chars,
        max_optional_chars=settings.ai_prompt_max_optional_chars,
    )
    context = assemble_context(
        system_prompt=prompt_context.content,
        system_prompt_blocks=prompt_context.included_blocks,
        dropped_prompt_blocks=prompt_context.dropped_blocks,
        messages=messages,
        user_extra_instructions=(
            request.system_prompt if settings.allow_user_extra_instructions else None
        ),
        conversation_summary=summaries.conversation_summary,
        memory=memory_context or summaries.memory,
        rag_context=rag_context,
        tool_context=tool_context,
        imagery_inventory=(
            build_imagery_inventory(user_id)
            if tool_context
            else None
        ),
        max_total_chars=settings.context_max_total_chars,
        max_recent_chars=settings.ai_context_max_recent_chars,
        max_recent_messages=settings.context_max_recent_messages,
        max_user_extra_chars=settings.ai_context_max_user_extra_chars,
        max_summary_chars=settings.ai_context_max_summary_chars,
        max_memory_chars=settings.ai_context_max_memory_chars,
        max_rag_chars=settings.ai_context_max_rag_chars,
        max_tool_chars=settings.ai_context_max_tool_chars,
        max_imagery_chars=settings.ai_context_max_imagery_chars,
    )
    return ProviderRequestContext(
        context=context,
        messages=context.messages,
        retrieved_chunks=retrieved_chunks,
        rag_trace=rag_trace,
        retrieved_context=retrieved_context,
    )


async def build_provider_messages(request: ChatRequest, *, user_id: str | None = None) -> list[dict[str, str]]:
    return (await build_provider_request_context(request, user_id=user_id)).messages


async def _resolve_context_messages(request: ChatRequest, *, user_id: str | None) -> list:
    settings = get_settings()
    if not settings.database_enabled or not request.conversation_id:
        return request.messages
    pool = await fetch_optional_pool()
    if pool is None:
        return request.messages
    try:
        async with pool.acquire() as conn:
            messages = await list_recent_messages(
                conn,
                conversation_id=request.conversation_id,
                limit=settings.context_max_loaded_messages,
            )
        return messages or request.messages
    except Exception:
        return request.messages


async def _resolve_retrieved_context(
    request: ChatRequest,
    *,
    query: str,
    user_id: str | None,
) -> RetrievedContext:
    settings = get_settings()
    log_event(
        logger,
        "rag.query",
        use_rag=request.use_rag,
        use_memory=request.use_memory,
        query_chars=len(query),
    )
    if not settings.database_enabled or not query or not (request.use_memory or request.use_rag):
        return RetrievedContext(rag_trace={"use_rag": request.use_rag, "use_memory": request.use_memory})
    pool = await fetch_optional_pool()
    if pool is None:
        return RetrievedContext(rag_trace={"use_rag": request.use_rag, "use_memory": request.use_memory})
    try:
        started = time.perf_counter()
        embedding = await get_embedding_service().embed_text(query)
        embedding_ms = int((time.perf_counter() - started) * 1000)
    except Exception:
        return RetrievedContext(rag_trace={"use_rag": request.use_rag, "use_memory": request.use_memory})

    memory_context: str | None = None
    rag_context: str | None = None
    retrieved_chunks = 0
    rag_trace: dict = {
        "use_rag": request.use_rag,
        "use_memory": request.use_memory,
        "query_chars": len(query),
        "embedding_ms": embedding_ms,
        "candidates": 0,
        "rerank_ms": None,
        "mmr_selected": None,
        "context_chars": 0,
    }
    try:
        can_parallel = bool(
            request.use_memory
            and user_id
            and request.use_rag
            and settings.database_pool_max_size >= 2
        )
        if can_parallel:
            memory_context, rag_payload = await asyncio.gather(
                _load_memory_context(pool, user_id=user_id, embedding=embedding),
                _load_rag_context(pool, query=query, embedding=embedding, user_id=user_id, rag_trace=rag_trace),
            )
            rag_context, retrieved_chunks = rag_payload
            rag_trace["parallel"] = True
        else:
            if request.use_memory and user_id:
                memory_context = await _load_memory_context(pool, user_id=user_id, embedding=embedding)
            if request.use_rag:
                rag_context, retrieved_chunks = await _load_rag_context(
                    pool,
                    query=query,
                    embedding=embedding,
                    user_id=user_id,
                    rag_trace=rag_trace,
                )
            rag_trace["parallel"] = False
    except Exception:
        return RetrievedContext(rag_trace=rag_trace)
    log_event(
        logger,
        "rag.context",
        retrieved_chunks=retrieved_chunks,
        context_chars=len(rag_context or ""),
    )
    rag_trace["retrieved_chunks"] = retrieved_chunks
    rag_trace["context_chars"] = len(rag_context or "")
    return RetrievedContext(
        memory_context=memory_context,
        rag_context=rag_context,
        retrieved_chunks=retrieved_chunks,
        rag_trace=rag_trace,
    )


async def _load_memory_context(pool, *, user_id: str, embedding: list[float]) -> str | None:
    settings = get_settings()
    async with pool.acquire() as conn:
        memories = await list_relevant_memories(
            conn,
            user_id=user_id,
            embedding=embedding,
            limit=settings.memory_retrieval_limit,
        )
    return format_retrieved_blocks(memories, title="memory")


async def _load_rag_context(
    pool,
    *,
    query: str,
    embedding: list[float],
    user_id: str | None,
    rag_trace: dict,
) -> tuple[str | None, int]:
    result = await retrieve_rag_context(
        pool,
        query=query,
        embedding=embedding,
        user_id=user_id,
        trace=rag_trace,
        search_fn=search_hybrid_rrf,
    )
    return result.context, result.retrieved_chunks


async def build_planning_context(
    request: ChatRequest,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    recent = (
        request.messages[-PLANNING_CONTEXT_RECENT_MESSAGES:]
        if len(request.messages) > PLANNING_CONTEXT_RECENT_MESSAGES
        else request.messages
    )
    for msg in recent:
        provider_msg = normalize_chat_message_for_provider(msg)
        messages.append(
            {
                "role": provider_msg["role"],
                "content": provider_msg["content"][:PLANNING_CONTEXT_MESSAGE_CHARS],
            }
        )
    return messages


def build_imagery_inventory(user_id: str | None) -> str | None:
    """Build a brief inventory of uploaded imagery for LLM context."""
    items: list[str] = []
    for imagery_id, meta in iter_user_imagery_metadata(user_id):
        items.append(
            f"- ID: {imagery_id} | {meta.get('band_count', '?')}波段 "
            f"| {meta.get('width', '?')}x{meta.get('height', '?')}px "
            f"| CRS: {meta.get('crs') or '未知'}"
        )

    if not items:
        return None
    return "可用影像:\n" + "\n".join(items)
