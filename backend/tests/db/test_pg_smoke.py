"""Stage 0 地基冒烟测试：连真实 PostgreSQL → 迁移建表 → 建会话 → 插消息 → 查回。

锁死"PG 测试地基本身可用"：docker compose 起库后这条必须绿，是后续把 26 个仓储测试
切到 PG 的前提。库不可达时 conftest 的 pg_pool 夹具会整组 skip（非失败）。
"""
from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.db.repositories._pg import conversation as conv_repo
from app.db.repositories._pg import identity as identity_repo
from app.db.repositories._pg import message as msg_repo

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _settings() -> Settings:
    # 不读本地 .env，用代码默认的 default_user_id/default_workspace_id（合法 UUID）。
    return Settings(_env_file=None)


async def test_pg_smoke_conversation_message_roundtrip(pg_conn) -> None:
    settings = _settings()
    user_id, _workspace_id = await identity_repo.ensure_default_identity(pg_conn, settings)

    conversation_id = await conv_repo.create_conversation(
        pg_conn, user_id=user_id, settings=settings, title="冒烟会话"
    )
    assert conversation_id

    message_id = await msg_repo.append_message(
        pg_conn,
        conversation_id=conversation_id,
        role="user",
        content="你好，冒烟测试",
        status="complete",
    )
    assert message_id

    messages = await msg_repo.list_recent_messages(
        pg_conn, conversation_id=conversation_id, limit=10, user_id=user_id
    )
    assert [m.content for m in messages] == ["你好，冒烟测试"]


async def test_pg_smoke_schema_migrations_recorded(pg_conn) -> None:
    # 迁移已落库：schema_migrations 至少含 base schema 版本号。
    rows = await pg_conn.fetch("SELECT version FROM agent_rs.schema_migrations")
    versions = {row["version"] for row in rows}
    assert "0000_base_schema" in versions
