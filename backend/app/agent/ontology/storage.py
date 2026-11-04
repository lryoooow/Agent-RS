"""Personal ontology overlays. Writes use optimistic locking across workers."""
from __future__ import annotations

import json

from app.db.pool import fetch_optional_pool
from app.db.sanitize import parse_jsonb


class OntologyStorageUnavailable(RuntimeError):
    pass


class OntologyConflict(ValueError):
    pass


async def read_overlay(user_id: str) -> tuple[dict, int, bool]:
    pool = await fetch_optional_pool()
    if pool is None:
        return {}, 0, False
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT overlay, version FROM public.ontology_definitions WHERE user_id=$1", user_id)
        return (parse_jsonb(row["overlay"]) or {}, row["version"], True) if row else ({}, 0, True)
    except Exception as exc:
        raise OntologyStorageUnavailable("个人图谱存储暂不可用；请检查数据库与迁移。") from exc


async def save_overlay(user_id: str, overlay: dict, version: int) -> int:
    pool = await fetch_optional_pool()
    if pool is None:
        raise OntologyStorageUnavailable("保存定义需要启用数据库。")
    payload = json.dumps(overlay, ensure_ascii=False, allow_nan=False)
    try:
        async with pool.acquire() as conn:
            if version == 0:
                row = await conn.fetchrow("""INSERT INTO public.ontology_definitions(user_id,overlay)
                    VALUES($1,$2::jsonb) ON CONFLICT(user_id) DO NOTHING RETURNING version""", user_id, payload)
            else:
                row = await conn.fetchrow("""UPDATE public.ontology_definitions
                    SET overlay=$2::jsonb, version=version+1, updated_at=now()
                    WHERE user_id=$1 AND version=$3 RETURNING version""", user_id, payload, version)
    except Exception as exc:
        raise OntologyStorageUnavailable("图谱保存失败，请检查数据库与迁移。") from exc
    if row is None:
        raise OntologyConflict("图谱已在另一个页面更新，请刷新后合并修改。")
    return row["version"]
