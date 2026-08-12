from types import SimpleNamespace

import asyncio

import pytest

from app.agent.persistence import PersistenceContext, _assistant_metadata, schedule_after_response


@pytest.mark.asyncio
async def test_schedule_after_response_keeps_embedding_ids_and_content_paired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = []
    embedded_targets = []

    def fake_create_task(coro):
        tasks.append(coro)
        return SimpleNamespace()

    async def fake_embed_messages(targets):
        embedded_targets.extend(targets)

    async def fake_maybe_store_memory(**_):
        return None

    monkeypatch.setattr("app.agent.persistence.asyncio.create_task", fake_create_task)
    monkeypatch.setattr("app.agent.persistence._embed_messages", fake_embed_messages)
    monkeypatch.setattr("app.agent.persistence.maybe_store_memory", fake_maybe_store_memory)

    schedule_after_response(
        PersistenceContext(
            user_id="00000000-0000-4000-8000-000000000001",
            conversation_id="00000000-0000-4000-8000-000000000301",
            user_message_id=None,
            assistant_message_id="00000000-0000-4000-8000-000000000303",
            user_content="user text",
        ),
        assistant_content="assistant text",
    )

    for task in tasks:
        await task

    assert embedded_targets == [
        ("00000000-0000-4000-8000-000000000303", "assistant text")
    ]


def test_assistant_metadata_embeds_structured_results() -> None:
    # A2 写入端：跑了工具的轮次，结构化结果与 finish_reason 一并落库（供跨轮回注/报告读取）。
    geo = {"type": "segmentation", "imagery_id": "d722c20e1234", "classes": []}
    tool = {"type": "raster_inspect", "imagery_id": "d722c20e1234", "band_count": 4}
    meta = _assistant_metadata(finish_reason="stop", geospatial_result=geo, tool_result=tool)
    assert meta == {"finish_reason": "stop", "geospatial_result": geo, "tool_result": tool}


def test_assistant_metadata_omits_absent_results() -> None:
    # 边界：纯对话轮（无工具结果）只存 finish_reason，不写空键，保持 metadata 精简。
    assert _assistant_metadata(finish_reason="stop", geospatial_result=None, tool_result=None) == {
        "finish_reason": "stop"
    }
    # 空 dict 也视作无结果，不写键（避免注入空块）。
    assert _assistant_metadata(finish_reason=None, geospatial_result={}, tool_result={}) == {
        "finish_reason": None
    }


@pytest.mark.asyncio
async def test_prepare_persistence_surfaces_operational_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # P1-2：操作性 DB 错误（死锁/连接掉）不再静默降级为无状态、返回 200；改为上抛 AIError(503)，
    # 让客户端知道本轮未保存。这里模拟 pool.acquire() 阶段即失败（非 missing-schema）。
    from app.agent.persistence import prepare_persistence
    from app.agent.errors import AIError
    from app.core.settings import get_settings
    from app.schemas.chat import ChatRequest, ChatMessage

    monkeypatch.setenv("DATABASE_ENABLED", "true")
    get_settings.cache_clear()

    class _RaisingPool:
        def acquire(self):
            raise RuntimeError("simulated connection drop mid-write")

    async def fake_pool():
        return _RaisingPool()

    monkeypatch.setattr("app.agent.persistence.fetch_optional_pool", fake_pool)

    request = ChatRequest(messages=[ChatMessage(role="user", content="hi")])
    with pytest.raises(AIError) as ei:
        await prepare_persistence(request, model_name="m", create_streaming_assistant=True)
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_mark_assistant_failed_preserves_streamed_content(monkeypatch: pytest.MonkeyPatch) -> None:
    # P2-6：finish_reason=error 且已有流式正文时，mark_assistant_failed 须保留正文（不再置空），
    # 否则用户已看到的回答被永久抹掉、不可恢复。
    from app.agent.persistence import PersistenceContext, mark_assistant_failed

    recorded: dict[str, object] = {}

    async def fake_update(conn, *, message_id, content, status, metadata=None, **_):  # noqa: ANN001
        recorded.update(message_id=message_id, content=content, status=status, metadata=metadata)

    class _FakeConn:
        pass

    class _FakeAcquire:
        def __init__(self, conn) -> None:
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, *exc):
            return False

    class _FakePool:
        def __init__(self, conn) -> None:
            self.conn = conn

        def acquire(self):
            return _FakeAcquire(self.conn)

    async def fake_pool():
        return _FakePool(_FakeConn())

    monkeypatch.setattr("app.agent.persistence.update_message_complete", fake_update)
    monkeypatch.setattr("app.agent.persistence.fetch_optional_pool", fake_pool)

    ctx = PersistenceContext(user_id="u", conversation_id="c", assistant_message_id="m1")
    await mark_assistant_failed(ctx, RuntimeError("provider error"), content="部分流式正文")

    assert recorded["content"] == "部分流式正文"
    assert recorded["status"] == "failed"
    assert recorded["metadata"] == {
        "error_code": "PROVIDER_ERROR",
        "error_type": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_drain_persistence_tasks_awaits_tracked_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    # O1：后台任务被强引用持有（不被 GC），drain_persistence_tasks 能在关池前 await 完成。
    import app.agent.persistence as persistence
    from app.agent.persistence import _track_background_task, drain_persistence_tasks

    release = asyncio.Event()
    started = asyncio.Event()

    async def worker() -> None:
        started.set()
        await asyncio.wait_for(release.wait(), timeout=2)

    task = asyncio.create_task(worker())
    _track_background_task(task, "test")
    await started.wait()
    assert task in persistence._background_tasks  # 强引用持有中

    release.set()
    await drain_persistence_tasks(timeout=2)
    assert task.done()


@pytest.mark.asyncio
async def test_mark_assistant_failed_inserts_failed_row_when_no_assistant_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # O2：非流式失败（无预建 assistant 行）时补一条 failed 行，而非静默 no-op。
    from app.agent.persistence import PersistenceContext, mark_assistant_failed

    inserted: dict[str, object] = {}

    async def fake_append(conn, *, conversation_id, role, content, status, metadata=None, **_):  # noqa: ANN001
        inserted.update(conversation_id=conversation_id, role=role, content=content,
                        status=status, metadata=metadata)
        return "new-failed-id"

    class _FakeConn:
        pass

    class _FakeAcquire:
        def __init__(self, conn) -> None:
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, *exc):
            return False

    class _FakePool:
        def __init__(self, conn) -> None:
            self.conn = conn

        def acquire(self):
            return _FakeAcquire(self.conn)

    async def fake_pool():
        return _FakePool(_FakeConn())

    monkeypatch.setattr("app.agent.persistence.fetch_optional_pool", fake_pool)
    monkeypatch.setattr("app.agent.persistence.append_message", fake_append)

    ctx = PersistenceContext(user_id="u", conversation_id="c1", assistant_message_id=None)
    await mark_assistant_failed(ctx, RuntimeError("boom"))

    assert inserted["status"] == "failed"
    assert inserted["role"] == "assistant"
    assert inserted["metadata"] == {
        "error_code": "PROVIDER_ERROR",
        "error_type": "RuntimeError",
    }
    assert ctx.assistant_message_id == "new-failed-id"
