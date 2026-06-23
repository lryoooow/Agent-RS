"""durable 工具任务队列：持久化"做过什么工具、什么失败了" + 重启恢复孤儿任务。

执行模型（最小侵入，不重写同步 SSE 流）：
- 正常流量仍在请求内同步执行（runtime → child.py → runner → docker），用户实时看 SSE 进度；
  仅在 child 执行的起止写 tool_jobs 行（pending→running→complete/failed），获得持久化可观测性。
- 重启恢复：lifespan 起一个轻量后台 worker（见 start_tool_job_worker），周期性
  `claim_stale_job`（FOR UPDATE SKIP LOCKED）只捞孤儿 job（重启时仍 running/pending、心跳超时的），
  重新跑至终态。worker 不接管正常流量，只兜底。
- 消费闭环（规避 embedding_retry "有表无消费者" 历史坑）：worker 即消费者，attempts 到
  max_attempts 即不再领取（claim 的 attempts < max_attempts 条件），杜绝队列无界增长。

并发约束：遥感工具 docker 执行的并发总闸已在 rs_tools_client.call_tool 内（见 app/mcp/concurrency.py）。
worker 重跑经同一 runner→call_tool 路径，自动受同一信号量约束——故 worker **不再**自行包
tool_semaphore（否则 limit=1 时 worker 持 1 permit、runner 等另一 permit → 死锁）。

所有 DB 操作 best-effort：job 记录是旁路可观测性，绝不能把异常抛进工具执行主路径
（DB 不可用/表未建/写失败 → 只记日志，工具照常执行返回）。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from app.core.settings import get_settings
from app.db.errors import is_missing_schema_error
from app.db.pool import fetch_optional_pool
from app.db.repositories.tool_job import (
    claim_stale_job,
    create_tool_job,
    heartbeat_job,
    mark_job_complete,
    mark_job_failed,
    mark_job_running,
)
from app.agent.types import ToolRunResult

logger = logging.getLogger(__name__)


def _result_summary(result: ToolRunResult) -> dict[str, Any]:
    """从 ToolRunResult 抽小结果摘要存 job.result（不存巨大的 tool_context 全文）。"""
    summary: dict[str, Any] = {
        "result_count": result.result_count,
        "query": result.query,
        "tool_context_chars": len(result.tool_context or ""),
    }
    if result.metadata:
        summary["metadata"] = dict(result.metadata)
    if result.geospatial_result:
        gr = result.geospatial_result
        summary["geospatial_type"] = gr.get("type") if isinstance(gr, dict) else getattr(gr, "type", None)
    return summary


async def begin_tool_job(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    imagery_id: str | None,
    user_id: str | None,
) -> str | None:
    """登记一条工具任务并转 running，返回 job_id；功能关闭/无库/出错 → None（不影响执行）。

    best-effort：任何异常都吞掉返回 None，工具照常同步执行。
    """
    settings = get_settings()
    if not settings.tool_jobs_enabled:
        return None
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            job_id = await create_tool_job(
                conn,
                tool_name=tool_name,
                arguments=arguments,
                imagery_id=imagery_id or None,
                user_id=user_id,
            )
            await mark_job_running(conn, job_id=job_id)
        return job_id
    except Exception as exc:
        if not is_missing_schema_error(exc):
            logger.exception("Failed to begin tool job for %s", tool_name)
        return None


async def finish_tool_job(job_id: str | None, result: ToolRunResult) -> None:
    """按 result.error 把任务写 complete/failed 终态。job_id 为 None（未登记）→ noop。

    best-effort：写失败只记日志，不影响已产出的工具结果。
    """
    if job_id is None:
        return
    pool = await fetch_optional_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            if result.error:
                await mark_job_failed(
                    conn,
                    job_id=job_id,
                    error_code=str(result.metadata.get("error_code") or "tool_error"),
                    error_message=str(result.error)[:2000],
                )
            else:
                await mark_job_complete(conn, job_id=job_id, result=_result_summary(result))
    except Exception as exc:
        if not is_missing_schema_error(exc):
            logger.exception("Failed to finish tool job %s", job_id)


# ───────────────────────── 执行期心跳（防活跃长任务被误判孤儿）─────────────────────────
async def _heartbeat_loop(job_id: str, interval: float) -> None:
    """周期刷新 running 任务心跳，直到被取消。best-effort：单次失败只记日志不中断循环。"""
    while True:
        await asyncio.sleep(interval)
        pool = await fetch_optional_pool()
        if pool is None:
            continue
        try:
            async with pool.acquire() as conn:
                await heartbeat_job(conn, job_id=job_id)
        except Exception as exc:
            if not is_missing_schema_error(exc):
                logger.exception("Failed to heartbeat tool job %s", job_id)


@asynccontextmanager
async def heartbeat_tool_job(job_id: str | None) -> AsyncIterator[None]:
    """执行期心跳：进入时起后台心跳协程，退出时停。

    根因修复（#1）：同步执行只在 begin 时写一次 heartbeat_at，长任务（detect/segment、
    并发闸排队、minio 大影像 staging 拉取）可能超过 stale_after 阈值，被恢复 worker 误判
    为孤儿而重复执行。本上下文在 runner 执行全程周期刷新心跳，使活跃任务始终"新鲜"、
    不被 claim；任务真正结束（或进程崩溃）后心跳停止，超时才被恢复 worker 接管。

    job_id 为 None（功能关闭/无库）→ 纯 no-op，不起协程。
    心跳间隔取 stale_after // 3（≥5s），确保一个周期内必有多次刷新覆盖阈值。
    """
    if job_id is None:
        yield
        return
    interval = max(5, get_settings().tool_jobs_stale_after_seconds // 3)
    task = asyncio.create_task(_heartbeat_loop(job_id, interval))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ───────────────────────── 重启恢复 worker（孤儿 job 消费者）─────────────────────────
async def recover_one_stale_job() -> str | None:
    """领取并重跑一个孤儿 job，返回被处理的 job_id；无可领任务返回 None。

    幂等重跑：遥感工具同输入同输出、结果覆盖写，重跑无副作用。
    重跑经 ToolChildAgent → runner → call_tool，自动受 docker 并发总闸约束（不再自包信号量）。
    在此把 child 自身的 begin/finish 旁路掉——claim 已把 job 置 running 并 attempts+1，
    故直接调 runner 并由本函数写终态，避免重复登记新 job。
    """
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    settings = get_settings()
    try:
        async with pool.acquire() as conn:
            job = await claim_stale_job(conn, stale_after_seconds=settings.tool_jobs_stale_after_seconds)
    except Exception as exc:
        if not is_missing_schema_error(exc):
            logger.exception("Failed to claim stale tool job")
        return None
    if job is None:
        return None

    job_id = job["id"]
    # 执行期心跳：worker 重跑同样可能是长任务，全程刷新心跳，避免被另一 worker/下一轮误判孤儿重领。
    async with heartbeat_tool_job(job_id):
        result = await _rerun_job(job)
    # 写终态：成功 complete；失败则——还有重试余量留 failed（下轮心跳超时不会重领，
    # 因 failed 不在 claim 的 status 集合）……但需求是"重试到上限"。故失败且未到上限 → 置回 pending 待重领；
    # 到上限 → failed 终态。
    pool2 = await fetch_optional_pool()
    if pool2 is None:
        return job_id
    try:
        async with pool2.acquire() as conn:
            if not result.error:
                await mark_job_complete(conn, job_id=job_id, result=_result_summary(result))
            elif job["attempts"] >= job["max_attempts"]:
                await mark_job_failed(
                    conn,
                    job_id=job_id,
                    error_code=str(result.metadata.get("error_code") or "tool_error"),
                    error_message=str(result.error)[:2000],
                )
            else:
                # 还有重试余量：置回 pending，下一轮 worker 再领（attempts 已在 claim 时累加）。
                await _requeue_job(conn, job_id=job_id)
    except Exception as exc:
        if not is_missing_schema_error(exc):
            logger.exception("Failed to finalize recovered tool job %s", job_id)
    return job_id


async def _rerun_job(job: dict[str, Any]) -> ToolRunResult:
    """据 job 行重建工具调用并执行。无效 tool_name/参数 → 直接返回失败 result（不进死循环）。"""
    from app.agent.tool_registry import get_tool
    from app.agent.tools.staging import stage_imagery

    tool = get_tool(job["tool_name"])
    if tool is None or not tool.is_enabled():
        return ToolRunResult(
            tool_context="工具不可用，已跳过重跑。",
            error=f"tool_unavailable: {job['tool_name']}",
            metadata={"error_code": "tool_unavailable"},
        )
    try:
        args = tool.argument_model.model_validate(job.get("arguments") or {})
    except Exception as exc:
        return ToolRunResult(
            tool_context="工具参数无效，已跳过重跑。",
            error=str(exc),
            metadata={"error_code": "invalid_arguments"},
        )
    try:
        imagery_id = str((job.get("arguments") or {}).get("imagery_id") or "")
        if imagery_id:
            async with stage_imagery(imagery_id):
                return await tool.runner(args)
        return await tool.runner(args)
    except Exception as exc:
        return ToolRunResult(
            tool_context="工具重跑失败。",
            error=str(exc),
            metadata={"error_code": "tool_runner_exception"},
        )


async def _requeue_job(conn, *, job_id: str) -> None:
    await conn.execute(
        "UPDATE public.tool_jobs SET status = 'pending', updated_at = now() WHERE id = $1::uuid",
        job_id,
    )


async def run_tool_job_worker(stop_event: asyncio.Event) -> None:
    """后台 worker 主循环：周期性捞孤儿 job 重跑，直到 stop_event 置位。

    一轮内连续领取直到无可领（清空积压），再 sleep 一个轮询间隔。
    单轮异常不杀死循环（记日志后继续），保证 worker 长活。
    """
    settings = get_settings()
    interval = max(1, settings.tool_jobs_poll_interval_seconds)
    logger.info("Tool job recovery worker started (interval=%ss).", interval)
    while not stop_event.is_set():
        try:
            while not stop_event.is_set():
                job_id = await recover_one_stale_job()
                if job_id is None:
                    break
                logger.info("Recovered stale tool job %s", job_id)
        except Exception:
            logger.exception("Tool job worker iteration failed; continuing.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    logger.info("Tool job recovery worker stopped.")


# ───────────────────────── lifespan 管理（单 worker 实例）─────────────────────────
_worker_task: asyncio.Task | None = None
_worker_stop: asyncio.Event | None = None


def start_tool_job_worker() -> None:
    """启动后台恢复 worker（lifespan 调）。功能关闭则不启。重复调用幂等（已在跑则忽略）。"""
    global _worker_task, _worker_stop
    if not get_settings().tool_jobs_enabled:
        return
    if _worker_task is not None and not _worker_task.done():
        return
    _worker_stop = asyncio.Event()
    _worker_task = asyncio.create_task(run_tool_job_worker(_worker_stop))


async def stop_tool_job_worker(timeout_seconds: float = 5) -> None:
    """优雅停 worker（lifespan 关闭调）：置 stop_event 并等其退出。"""
    global _worker_task, _worker_stop
    if _worker_stop is not None:
        _worker_stop.set()
    if _worker_task is not None:
        try:
            await asyncio.wait_for(_worker_task, timeout=timeout_seconds)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _worker_task.cancel()
        except Exception:
            logger.exception("Tool job worker raised during shutdown.")
    _worker_task = None
    _worker_stop = None
