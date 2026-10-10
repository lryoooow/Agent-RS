"""HNSW 按用户过滤的召回保障（G9，2026-10-10）。

背景：pgvector 的 HNSW 索引扫描先取 ``ef_search``（默认 40）个近邻候选，
再套用户过滤——当查询用户在候选池里占比很低时，过滤后不足 ``LIMIT``，即"按用户过滤后 HNSW 漏召回"。
pgvector >= 0.8 提供 ``hnsw.iterative_scan``：过滤后不足 LIMIT 时自动继续
迭代扫描，直到取满或达到上限，从根本上消除该缺陷。

本模块按服务器实际 pgvector 版本选择策略：
- >= 0.8：在查询所在事务内 ``SET LOCAL hnsw.iterative_scan = relaxed_order``，
  让计划器无论何时选中 HNSW 计划都安全（顺序为近似序，分值仍按行精确计算）。
- < 0.8 或未安装 vector 扩展：没有 iterative_scan 可用。调大
  ``hnsw.ef_search``（40 → 400）扩大候选池缓解过滤后不足；若返回行数仍少于
  ``limit``，回退到精确扫描 SQL（MATERIALIZED 先物化租户数据再排序），
  保证旧版本上召回不回退。正解是升级 pgvector >= 0.8（compose 已钉
  pgvector/pgvector:0.8.3-pg16）。
- 版本探测结果按进程缓存（``SELECT extversion FROM pg_extension`` 很稳定，
  运行期不会变化；进程重启后重新探测）。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ITERATIVE_SCAN_MIN_VERSION = (0, 8)
EF_SEARCH_FALLBACK = 400  # <0.8 时的候选池大小：默认 40 的 10 倍

_version_cache: dict[str, Any] = {"probed": False, "version": None}


def _parse_extversion(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    parts: list[int] = []
    for piece in text.strip().split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts) if parts else None


async def pgvector_version(conn) -> tuple[int, ...] | None:
    """探测服务器 pgvector 版本（进程内缓存）。未安装扩展 → None。"""
    if not _version_cache["probed"]:
        row = await conn.fetchrow(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        )
        _version_cache["probed"] = True
        _version_cache["version"] = _parse_extversion(row["extversion"] if row else None)
    return _version_cache["version"]


async def fetch_tenant_nearest(
    conn,
    *,
    sql_index: str,
    sql_exact: str,
    params: tuple,
    limit: int,
) -> list[Any]:
    """租户过滤的近邻检索：按 pgvector 版本套用召回保障后执行。

    ``sql_index``：索引友好形（用户过滤放 WHERE、``ORDER BY embedding <=>
    $q LIMIT n``），计划器可选 HNSW，也可退化为精确扫描——两种计划下
    结果集都完整。
    ``sql_exact``：精确扫描形（MATERIALIZED 先物化租户数据再排序），
    仅在旧版 pgvector 索引路径返回不足 limit 时兜底。
    两条 SQL 的占位符布局必须一致。
    """
    version = await pgvector_version(conn)
    if version is not None and version >= ITERATIVE_SCAN_MIN_VERSION:
        # SET LOCAL 必须在事务内才生效：包一层事务，结束后自动还原，
        # 不污染归还到池里的连接。调用方若已在事务中，这里只是 SAVEPOINT。
        async with conn.transaction():
            await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            return await conn.fetch(sql_index, *params)

    if version is None:
        # 未装 vector 扩展：没有 HNSW，直接精确扫描。
        return await conn.fetch(sql_exact, *params)

    # pgvector < 0.8：调大候选池缓解；不足 limit 时回退精确扫描保召回。
    async with conn.transaction():
        await conn.execute(f"SET LOCAL hnsw.ef_search = {EF_SEARCH_FALLBACK}")
        rows = await conn.fetch(sql_index, *params)
        if len(rows) < limit:
            logger.warning(
                "pgvector %s lacks iterative_scan; index path returned %d/%d rows, "
                "falling back to exact tenant scan",
                ".".join(map(str, version)),
                len(rows),
                limit,
            )
            rows = await conn.fetch(sql_exact, *params)
        return rows
