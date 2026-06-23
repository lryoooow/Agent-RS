"""影像归属与元数据访问：DB 优先 + 本地 metadata.json 兜底。

迁移背景（见 0007_imagery.sql）：租户隔离从"读本地 metadata.json 靠约定"升级为
"DB owner 查询"。但必须保留 json 兜底，原因：
- 老影像（迁移前上传）只有本地 metadata.json，无 DB 行；
- DATABASE_ENABLED=false 的纯算子调试场景无库；
- 现有 11 个 imagery API 测试用 TestClient 不连库，靠 metadata.json 校验 owner。
故策略：DB 可用且命中 → 用 DB（新影像走此路，修掉"靠约定"脆弱性）；
否则 → 回落到本地 metadata.json（原有逻辑，已验证，零行为变化）。

接口从同步改为 async：因为 DB 查询是 async，且三处调用方（tool_guards←child.py、
build_imagery_inventory←llm_planner/request_builder、report/builder）全在 async 上下文，
顺调用链 await 即可，无需在同步函数里 asyncio.run（那会在运行的 loop 里报错）。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.paths import imagery_root
from app.core.settings import get_settings
from app.db.errors import is_missing_schema_error
from app.db.pool import fetch_optional_pool
from app.db.repositories.imagery import get_imagery as _db_get_imagery
from app.db.repositories.imagery import list_imagery as _db_list_imagery

logger = logging.getLogger(__name__)

IMAGERY_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


# ───────────────────────── 本地 metadata.json 兜底（原有逻辑，保留）─────────────────────────
def read_imagery_metadata(imagery_id: str) -> dict[str, Any] | None:
    if not IMAGERY_ID_PATTERN.fullmatch(imagery_id):
        return None
    return read_metadata_file(imagery_root() / imagery_id / "metadata.json")


def read_metadata_file(meta_file: Path) -> dict[str, Any] | None:
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # 幻觉/不存在的 imagery_id 查找会高频走到这里（红队约 20% case）；只记一行原因，
        # 不带 exc_info——满栈 traceback 对"文件不存在"无诊断价值，徒增日志噪声。
        logger.warning("Invalid imagery metadata skipped: %s (%s)", meta_file, exc)
        return None


def imagery_owner_id(meta: dict[str, Any]) -> str:
    return str(meta.get("owner_user_id") or get_settings().default_user_id)


def _user_owns_imagery_from_disk(imagery_id: str, user_id: str) -> bool:
    meta = read_imagery_metadata(imagery_id)
    if meta is None:
        return False
    return imagery_owner_id(meta) == user_id


def _iter_user_imagery_metadata_from_disk(user_id: str) -> list[tuple[str, dict[str, Any]]]:
    root = imagery_root()
    if not root.exists():
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not IMAGERY_ID_PATTERN.fullmatch(entry.name):
            continue
        meta = read_metadata_file(entry / "metadata.json")
        if meta is None:
            continue
        if imagery_owner_id(meta) == user_id:
            items.append((entry.name, meta))
    return items


# ───────────────────────── DB 访问（优先）─────────────────────────
async def _db_lookup(imagery_id: str, user_id: str) -> dict[str, Any] | None:
    """查 DB 单条影像归属。返回 None 表示"DB 不可用或无此行"——交由上层决定是否兜底。"""
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            return await _db_get_imagery(conn, imagery_id=imagery_id, owner_user_id=user_id)
    except Exception as exc:
        if is_missing_schema_error(exc):
            return None  # imagery 表还没建（未跑迁移）→ 兜底
        logger.exception("Imagery owner DB lookup failed: %s", imagery_id)
        return None


async def _db_exists(imagery_id: str) -> bool:
    """imagery_id 是否在 DB 里存在（不限 owner）——用于判断该走 DB 还是兜底 json。"""
    pool = await fetch_optional_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            row = await _db_get_imagery(conn, imagery_id=imagery_id)
            return row is not None
    except Exception as exc:
        if not is_missing_schema_error(exc):
            logger.exception("Imagery existence DB check failed: %s", imagery_id)
        return False


# ───────────────────────── 公开接口（async，DB 优先 + json 兜底）─────────────────────────
async def user_owns_imagery(imagery_id: str, user_id: str | None) -> bool:
    """用户是否拥有该影像。

    DB 里存在此 imagery_id（不论归属）→ 以 DB 为准（命中 owner 才 True，租户隔离硬约束）；
    DB 里无此行（老影像/无库）→ 回落本地 metadata.json 校验。
    """
    if not user_id or not IMAGERY_ID_PATTERN.fullmatch(imagery_id):
        return False
    if await _db_exists(imagery_id):
        row = await _db_lookup(imagery_id, user_id)
        return row is not None
    return _user_owns_imagery_from_disk(imagery_id, user_id)


async def iter_user_imagery_metadata(user_id: str | None) -> list[tuple[str, dict[str, Any]]]:
    """列出用户全部影像 (imagery_id, metadata) 对。

    DB 有该用户的影像行 → 用 DB（metadata 列与旧 json 同构，调用方无感）；
    DB 空/不可用 → 回落本地扫描（老影像、无库场景）。
    两路按 imagery_id 去重合并：DB 优先，本地补充 DB 没有的老影像。
    """
    if not user_id:
        return []
    merged: dict[str, dict[str, Any]] = {}
    for imagery_id, meta in _iter_user_imagery_metadata_from_disk(user_id):
        merged[imagery_id] = meta
    pool = await fetch_optional_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await _db_list_imagery(conn, owner_user_id=user_id)
            for row in rows:
                # DB 的 metadata 列已存完整原 json；兼容性补 bands/imagery_id。
                meta = dict(row.get("metadata") or {})
                merged[row["imagery_id"]] = meta
        except Exception as exc:
            if not is_missing_schema_error(exc):
                logger.exception("Imagery inventory DB list failed for user %s", user_id)
    return sorted(merged.items())
