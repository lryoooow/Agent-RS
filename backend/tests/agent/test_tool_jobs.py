"""durable 工具任务队列 PG 集成测试。

跑在 docker compose 的 pgvector/pg16 上（复用全局 pg_pool/pg_conn；库不可达整组 skip）。
验证 tool_jobs 的"持久化 + 重启恢复 + 消费闭环"，根除 embedding_retry "有表无消费者" 历史坑。

五维覆盖（对齐 CLAUDE.md）：
- 常规：begin→finish 写 pending→running→complete 三态；失败写 failed + error。
- 重启恢复：插一条心跳过期的 running job → recover → 被领重跑至 complete。
- 失败重试上限：连续失败到 max_attempts → 终态 failed，不再被领（attempts 不超限、队列不无限增长）。
- 并发不重复领取：两协程同时 claim，FOR UPDATE SKIP LOCKED 确保同一 job 只被一个领取。
- 异常分支：worker 处理中崩溃 → job 留 running，下轮心跳超时被重领（不丢）。
- 非法输入：无效 tool_name / 缺参 → _rerun_job 直接失败 result，不进死循环。
- 历史重复点（有表无消费者）：断言 worker 确实消费——recover 后 job 离开可领集合。
"""
from __future__ import annotations

import asyncio

import pytest

from app.agent import tool_jobs
from app.agent.types import ToolRunResult
from app.core.settings import get_settings
from app.db.repositories import tool_job as repo

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _wrap(pool):
    """把就绪 pool 包成 awaitable，匹配 fetch_optional_pool 的 async 调用约定。"""
    async def _inner():
        return pool
    return _inner()


class _FakeTool:
    """假工具：runner 行为可注入（成功/失败/计数）。argument_model 宽松接受任意 dict。"""

    def __init__(self, runner, *, enabled: bool = True) -> None:
        self.runner = runner
        self._enabled = enabled
        from pydantic import BaseModel, ConfigDict

        class _Args(BaseModel):
            model_config = ConfigDict(extra="allow")

        self.argument_model = _Args

    def is_enabled(self) -> bool:
        return self._enabled


def _ok_runner_factory(counter: dict):
    async def _runner(args):
        counter["runs"] = counter.get("runs", 0) + 1
        return ToolRunResult(tool_context="ok", result_count=1)
    return _runner


def _fail_runner(args):
    async def _never():  # pragma: no cover
        ...
    raise RuntimeError("synthetic tool failure")


# ───────────────────────── 常规：同步执行起止写三态 ─────────────────────────
async def test_begin_finish_writes_pending_running_complete(pg_conn, pg_pool, monkeypatch) -> None:
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    monkeypatch.setenv("TOOL_JOBS_ENABLED", "true")
    get_settings.cache_clear()

    job_id = await tool_jobs.begin_tool_job(
        tool_name="calculate_ndvi", arguments={"imagery_id": "abc"}, imagery_id="abc", user_id="u1"
    )
    assert job_id is not None
    running = await repo.get_tool_job(pg_conn, job_id=job_id)
    assert running["status"] == "running"
    assert running["attempts"] == 1

    await tool_jobs.finish_tool_job(job_id, ToolRunResult(tool_context="done", result_count=2))
    done = await repo.get_tool_job(pg_conn, job_id=job_id)
    assert done["status"] == "complete"
    assert done["result"]["result_count"] == 2


async def test_finish_with_error_writes_failed(pg_conn, pg_pool, monkeypatch) -> None:
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    get_settings.cache_clear()

    job_id = await tool_jobs.begin_tool_job(
        tool_name="detect_objects", arguments={"imagery_id": "x"}, imagery_id="x", user_id="u1"
    )
    await tool_jobs.finish_tool_job(
        job_id,
        ToolRunResult(tool_context="", error="boom", metadata={"error_code": "tool_runner_exception"}),
    )
    row = await repo.get_tool_job(pg_conn, job_id=job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "tool_runner_exception"
    assert "boom" in row["error_message"]


async def test_begin_disabled_returns_none_and_writes_nothing(pg_conn, pg_pool, monkeypatch) -> None:
    # 回退开关：tool_jobs_enabled=false → begin 返 None、不写任何行（与迁移前等价）。
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    monkeypatch.setenv("TOOL_JOBS_ENABLED", "false")
    get_settings.cache_clear()

    job_id = await tool_jobs.begin_tool_job(
        tool_name="calculate_ndvi", arguments={}, imagery_id=None, user_id="u1"
    )
    assert job_id is None
    count = await pg_conn.fetchval("SELECT count(*) FROM public.tool_jobs")
    assert count == 0
    monkeypatch.setenv("TOOL_JOBS_ENABLED", "true")
    get_settings.cache_clear()


# ───────────────────────── 重启恢复：捞孤儿重跑至 complete ─────────────────────────
async def test_recover_stale_job_reruns_to_complete(pg_conn, pg_pool, monkeypatch) -> None:
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    get_settings.cache_clear()
    counter: dict = {}
    monkeypatch.setattr(
        "app.agent.tool_registry.get_tool",
        lambda name: _FakeTool(_ok_runner_factory(counter)),
    )
    # 模拟"被重启打断"：插一条 running 但心跳过期的 job。
    job_id = await repo.create_tool_job(
        pg_conn, tool_name="calculate_ndvi", arguments={"imagery_id": "abc"}, imagery_id="abc", user_id="u1"
    )
    await pg_conn.execute(
        "UPDATE public.tool_jobs SET status='running', heartbeat_at=now() - interval '1000 seconds' WHERE id=$1::uuid",
        job_id,
    )

    recovered = await tool_jobs.recover_one_stale_job()
    assert recovered == job_id
    assert counter["runs"] == 1
    row = await repo.get_tool_job(pg_conn, job_id=job_id)
    assert row["status"] == "complete"
    # 历史重复点（有表无消费者）：消费后离开可领集合，再 recover 无可领。
    assert await tool_jobs.recover_one_stale_job() is None


async def test_pending_job_is_picked_up(pg_conn, pg_pool, monkeypatch) -> None:
    # 边界：纯 pending（从未跑过）也应被 worker 领取执行。
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    get_settings.cache_clear()
    counter: dict = {}
    monkeypatch.setattr(
        "app.agent.tool_registry.get_tool",
        lambda name: _FakeTool(_ok_runner_factory(counter)),
    )
    job_id = await repo.create_tool_job(
        pg_conn, tool_name="calculate_ndvi", arguments={"imagery_id": "p"}, imagery_id="p", user_id="u1"
    )
    recovered = await tool_jobs.recover_one_stale_job()
    assert recovered == job_id
    assert counter["runs"] == 1


# ───────────────────────── 失败重试上限：到 max_attempts 转 failed 不再重试 ─────────────────────────
async def test_failed_job_retries_until_max_then_terminal(pg_conn, pg_pool, monkeypatch) -> None:
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    get_settings.cache_clear()

    async def _always_fail(args):
        return ToolRunResult(tool_context="", error="always", metadata={"error_code": "tool_runner_exception"})

    monkeypatch.setattr(
        "app.agent.tool_registry.get_tool",
        lambda name: _FakeTool(_always_fail),
    )
    job_id = await repo.create_tool_job(
        pg_conn, tool_name="detect_objects", arguments={"imagery_id": "f"}, imagery_id="f", user_id="u1"
    )
    # max_attempts 默认 3：claim 累加 attempts，失败未到上限 requeue，到上限置 failed。
    for _ in range(5):
        if await tool_jobs.recover_one_stale_job() is None:
            break

    row = await repo.get_tool_job(pg_conn, job_id=job_id)
    assert row["status"] == "failed"
    assert row["attempts"] == row["max_attempts"] == 3  # 不超限
    # 终态后不再被领取（队列不无限增长）。
    assert await tool_jobs.recover_one_stale_job() is None


# ───────────────────────── 非法输入：无效 tool_name → 失败不死循环 ─────────────────────────
async def test_unknown_tool_name_fails_without_loop(pg_conn, pg_pool, monkeypatch) -> None:
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    get_settings.cache_clear()
    monkeypatch.setattr("app.agent.tool_registry.get_tool", lambda name: None)  # 注册表无此工具

    job_id = await repo.create_tool_job(
        pg_conn, tool_name="not_a_real_tool", arguments={}, user_id="u1"
    )
    for _ in range(5):
        if await tool_jobs.recover_one_stale_job() is None:
            break
    row = await repo.get_tool_job(pg_conn, job_id=job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "tool_unavailable"
    assert row["attempts"] <= row["max_attempts"]


# ───────────────────────── 并发：SKIP LOCKED 同一 job 不被双领 ─────────────────────────
async def test_concurrent_claim_no_double_pickup(pg_pool, monkeypatch) -> None:
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    get_settings.cache_clear()
    counter: dict = {}
    # 用 Event 卡住 runner，确保两协程在执行期重叠，逼真并发争用。
    gate = asyncio.Event()

    async def _slow_runner(args):
        counter["runs"] = counter.get("runs", 0) + 1
        await gate.wait()
        return ToolRunResult(tool_context="ok", result_count=1)

    monkeypatch.setattr(
        "app.agent.tool_registry.get_tool",
        lambda name: _FakeTool(_slow_runner),
    )
    async with pg_pool.acquire() as conn:
        await conn.execute("TRUNCATE public.tool_jobs")
        job_id = await repo.create_tool_job(
            conn, tool_name="calculate_ndvi", arguments={"imagery_id": "c"}, imagery_id="c", user_id="u1"
        )

    # 两协程同时尝试恢复：只有一个能 claim 到这唯一的 job，另一个 claim 为 None 立即返回。
    task_a = asyncio.create_task(tool_jobs.recover_one_stale_job())
    task_b = asyncio.create_task(tool_jobs.recover_one_stale_job())
    await asyncio.sleep(0.2)  # 让两协程都越过 claim
    gate.set()
    results = await asyncio.gather(task_a, task_b)

    # 恰一个领到 job_id、跑了 runner；另一个无可领。
    assert sorted(r for r in results if r) == [job_id]
    assert results.count(None) == 1
    assert counter["runs"] == 1  # runner 只执行一次（无双执行）


# ───────────────────────── 异常分支：worker 处理中崩溃 → job 留 running 待重领 ─────────────────────────
async def test_crashed_job_stays_running_and_is_reclaimable(pg_conn) -> None:
    # 模拟 worker 崩溃：claim 把 job 置 running（attempts+1）后，finalize 未执行（崩了）。
    # 断言：① job 仍 running（未丢失为终态）；② 心跳再次老化后能被重新 claim（不丢任务）。
    job_id = await repo.create_tool_job(
        pg_conn, tool_name="calculate_ndvi", arguments={"imagery_id": "z"}, imagery_id="z", user_id="u1"
    )
    await pg_conn.execute(
        "UPDATE public.tool_jobs SET status='running', heartbeat_at=now() - interval '1000 seconds' WHERE id=$1::uuid",
        job_id,
    )
    # 第一次 claim：领到、转 running、attempts=1、刷新心跳。随后"崩溃"——不写终态。
    first = await repo.claim_stale_job(pg_conn, stale_after_seconds=450)
    assert first["id"] == job_id and first["attempts"] == 1
    mid = await repo.get_tool_job(pg_conn, job_id=job_id)
    assert mid["status"] == "running"  # 仍 running，未丢为终态

    # 心跳新鲜 → 暂不可被重领（不会被误判孤儿）。
    assert await repo.claim_stale_job(pg_conn, stale_after_seconds=450) is None
    # 再次老化心跳（模拟下一轮超时）→ 被重新领取（不丢任务）。
    await pg_conn.execute(
        "UPDATE public.tool_jobs SET heartbeat_at=now() - interval '1000 seconds' WHERE id=$1::uuid",
        job_id,
    )
    second = await repo.claim_stale_job(pg_conn, stale_after_seconds=450)
    assert second["id"] == job_id and second["attempts"] == 2  # 重领、attempts 继续累加


async def test_worker_loop_drains_then_stops(pg_conn, pg_pool, monkeypatch) -> None:
    # worker 主循环：领光积压后 sleep；stop_event 置位即退出（lifespan 优雅停）。
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    monkeypatch.setenv("TOOL_JOBS_POLL_INTERVAL_SECONDS", "1")
    get_settings.cache_clear()
    counter: dict = {}
    monkeypatch.setattr(
        "app.agent.tool_registry.get_tool",
        lambda name: _FakeTool(_ok_runner_factory(counter)),
    )
    for i in range(3):
        await repo.create_tool_job(
            pg_conn, tool_name="calculate_ndvi", arguments={"imagery_id": f"img{i}"},
            imagery_id=f"img{i}", user_id="u1",
        )

    stop = asyncio.Event()
    task = asyncio.create_task(tool_jobs.run_tool_job_worker(stop))
    await asyncio.sleep(0.5)  # 一轮足以领光 3 个
    stop.set()
    await asyncio.wait_for(task, timeout=3)

    assert counter["runs"] == 3
    remaining = await pg_conn.fetchval(
        "SELECT count(*) FROM public.tool_jobs WHERE status IN ('pending','running')"
    )
    assert remaining == 0


# ───────────────────────── 执行期心跳：活跃长任务不被误判孤儿（#1 根因修复）─────────────────────────
async def test_heartbeat_job_refreshes_and_blocks_reclaim(pg_conn) -> None:
    # 根因（#1）：begin 只写一次 heartbeat_at，长任务超过 stale 阈值会被 worker 误领重复执行。
    # 断言：心跳过期 → 可被 claim；执行中刷新心跳 → 同样的 stale 阈值下不再可领（活跃任务受保护）。
    job_id = await repo.create_tool_job(
        pg_conn, tool_name="calculate_ndvi", arguments={"imagery_id": "h"}, imagery_id="h", user_id="u1"
    )
    # 模拟活跃 running 但心跳已老化（旧实现的缺陷态）。
    await pg_conn.execute(
        "UPDATE public.tool_jobs SET status='running', heartbeat_at=now() - interval '1000 seconds' WHERE id=$1::uuid",
        job_id,
    )
    # 此刻确实会被判为孤儿（可领）——证明缺陷真实存在。
    claimed = await repo.claim_stale_job(pg_conn, stale_after_seconds=450)
    assert claimed is not None and claimed["id"] == job_id

    # 现在刷新心跳（模拟执行期 heartbeat_loop 的一次刷新）。
    await repo.heartbeat_job(pg_conn, job_id=job_id)
    # 同样 stale 阈值下，心跳新鲜 → 不再被领（活跃任务受保护，不会被重复执行）。
    assert await repo.claim_stale_job(pg_conn, stale_after_seconds=450) is None


async def test_heartbeat_tool_job_keeps_long_run_unclaimable(pg_pool, monkeypatch) -> None:
    # 集成：heartbeat_tool_job 包住一个"长任务"，执行期间并发 claim 应始终领不到（心跳持续刷新）。
    # 用极小 stale 阈值 + gate 卡住任务制造"任务时长 > stale"的逼真场景。
    monkeypatch.setattr(tool_jobs, "fetch_optional_pool", lambda: _wrap(pg_pool))
    monkeypatch.setenv("TOOL_JOBS_STALE_AFTER_SECONDS", "15")  # //3=5s（下限），任务跨多个心跳周期
    get_settings.cache_clear()

    async with pg_pool.acquire() as conn:
        await conn.execute("TRUNCATE public.tool_jobs")
        job_id = await repo.create_tool_job(
            conn, tool_name="segment_objects", arguments={"imagery_id": "long"},
            imagery_id="long", user_id="u1",
        )
        await conn.execute(
            "UPDATE public.tool_jobs SET status='running', heartbeat_at=now() - interval '100 seconds' WHERE id=$1::uuid",
            job_id,
        )

    # 进入 heartbeat 上下文：起后台刷新协程。给足时间让它刷新至少一次（>5s 下限）。
    async with tool_jobs.heartbeat_tool_job(job_id):
        await asyncio.sleep(6)  # 跨过一个心跳间隔，心跳被刷新为 now()
        async with pg_pool.acquire() as conn:
            # stale=15s，心跳刚在 6s 内被刷新 → 不该被判孤儿。
            claimed = await repo.claim_stale_job(conn, stale_after_seconds=15)
        assert claimed is None  # 活跃任务受保护，未被误领

    # 上下文退出：心跳协程已停。让心跳老化后应可被恢复 worker 接管（任务真正结束/崩溃的兜底）。
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.tool_jobs SET heartbeat_at=now() - interval '100 seconds' WHERE id=$1::uuid",
            job_id,
        )
        reclaimed = await repo.claim_stale_job(conn, stale_after_seconds=15)
    assert reclaimed is not None and reclaimed["id"] == job_id


async def test_heartbeat_tool_job_none_is_noop() -> None:
    # 边界：job_id=None（功能关闭/无库）→ 纯 no-op，不起协程、不抛异常。
    async with tool_jobs.heartbeat_tool_job(None):
        pass
