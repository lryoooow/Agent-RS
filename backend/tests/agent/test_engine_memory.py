"""engine/memory：RAG 与长期记忆的 AutoGen Memory 协议适配。

不打库、不打网络：把 pool / 检索管线 / embedding 都替掉，只验协议行为与降级策略。
"""
from __future__ import annotations

import pytest
from autogen_core.memory import MemoryContent, MemoryMimeType
from autogen_core.model_context import UnboundedChatCompletionContext
from autogen_core.models import AssistantMessage, SystemMessage, UserMessage

from app.agent.engine.memory._common import latest_user_query
from app.agent.engine.memory.pg_memory import PgVectorMemory
from app.agent.engine.memory.rag_memory import RagMemory
from app.agent.engine.turn_context import turn_scope
from app.agent.rag.service import RAGResult
from app.core.settings import get_settings

USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _storage_on(monkeypatch):
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakePool:
    """够用的假连接池：只要能 `async with pool.acquire() as conn` 就行。"""

    def acquire(self):
        class _Ctx:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *_):
                return False

        return _Ctx()


async def _fake_embed(_text):
    return [0.1] * 8


# --------------------------------------------------------------- _common


@pytest.mark.asyncio
async def test_latest_user_query_skips_trailing_non_user_messages() -> None:
    """多步链路里上下文尾部常是工具/助手消息，必须往回找真正的用户提问。"""
    ctx = UnboundedChatCompletionContext()
    await ctx.add_message(UserMessage(content="算一下这张图的 NDVI", source="user"))
    await ctx.add_message(AssistantMessage(content="好的", source="assistant"))
    await ctx.add_message(SystemMessage(content="工具结果：NDVI 均值 0.42"))

    assert await latest_user_query(ctx) == "算一下这张图的 NDVI"


@pytest.mark.asyncio
async def test_latest_user_query_empty_when_no_user_message() -> None:
    ctx = UnboundedChatCompletionContext()
    await ctx.add_message(SystemMessage(content="只有系统消息"))
    assert await latest_user_query(ctx) == ""


# --------------------------------------------------------------- RagMemory


@pytest.mark.asyncio
async def test_rag_memory_injects_system_block_and_records_trace(monkeypatch) -> None:
    async def fake_retrieve(_pool, **kwargs):
        return RAGResult(
            context="【知识库】台风路径预报规范……",
            retrieved_chunks=3,
            trace={"candidates": 12, "rerank_ms": 40},
        )

    monkeypatch.setattr("app.agent.engine.memory.rag_memory.fetch_optional_pool", _fake_pool)
    monkeypatch.setattr("app.agent.engine.memory.rag_memory.retrieve_rag_context", fake_retrieve)
    monkeypatch.setattr(
        "app.agent.engine.memory.rag_memory.get_embedding_service", lambda: _FakeEmbed()
    )

    ctx = UnboundedChatCompletionContext()
    await ctx.add_message(UserMessage(content="台风路径怎么预报", source="user"))

    memory = RagMemory(user_id=USER)
    with turn_scope() as state:
        result = await memory.update_context(ctx)

    assert len(result.memories.results) == 1
    messages = await ctx.get_messages()
    assert isinstance(messages[-1], SystemMessage), "检索结果必须作为 SystemMessage 注入"
    assert "台风路径预报规范" in messages[-1].content
    # 检索统计要回到回合状态，编排层才能塞进 SSE 的 rag_trace 面板
    assert state.retrieved_chunks == 3
    assert state.rag_trace["candidates"] == 12


@pytest.mark.asyncio
async def test_rag_memory_degrades_when_retrieval_raises(monkeypatch) -> None:
    """检索炸了不能拖垮回答，只降级成没有知识库上下文。"""

    async def boom(_pool, **kwargs):
        raise RuntimeError("向量库挂了")

    monkeypatch.setattr("app.agent.engine.memory.rag_memory.fetch_optional_pool", _fake_pool)
    monkeypatch.setattr("app.agent.engine.memory.rag_memory.retrieve_rag_context", boom)
    monkeypatch.setattr(
        "app.agent.engine.memory.rag_memory.get_embedding_service", lambda: _FakeEmbed()
    )

    ctx = UnboundedChatCompletionContext()
    await ctx.add_message(UserMessage(content="随便问点什么", source="user"))

    with turn_scope() as state:
        result = await RagMemory(user_id=USER).update_context(ctx)

    assert result.memories.results == []
    assert len(await ctx.get_messages()) == 1, "失败时不该往上下文塞任何东西"
    assert state.rag_trace["error"] == "rag_failed", "失败要如实反映在 trace 里"


@pytest.mark.asyncio
async def test_rag_memory_disabled_is_noop(monkeypatch) -> None:
    monkeypatch.setattr("app.agent.engine.memory.rag_memory.fetch_optional_pool", _boom_pool)
    result = await RagMemory(user_id=USER, enabled=False).query("任意问题")
    assert result.results == []


@pytest.mark.asyncio
async def test_rag_memory_refuses_write_paths() -> None:
    """知识库入库必须走文档上传管线，不能开旁路。"""
    memory = RagMemory(user_id=USER)
    with pytest.raises(NotImplementedError, match="文档上传接口"):
        await memory.add(MemoryContent(content="x", mime_type=MemoryMimeType.TEXT))
    with pytest.raises(NotImplementedError):
        await memory.clear()


# --------------------------------------------------------------- PgVectorMemory


@pytest.mark.asyncio
async def test_pg_memory_exposes_structured_metadata(monkeypatch) -> None:
    """召回结果要带上 memory_type / importance，这正是本次修好的两列。"""

    async def fake_list(_conn, **kwargs):
        return [
            {
                "id": "m1",
                "content": "结论必须标注数据来源与时间",
                "memory_type": "constraint",
                "importance": 0.9,
                "score": 0.87,
                "metadata": {"tags": ["项目约束"]},
            }
        ]

    monkeypatch.setattr("app.agent.engine.memory.pg_memory.fetch_optional_pool", _fake_pool)
    monkeypatch.setattr("app.agent.engine.memory.pg_memory.list_relevant_memories", fake_list)
    monkeypatch.setattr(
        "app.agent.engine.memory.pg_memory.get_embedding_service", lambda: _FakeEmbed()
    )

    result = await PgVectorMemory(user_id=USER).query("有什么规定")

    assert len(result.results) == 1
    meta = result.results[0].metadata
    assert meta["memory_type"] == "constraint"
    assert meta["importance"] == 0.9
    assert meta["tags"] == ["项目约束"]


@pytest.mark.asyncio
async def test_pg_memory_without_user_is_fully_disabled(monkeypatch) -> None:
    """没有身份就既不读别人的记忆，也不写孤儿行。"""
    monkeypatch.setattr("app.agent.engine.memory.pg_memory.fetch_optional_pool", _boom_pool)
    memory = PgVectorMemory(user_id=None)

    assert (await memory.query("任意")).results == []
    await memory.add(MemoryContent(content="不该落库", mime_type=MemoryMimeType.TEXT))


@pytest.mark.asyncio
async def test_pg_memory_add_normalizes_type_and_importance(monkeypatch) -> None:
    """模型可能给出没定义的类型或越界重要度，落库前必须收敛，否则撞 CHECK 约束。"""
    captured: dict = {}

    async def fake_insert(_conn, **kwargs):
        captured.update(kwargs)
        return "new-id"

    monkeypatch.setattr("app.agent.engine.memory.pg_memory.fetch_optional_pool", _fake_pool)
    monkeypatch.setattr("app.agent.engine.memory.pg_memory.insert_memory", fake_insert)
    monkeypatch.setattr(
        "app.agent.engine.memory.pg_memory.get_embedding_service", lambda: _FakeEmbed()
    )

    await PgVectorMemory(user_id=USER).add(
        MemoryContent(
            content="用户偏好中文",
            mime_type=MemoryMimeType.TEXT,
            metadata={"memory_type": "不存在的类型", "importance": 42, "tags": ["x"]},
        )
    )

    assert captured["memory_type"] == "fact", "未知类型必须回退，不能直接落库"
    assert 0.0 <= captured["importance"] <= 1.0, "重要度必须夹进 [0,1]"
    assert captured["metadata"]["tags"] == ["x"], "其余 metadata 要原样保留"


@pytest.mark.asyncio
async def test_pg_memory_add_survives_write_failure(monkeypatch) -> None:
    """记忆写入是锦上添花，失败不该影响本次回答。"""

    async def boom(_conn, **kwargs):
        raise RuntimeError("库挂了")

    monkeypatch.setattr("app.agent.engine.memory.pg_memory.fetch_optional_pool", _fake_pool)
    monkeypatch.setattr("app.agent.engine.memory.pg_memory.insert_memory", boom)
    monkeypatch.setattr(
        "app.agent.engine.memory.pg_memory.get_embedding_service", lambda: _FakeEmbed()
    )

    await PgVectorMemory(user_id=USER).add(
        MemoryContent(content="x", mime_type=MemoryMimeType.TEXT)
    )  # 不抛异常即通过


@pytest.mark.asyncio
async def test_pg_memory_refuses_bulk_clear() -> None:
    with pytest.raises(NotImplementedError, match="/api/memories"):
        await PgVectorMemory(user_id=USER).clear()


# --------------------------------------------------------------- helpers


class _FakeEmbed:
    async def embed_text(self, _text):
        return [0.1] * 8


async def _fake_pool():
    return _FakePool()


async def _boom_pool():
    raise AssertionError("禁用状态下不应触碰连接池")
