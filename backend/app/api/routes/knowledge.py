from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.auth.current_user import get_current_user_id
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool
from app.knowledge.service import graph_view

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
_import_lock = asyncio.Lock()


@router.get("/graph")
async def get_graph(focus: str = Query(default="*", max_length=180)):
    if not get_settings().knowledge_graph_enabled:
        raise HTTPException(503, "知识图谱未启用")
    try:
        return await graph_view(get_current_user_id(), focus)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Knowledge graph read failed")
        raise HTTPException(503, "知识图谱暂不可用，请稍后刷新") from exc


@router.post("/retry")
async def retry_graph():
    pool = await fetch_optional_pool()
    if pool is None:
        raise HTTPException(503, "数据库不可用")
    async with pool.acquire() as conn:
        await conn.execute("UPDATE public.knowledge_graph_jobs SET status='pending',attempts=0,error_code=NULL,version=version+1,updated_at=now() WHERE user_id=$1 AND status='failed'", get_current_user_id())
    return {"queued": True}


@router.post("/guides")
async def import_guides():
    from app.api.routes.documents import _store_document_content
    user_id = get_current_user_id()
    pool = await fetch_optional_pool()
    if pool is None:
        raise HTTPException(503, "数据库不可用")
    root = Path(__file__).resolve().parents[4]
    paths = ["docs/agent-tool-architecture.md", "docs/knowledge-guide.md"]
    inserted = []
    async with _import_lock:
        for relative in paths:
            async with pool.acquire() as conn:
                exists = await conn.fetchval("SELECT id FROM public.documents WHERE created_by_user_id=$1 AND metadata->>'platform_guide'=$2", user_id, relative)
            if exists:
                continue
            content = (root / relative).read_text(encoding="utf-8")
            result = await _store_document_content(title=content.splitlines()[0].lstrip("# "), content=content,
                doc_type="markdown", source_url=None, metadata={"platform_guide": relative}, user_id=user_id)
            inserted.append(result.document_id)
    return {"inserted": inserted, "message": "平台指南已导入，图谱将在后台建立关联。"}
