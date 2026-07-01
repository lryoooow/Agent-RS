import logging
import time
import asyncio
import math
from dataclasses import dataclass

from app.agent.imagery_access import iter_user_imagery_metadata
from app.agent.context.analysis_summary import summarize_persisted_analyses
from app.agent.context.assembler import assemble_context
from app.agent.context.history import normalize_chat_message_for_provider
from app.agent.context.summarizer import build_context_summaries
from app.agent.context.types import ContextAssembly
from app.agent.embedding.service import get_embedding_service
from app.agent.geocode import cached_location, format_location_context, prefetch_location
from app.agent.prompting.renderer import render_prompt_context
from app.agent.prompting.scenarios import latest_user_text
from app.agent.rag.formatter import format_retrieved_blocks
from app.agent.rag.service import retrieve_rag_context
from app.db.pool import fetch_optional_pool
from app.db.repositories.document import list_documents
from app.db.repositories.memory import list_relevant_memories
from app.db.repositories.message import list_recent_analysis_results, list_recent_messages
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
    query = latest_user_text(request.messages)

    # 并行执行所有独立的异步操作，减少总延迟
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
            # skip_retrieval 时仍需并行查询其他上下文
            messages, prior_analysis_results, geo_context, imagery_inventory, document_inventory = await asyncio.gather(
                _resolve_context_messages(request, user_id=user_id),
                _resolve_prior_analysis_results(request, user_id=user_id),
                _resolve_geo_context(request),
                build_imagery_inventory(user_id),
                build_document_inventory(user_id),
            )
        else:
            # 并行执行：历史消息、先验结果、地理上下文、RAG/记忆检索、影像清单
            messages, prior_analysis_results, geo_context, retrieved_context, imagery_inventory, document_inventory = await asyncio.gather(
                _resolve_context_messages(request, user_id=user_id),
                _resolve_prior_analysis_results(request, user_id=user_id),
                _resolve_geo_context(request),
                _resolve_retrieved_context(request, query=query, user_id=user_id),
                build_imagery_inventory(user_id),
                build_document_inventory(user_id),
            )
    else:
        # retrieved_context 已提供，只并行其他操作
        messages, prior_analysis_results, geo_context, imagery_inventory, document_inventory = await asyncio.gather(
            _resolve_context_messages(request, user_id=user_id),
            _resolve_prior_analysis_results(request, user_id=user_id),
            _resolve_geo_context(request),
            build_imagery_inventory(user_id),
            build_document_inventory(user_id),
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
        prior_analysis_results=prior_analysis_results,
        # 影像清单始终注入答复上下文（与 planner 一贯注入保持一致）。
        # 此前用 `if tool_context` 门控，导致未跑工具的轮次（如"根据刚才结果生成报告"
        # 这类纯追问）答复模型看不到影像，误判"用户没上传影像"。
        # build_imagery_inventory 无影像时返回 None，无影像用户零开销。
        imagery_inventory=imagery_inventory,
        document_inventory=document_inventory,
        geo_context=geo_context,
        max_total_chars=settings.context_max_total_chars,
        max_recent_chars=settings.ai_context_max_recent_chars,
        max_recent_messages=settings.context_max_recent_messages,
        max_user_extra_chars=settings.ai_context_max_user_extra_chars,
        max_summary_chars=settings.ai_context_max_summary_chars,
        max_memory_chars=settings.ai_context_max_memory_chars,
        max_rag_chars=settings.ai_context_max_rag_chars,
        max_tool_chars=settings.ai_context_max_tool_chars,
        max_prior_results_chars=settings.ai_context_max_prior_results_chars,
        max_imagery_chars=settings.ai_context_max_imagery_chars,
        max_document_chars=settings.ai_context_max_document_chars,
        max_geo_chars=settings.ai_context_max_geo_chars,
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
    if not settings.storage_active or not request.conversation_id:
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
                user_id=user_id,
            )
        if not messages:
            return request.messages
        return _merge_ephemeral_system_hints(messages, request.messages)
    except Exception:
        return request.messages


def _merge_ephemeral_system_hints(persisted_messages: list, request_messages: list) -> list:
    """Insert current-request system hints before the latest persisted user message."""
    existing_contents = {
        message.content
        for message in persisted_messages
        if getattr(message, "role", None) == "system"
    }
    hints = [
        message
        for message in request_messages
        if message.role == "system" and message.content not in existing_contents
    ]
    if not hints:
        return persisted_messages

    insert_at = next(
        (
            index
            for index in range(len(persisted_messages) - 1, -1, -1)
            if persisted_messages[index].role == "user"
        ),
        len(persisted_messages),
    )
    return [*persisted_messages[:insert_at], *hints, *persisted_messages[insert_at:]]


async def _resolve_prior_analysis_results(request: ChatRequest, *, user_id: str | None) -> str | None:
    """读本对话此前持久化的结构化分析结果，整形成可注入答复上下文的中文摘要。

    跨轮回注的核心：让"根据刚才的分类结果生成报告""那张图分析过吗"这类未跑工具的追问轮，
    也能看到本对话真实执行过的工具结果，根治"同对话否认已执行分析"。
    无 conversation_id / 无 user_id / 无存储 / 查询异常 → 返回 None（不注入，不报错）。
    """
    settings = get_settings()
    if not settings.storage_active or not request.conversation_id or not user_id:
        return None
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            results = await list_recent_analysis_results(
                conn,
                conversation_id=request.conversation_id,
                user_id=user_id,
                limit=settings.memory_retrieval_limit,
            )
        return summarize_persisted_analyses(results)
    except Exception:
        return None


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
    if not settings.storage_active or not query or not (request.use_memory or request.use_rag):
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


async def build_imagery_inventory(user_id: str | None) -> str | None:
    """Build a brief inventory of uploaded imagery for LLM context."""
    items: list[str] = []
    for imagery_id, meta in await iter_user_imagery_metadata(user_id):
        items.append(
            f"- ID: {imagery_id} | {meta.get('band_count', '?')}波段 "
            f"| {meta.get('width', '?')}x{meta.get('height', '?')}px "
            f"| CRS: {meta.get('crs') or '未知'}"
        )

    if not items:
        return None
    return "可用影像:\n" + "\n".join(items)


async def build_document_inventory(user_id: str | None) -> str | None:
    """Build an owner-filtered document inventory for planner and answer context."""
    if not user_id or not get_settings().storage_active:
        return None
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            documents = await list_documents(
                conn,
                user_id=user_id,
                limit=get_settings().agent_document_inventory_limit,
            )
    except Exception:
        logger.debug("Document inventory lookup failed.", exc_info=True)
        return None
    if not documents:
        return None
    return "用户已上传需要解析的文档:\n" + "\n".join(
        f"- ID: {document['id']} | 标题: {document.get('title') or '未命名'} "
        f"| 类型: {document.get('doc_type') or '未知'} | 分块: {document.get('chunk_count', 0)}"
        for document in documents
    )


async def _resolve_geo_context(request: ChatRequest) -> str | None:
    """
    从请求 metadata 提取地图上下文，调用逆地理编码服务，返回位置描述文本。

    前端需传递 metadata.map_context: { center: [lon, lat], zoom: number, annotations?: [...] }
    """
    if not request.metadata:
        return None

    map_ctx = request.metadata.get("map_context")
    if not map_ctx or not isinstance(map_ctx, dict):
        return None

    center = map_ctx.get("center")
    zoom = map_ctx.get("zoom")
    annotations = map_ctx.get("annotations")

    if not center or not isinstance(center, (list, tuple)) or len(center) < 2:
        return None

    try:
        lon, lat = float(center[0]), float(center[1])
        zoom_int = int(zoom) if zoom is not None else None
    except (ValueError, TypeError):
        logger.warning(f"Invalid map_context coordinates: {center}")
        return None
    if (
        not math.isfinite(lon)
        or not math.isfinite(lat)
        or not (-180 <= lon <= 180)
        or not (-90 <= lat <= 90)
    ):
        logger.warning("Out-of-range map_context coordinates: %s", center)
        return None

    # 地名仅从缓存读取；未命中时后台预取，当前请求立即使用坐标兜底。
    location = cached_location(lat, lon, zoom=zoom_int)
    if location is None:
        prefetch_location(lat, lon)

    # 格式化为上下文文本
    context_parts = [format_location_context(location, fallback_coords=(lat, lon))]

    # 添加标注信息
    if annotations and isinstance(annotations, list) and len(annotations) > 0:
        annotation_summary = _format_annotations(annotations[:100])
        if annotation_summary:
            context_parts.append(annotation_summary)

    return "\n\n".join(filter(None, context_parts))


def _format_annotations(annotations: list) -> str | None:
    """
    格式化用户在地图上绘制的标注为可读文本。

    标注格式为 GeoJSON Feature：
    - Polygon: 多边形区域
    - Point: 点标记
    - LineString: 线段（可用于测距）
    """
    if not annotations:
        return None

    summary_parts = ["**用户在地图上标注的区域/位置：**\n"]

    for i, feature in enumerate(annotations, 1):
        if not isinstance(feature, dict):
            continue

        geometry = feature.get("geometry", {})
        geo_type = geometry.get("type")
        coordinates = geometry.get("coordinates")

        if not geo_type or not coordinates:
            continue

        try:
            if geo_type == "Polygon":
                # 多边形：显示顶点数和大致范围
                if coordinates and len(coordinates) > 0:
                    points = coordinates[0]
                    lons = [p[0] for p in points if len(p) >= 2]
                    lats = [p[1] for p in points if len(p) >= 2]
                    if lons and lats:
                        bbox = [min(lons), min(lats), max(lons), max(lats)]
                        summary_parts.append(
                            f"{i}. 多边形区域：{len(points)}个顶点，范围 [{bbox[0]:.4f}, {bbox[1]:.4f}] 至 [{bbox[2]:.4f}, {bbox[3]:.4f}]"
                        )

            elif geo_type == "Point":
                # 点标记：显示坐标
                if len(coordinates) >= 2:
                    lon, lat = coordinates[0], coordinates[1]
                    summary_parts.append(f"{i}. 点标记：经度 {lon:.4f}, 纬度 {lat:.4f}")

            elif geo_type == "LineString":
                valid_points = [
                    (float(point[0]), float(point[1]))
                    for point in coordinates
                    if isinstance(point, (list, tuple))
                    and len(point) >= 2
                    and math.isfinite(float(point[0]))
                    and math.isfinite(float(point[1]))
                ]
                if len(valid_points) >= 2:
                    start = valid_points[0]
                    end = valid_points[-1]
                    distance = sum(
                        _haversine_km(first, second)
                        for first, second in zip(valid_points, valid_points[1:])
                    )
                    summary_parts.append(
                        f"{i}. 线段：起点 [{start[0]:.4f}, {start[1]:.4f}] → 终点 [{end[0]:.4f}, {end[1]:.4f}]，约 {distance:.2f} km"
                    )
        except (IndexError, TypeError, ValueError):
            continue

    if len(summary_parts) == 1:
        return None

    return "\n".join(summary_parts)


def _haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(value)))
