from __future__ import annotations

import json
from typing import Any

from app.db.sanitize import parse_jsonb, sanitize_json, sanitize_text


class ImageryOwnershipConflict(Exception):
    """同一 imagery_id 已属于其他用户。

    根因防线（#4）：upsert 绝不转移归属。冲突且非同属主时抛此异常，由上层
    （上传路由）转 5xx + 换新 id 重试，杜绝"导入/恢复/手动指定 id 时所有权被悄悄转移"。
    """

    def __init__(self, imagery_id: str) -> None:
        super().__init__(f"imagery_id already owned by another user: {imagery_id}")
        self.imagery_id = imagery_id


async def insert_imagery(
    conn,
    *,
    imagery_id: str,
    owner_user_id: str,
    workspace_id: str | None = None,
    filename: str | None = None,
    sha256: str | None = None,
    bounds: list[float] | None = None,
    bands: int | None = None,
    storage_backend: str = "local",
    metadata: dict[str, Any] | None = None,
) -> str:
    """写入一条影像归属记录。同 imagery_id 重传：仅当属主一致时覆盖元数据（幂等）；
    属主不一致 → 抛 ImageryOwnershipConflict（绝不转移归属，根因防线 #4）。

    实现：ON CONFLICT DO UPDATE ... WHERE owner_user_id = EXCLUDED.owner_user_id。
    WHERE 为假（他人持有）时冲突被当作 no-op，RETURNING 无行 → fetchrow 返 None → 抛冲突。
    owner_user_id 不在 SET 子句里——归属一旦写入即不可变。
    """
    row = await conn.fetchrow(
        """
        INSERT INTO public.imagery (
          imagery_id, owner_user_id, workspace_id, filename, sha256,
          bounds, bands, storage_backend, metadata
        )
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9::jsonb)
        ON CONFLICT (imagery_id) DO UPDATE
        SET workspace_id = EXCLUDED.workspace_id,
            filename = EXCLUDED.filename,
            sha256 = EXCLUDED.sha256,
            bounds = EXCLUDED.bounds,
            bands = EXCLUDED.bands,
            storage_backend = EXCLUDED.storage_backend,
            metadata = EXCLUDED.metadata
        WHERE public.imagery.owner_user_id = EXCLUDED.owner_user_id
        RETURNING id::text
        """,
        sanitize_text(imagery_id),
        owner_user_id,
        workspace_id,
        sanitize_text(filename) if filename else None,
        sanitize_text(sha256) if sha256 else None,
        json.dumps(bounds) if bounds is not None else None,
        bands,
        storage_backend,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
    )
    if row is None:
        # 冲突且 WHERE 为假 → imagery_id 已属他人，拒绝（不转移归属）。
        raise ImageryOwnershipConflict(imagery_id)
    return row["id"]


async def get_imagery(conn, *, imagery_id: str, owner_user_id: str | None = None) -> dict[str, Any] | None:
    """取单条影像记录。给 owner_user_id 时按归属过滤（鉴权用），否则不限（内部读元数据用）。"""
    owner_clause = "AND owner_user_id = $2" if owner_user_id else ""
    params: tuple[Any, ...] = (imagery_id, owner_user_id) if owner_user_id else (imagery_id,)
    row = await conn.fetchrow(
        f"""
        SELECT id::text, imagery_id, owner_user_id, workspace_id, filename, sha256,
               bounds, bands, storage_backend, metadata, created_at
        FROM public.imagery
        WHERE imagery_id = $1
        {owner_clause}
        """,
        *params,
    )
    return _row_to_dict(row) if row else None


async def list_imagery(conn, *, owner_user_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id::text, imagery_id, owner_user_id, workspace_id, filename, sha256,
               bounds, bands, storage_backend, metadata, created_at
        FROM public.imagery
        WHERE owner_user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        owner_user_id,
        limit,
    )
    return [_row_to_dict(row) for row in rows]


async def delete_imagery(conn, *, imagery_id: str, owner_user_id: str) -> bool:
    result = await conn.execute(
        "DELETE FROM public.imagery WHERE imagery_id = $1 AND owner_user_id = $2",
        imagery_id,
        owner_user_id,
    )
    return result.endswith(" 1")


def _row_to_dict(row) -> dict[str, Any]:
    """asyncpg Record → dict，并把 jsonb 列（读回为字符串）归一为 Python 对象。

    bounds/metadata 写入侧走 ::jsonb，asyncpg 未注册解码 codec 故读回是 JSON 字符串
    （见 sanitize.parse_jsonb 说明）。bounds 是 list、metadata 是 dict，分别归一。
    """
    data = dict(row)
    data["metadata"] = parse_jsonb(data.get("metadata")) or {}
    raw_bounds = data.get("bounds")
    if isinstance(raw_bounds, (str, bytes)):
        try:
            parsed = json.loads(raw_bounds)
        except (ValueError, TypeError):
            parsed = None
        data["bounds"] = parsed if isinstance(parsed, list) else None
    return data
