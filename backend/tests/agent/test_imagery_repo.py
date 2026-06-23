"""影像归属 DB 仓储 + DB 优先鉴权 的 PostgreSQL 集成测试。

跑在 docker compose 的 pgvector/pg16 上（复用全局 pg_pool/pg_conn 夹具；库不可达整组 skip）。
对照 tests/ai/test_tool_guards.py（那组锁死 fetch_optional_pool=None 走磁盘兜底），
本组反过来把 fetch_optional_pool 指向真实测试池，验证"DB 有行 → 以 DB owner 为准"这条
租户隔离硬约束路径，根除 deep-audit-2026-06-17 标记的"租户隔离靠约定"脆弱性。

五维覆盖（对齐 CLAUDE.md）：
- 常规：insert/get/list/delete 往返；DB-first owner 命中放行；
- 边界：list 空集、owner 过滤只返本人、delete 不存在返 False；
- 非法输入：幻觉 imagery_id（不在 DB）→ user_owns_imagery 走磁盘兜底（无文件即 False）；
- 异常分支：ON CONFLICT 同属主重传覆盖元数据（幂等）；他人持有 → 拒绝转移归属（#4 防线）；
- 历史重复点（租户隔离靠约定）：用户 A 持用户 B 的 imagery_id → DB owner 查询拒绝（核心防线）。
"""
from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.db.repositories._pg import imagery as imagery_repo

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_A = "00000000-0000-4000-8000-00000000000a"
_USER_B = "00000000-0000-4000-8000-00000000000b"


def _settings() -> Settings:
    return Settings(_env_file=None)


def _wrap(pool):
    """把就绪 pool 包成 awaitable，匹配 fetch_optional_pool 的 async 调用约定。"""
    async def _inner():
        return pool
    return _inner()


# ───────────────────────── 仓储层 CRUD ─────────────────────────
async def test_insert_get_roundtrip(pg_conn) -> None:
    # 常规：写入后按 imagery_id 取回，字段（owner/bounds/bands/metadata）一致还原。
    new_id = await imagery_repo.insert_imagery(
        pg_conn,
        imagery_id="aaaaaaaaaaaa",
        owner_user_id=_USER_A,
        filename="scene.tif",
        sha256="deadbeef",
        bounds=[100.0, 20.0, 100.5, 20.5],
        bands=4,
        storage_backend="minio",
        metadata={"filename": "scene.tif", "owner_user_id": _USER_A, "band_count": 4},
    )
    assert new_id

    row = await imagery_repo.get_imagery(pg_conn, imagery_id="aaaaaaaaaaaa")
    assert row is not None
    assert row["owner_user_id"] == _USER_A
    assert row["filename"] == "scene.tif"
    assert row["bounds"] == [100.0, 20.0, 100.5, 20.5]
    assert row["bands"] == 4
    assert row["storage_backend"] == "minio"
    assert row["metadata"]["band_count"] == 4


async def test_get_with_owner_filter_enforces_isolation(pg_conn) -> None:
    # 历史重复点（租户隔离靠约定）：带 owner 过滤时，他人 owner 查不到（核心防线）。
    await imagery_repo.insert_imagery(
        pg_conn, imagery_id="bbbbbbbbbbbb", owner_user_id=_USER_A, metadata={}
    )
    assert await imagery_repo.get_imagery(pg_conn, imagery_id="bbbbbbbbbbbb", owner_user_id=_USER_A) is not None
    assert await imagery_repo.get_imagery(pg_conn, imagery_id="bbbbbbbbbbbb", owner_user_id=_USER_B) is None
    # 不带 owner（内部读元数据用）→ 仍能取到行。
    assert await imagery_repo.get_imagery(pg_conn, imagery_id="bbbbbbbbbbbb") is not None


async def test_list_imagery_only_returns_owner_rows(pg_conn) -> None:
    # 边界 + 隔离：list 只返属主影像，他人影像不出现。
    await imagery_repo.insert_imagery(pg_conn, imagery_id="a1a1a1a1a1a1", owner_user_id=_USER_A, metadata={})
    await imagery_repo.insert_imagery(pg_conn, imagery_id="a2a2a2a2a2a2", owner_user_id=_USER_A, metadata={})
    await imagery_repo.insert_imagery(pg_conn, imagery_id="b1b1b1b1b1b1", owner_user_id=_USER_B, metadata={})

    rows_a = await imagery_repo.list_imagery(pg_conn, owner_user_id=_USER_A)
    ids_a = {r["imagery_id"] for r in rows_a}
    assert ids_a == {"a1a1a1a1a1a1", "a2a2a2a2a2a2"}

    assert await imagery_repo.list_imagery(pg_conn, owner_user_id="nobody-user") == []


async def test_insert_conflict_same_owner_updates_metadata_idempotent(pg_conn) -> None:
    # 幂等：同属主重传同 imagery_id → 覆盖元数据/文件名，归属不变（不抛重复键）。
    await imagery_repo.insert_imagery(
        pg_conn, imagery_id="cccccccccccc", owner_user_id=_USER_A,
        filename="old.tif", metadata={"v": 1},
    )
    await imagery_repo.insert_imagery(
        pg_conn, imagery_id="cccccccccccc", owner_user_id=_USER_A,
        filename="new.tif", metadata={"v": 2},
    )
    row = await imagery_repo.get_imagery(pg_conn, imagery_id="cccccccccccc")
    assert row["owner_user_id"] == _USER_A
    assert row["filename"] == "new.tif"
    assert row["metadata"]["v"] == 2


async def test_insert_conflict_cross_owner_rejected_no_theft(pg_conn) -> None:
    # 根因防线（#4）：他人已持有该 imagery_id → 重传不得转移归属，抛 ImageryOwnershipConflict；
    # 原属主、文件名、元数据均不被篡改（杜绝所有权悄悄转移）。
    from app.db.repositories._pg.imagery import ImageryOwnershipConflict

    await imagery_repo.insert_imagery(
        pg_conn, imagery_id="cccccccccccc", owner_user_id=_USER_A,
        filename="old.tif", metadata={"v": 1},
    )
    with pytest.raises(ImageryOwnershipConflict):
        await imagery_repo.insert_imagery(
            pg_conn, imagery_id="cccccccccccc", owner_user_id=_USER_B,
            filename="hijack.tif", metadata={"v": 99},
        )
    # 归属与内容原封不动。
    row = await imagery_repo.get_imagery(pg_conn, imagery_id="cccccccccccc")
    assert row["owner_user_id"] == _USER_A
    assert row["filename"] == "old.tif"
    assert row["metadata"]["v"] == 1


async def test_delete_imagery_owner_scoped(pg_conn) -> None:
    # 常规 + 边界：删本人影像返 True；删他人/不存在返 False（不误删）。
    await imagery_repo.insert_imagery(pg_conn, imagery_id="dddddddddddd", owner_user_id=_USER_A, metadata={})

    assert await imagery_repo.delete_imagery(pg_conn, imagery_id="dddddddddddd", owner_user_id=_USER_B) is False
    assert await imagery_repo.get_imagery(pg_conn, imagery_id="dddddddddddd") is not None  # 没被误删

    assert await imagery_repo.delete_imagery(pg_conn, imagery_id="dddddddddddd", owner_user_id=_USER_A) is True
    assert await imagery_repo.get_imagery(pg_conn, imagery_id="dddddddddddd") is None

    assert await imagery_repo.delete_imagery(pg_conn, imagery_id="ffffffffffff", owner_user_id=_USER_A) is False


# ───────────────────────── DB 优先鉴权（imagery_access）─────────────────────────
async def test_user_owns_imagery_db_first_grants_owner(pg_conn, pg_pool, monkeypatch) -> None:
    # 核心：DB 有此 imagery 行 → 以 DB owner 为准，命中放行、未命中拒绝（不再回落磁盘）。
    import app.agent.imagery_access as access

    monkeypatch.setattr(access, "fetch_optional_pool", lambda: _wrap(pg_pool))
    await imagery_repo.insert_imagery(pg_conn, imagery_id="e1e1e1e1e1e1", owner_user_id=_USER_A, metadata={})

    assert await access.user_owns_imagery("e1e1e1e1e1e1", _USER_A) is True
    assert await access.user_owns_imagery("e1e1e1e1e1e1", _USER_B) is False


async def test_user_owns_imagery_hallucinated_id_denied(pg_pool, monkeypatch) -> None:
    # 非法输入（红队防线）：幻觉 imagery_id 不在 DB → _db_exists False → 走磁盘兜底；
    # 无本地文件 → False（既不放行也不崩）。
    import app.agent.imagery_access as access

    monkeypatch.setattr(access, "fetch_optional_pool", lambda: _wrap(pg_pool))
    assert await access.user_owns_imagery("0123456789ab", _USER_A) is False
    # 非法格式（非 12 位 hex）直接 False。
    assert await access.user_owns_imagery("not-a-valid-id", _USER_A) is False
    assert await access.user_owns_imagery("e1e1e1e1e1e1", None) is False


async def test_iter_user_imagery_metadata_db_priority(pg_conn, pg_pool, monkeypatch, tmp_path) -> None:
    # 合并语义：DB 有该用户影像 → 出现在清单；他人影像不出现；磁盘老影像（无 DB 行）也并入。
    import app.agent.imagery_access as access

    monkeypatch.setattr(access, "fetch_optional_pool", lambda: _wrap(pg_pool))
    monkeypatch.setattr(access, "imagery_root", lambda: tmp_path / "imagery")

    await imagery_repo.insert_imagery(
        pg_conn, imagery_id="f1f1f1f1f1f1", owner_user_id=_USER_A,
        metadata={"filename": "db.tif", "owner_user_id": _USER_A},
    )
    await imagery_repo.insert_imagery(
        pg_conn, imagery_id="b9b9b9b9b9b9", owner_user_id=_USER_B,
        metadata={"filename": "other.tif", "owner_user_id": _USER_B},
    )
    # 磁盘老影像（属 A，无 DB 行）。
    disk_dir = tmp_path / "imagery" / "0a0a0a0a0a0a"
    disk_dir.mkdir(parents=True)
    (disk_dir / "metadata.json").write_text(
        '{"filename": "disk.tif", "owner_user_id": "' + _USER_A + '"}', encoding="utf-8"
    )

    items = await access.iter_user_imagery_metadata(_USER_A)
    ids = {iid for iid, _meta in items}
    assert "f1f1f1f1f1f1" in ids      # DB 影像
    assert "0a0a0a0a0a0a" in ids      # 磁盘老影像并入
    assert "b9b9b9b9b9b9" not in ids  # 他人影像不泄漏
