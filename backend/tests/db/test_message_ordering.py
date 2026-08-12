"""P1-3 回归：同事务多行（created_at 相同）的消息顺序必须确定性。

流式轮里 user + streaming-assistant 在 prepare_persistence 的同一事务插入，
created_at 完全相同（now() 事务级稳定）。仅 ORDER BY created_at 时同 timestamp 行顺序
非确定（角色可能反转，污染下一轮上下文）。加 seq BIGSERIAL + ORDER BY ..., seq DESC 后
顺序恒定。库不可达时整组 skip（见 tests/conftest.py 的 pg_pool/pg_conn 夹具）。
"""
from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.db.repositories._pg import conversation as conv_repo
from app.db.repositories._pg import identity as identity_repo
from app.db.repositories._pg import message as msg_repo

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _settings() -> Settings:
    return Settings(_env_file=None)


async def test_message_ordering_deterministic_within_same_transaction(pg_conn) -> None:
    settings = _settings()
    uid, _wid = await identity_repo.ensure_default_identity(pg_conn, settings)
    cid = await conv_repo.create_conversation(pg_conn, user_id=uid, settings=settings, title="Tie")

    # 同事务双插入 → 两行 created_at 完全相同（复刻 prepare_persistence 流式场景）。
    async with pg_conn.transaction():
        await msg_repo.append_message(pg_conn, conversation_id=cid, role="user", content="问题")
        await msg_repo.append_message(pg_conn, conversation_id=cid, role="assistant", content="回答")

    # 多次读取，顺序必须恒定为 [user, assistant]（修复前因 created_at 并列而随机反转）。
    for _ in range(10):
        recent = await msg_repo.list_recent_messages(
            pg_conn, conversation_id=cid, limit=10, user_id=uid
        )
        assert [m.role for m in recent] == ["user", "assistant"]
