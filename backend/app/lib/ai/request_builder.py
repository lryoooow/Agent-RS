import logging
import time
from dataclasses import dataclass

from app.lib.ai.context.assembler import assemble_context
from app.lib.ai.context.summarizer import build_context_summaries
from app.lib.ai.context.types import ContextAssembly
from app.lib.ai.embedding.service import get_embedding_service
from app.lib.ai.prompting.renderer import render_prompt_context
from app.lib.ai.rag.formatter import format_retrieved_blocks
from app.lib.ai.rag.mmr import mmr_select
from app.lib.ai.rerank import get_rerank_service
from app.lib.db.pool import fetch_optional_pool
from app.lib.db.repositories.memory import list_relevant_memories
from app.lib.db.repositories.message import list_recent_messages
from app.lib.db.repositories.vector_search import search_hybrid_rrf
from app.schemas.chat import ChatRequest
from app.shared.logging import log_event
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)


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
    query = _latest_user_text(request)
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
        messages=request.messages,
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
        imagery_inventory=_build_imagery_inventory(),
        max_total_chars=settings.context_max_total_chars,
        max_recent_chars=settings.ai_context_max_recent_chars,
        max_recent_messages=settings.context_max_recent_messages,
        max_user_extra_chars=settings.ai_context_max_user_extra_chars,
        max_summary_chars=settings.ai_context_max_summary_chars,
        max_memory_chars=settings.ai_context_max_memory_chars,
        max_rag_chars=settings.ai_context_max_rag_chars,
        max_tool_chars=settings.ai_context_max_tool_chars,
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
                limit=settings.context_max_recent_messages,
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
        async with pool.acquire() as conn:
            if request.use_memory and user_id:
                memories = await list_relevant_memories(
                    conn,
                    user_id=user_id,
                    embedding=embedding,
                    limit=settings.memory_retrieval_limit,
                )
                memory_context = format_retrieved_blocks(memories, title="memory")
            if request.use_rag:
                started = time.perf_counter()
                chunks = await search_hybrid_rrf(
                    conn,
                    embedding=embedding,
                    query=query,
                    limit=max(settings.rag_candidate_limit, settings.rag_retrieval_limit),
                    k=settings.rag_rrf_k,
                )
                rag_trace["candidates"] = len(chunks)
                rag_trace["recall_ms"] = int((time.perf_counter() - started) * 1000)
                started = time.perf_counter()
                chunks = await get_rerank_service().rerank(
                    query=query,
                    items=chunks,
                    top_n=(settings.rerank_top_n or settings.rag_retrieval_limit) + 3,
                )
                rag_trace["rerank_ms"] = int((time.perf_counter() - started) * 1000)
                if settings.rag_mmr_enabled:
                    chunks = mmr_select(
                        candidates=chunks,
                        query_embedding=embedding,
                        top_n=settings.rerank_top_n or settings.rag_retrieval_limit,
                        lambda_mult=settings.rag_mmr_lambda,
                    )
                    rag_trace["mmr_selected"] = len(chunks)
                else:
                    chunks = chunks[: settings.rerank_top_n or settings.rag_retrieval_limit]
                retrieved_chunks = sum(1 for chunk in chunks if str(chunk.get("content") or "").strip())
                rag_context = format_retrieved_blocks(chunks, title="document")
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


def _latest_user_text(request: ChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content.strip()
    return ""


async def build_planning_context(
    request: ChatRequest,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "判断用户是否需要联网搜索。只回复YES或NO，不要解释。\n"
                "YES：需要最新信息、实时数据、新闻、验证事实\n"
                "NO：闲聊、编程、写作、数学、已有上下文可答"
            ),
        }
    ]
    recent = request.messages[-3:] if len(request.messages) > 3 else request.messages
    for msg in recent:
        messages.append({"role": msg.role, "content": msg.content[:400]})
    return messages


def _build_imagery_inventory() -> str | None:
    """Build a brief inventory of uploaded imagery for LLM context."""
    import json
    from pathlib import Path

    settings = get_settings()
    root = Path(settings.imagery_upload_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / root
    if not root.exists():
        return None

    items: list[str] = []
    for entry in sorted(root.iterdir()):
        meta_file = entry / "metadata.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        items.append(
            f"- ID: {entry.name} | {meta.get('band_count', '?')}波段 "
            f"| {meta.get('width', '?')}x{meta.get('height', '?')}px "
            f"| CRS: {meta.get('crs', '未知')}"
        )

    if not items:
        return None
    return "可用影像:\n" + "\n".join(items)
