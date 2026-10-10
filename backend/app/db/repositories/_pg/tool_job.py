from __future__ import annotations

import json
from typing import Any

from app.db.sanitize import parse_jsonb, sanitize_json, sanitize_text


async def create_tool_job(
    conn,
    *,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    imagery_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    max_attempts: int = 3,
    job_id: str | None = None,
) -> str:
    """新建一条 pending 工具任务，返回 job_id。child 执行前调用。"""
    row = await conn.fetchrow(
        """
        INSERT INTO public.tool_jobs (
          tool_name, arguments, imagery_id, user_id, conversation_id, max_attempts, id
        )
        VALUES ($1, $2::jsonb, $3, $4, $5, $6, COALESCE($7::uuid, gen_random_uuid()))
        RETURNING id::text
        """,
        sanitize_text(tool_name),
        json.dumps(sanitize_json(arguments or {}), ensure_ascii=False),
        sanitize_text(imagery_id) if imagery_id else None,
        user_id,
        conversation_id,
        max_attempts,
        job_id,
    )
    return row["id"]


async def mark_job_running(conn, *, job_id: str) -> None:
    """转 running，attempts+1，刷新心跳。child 真正执行前调用。"""
    await conn.execute(
        """
        UPDATE public.tool_jobs
        SET status = 'running',
            attempts = attempts + 1,
            heartbeat_at = now(),
            updated_at = now()
        WHERE id = $1::uuid AND status = 'pending'
        """,
        job_id,
    )


async def mark_job_complete(conn, *, job_id: str, result: dict[str, Any] | None = None, expected_attempt: int | None = None) -> None:
    """转 complete 终态，写结果摘要。"""
    await conn.execute(
        """
        UPDATE public.tool_jobs
        SET status = 'complete',
            result = $2::jsonb,
            error_code = NULL,
            error_message = NULL,
            updated_at = now()
        WHERE id = $1::uuid AND status IN ('pending', 'running')
          AND ($3::int IS NULL OR attempts = $3)
        """,
        job_id,
        json.dumps(sanitize_json(result or {}), ensure_ascii=False),
        expected_attempt,
    )


async def mark_job_failed(
    conn,
    *,
    job_id: str,
    error_code: str | None = None,
    error_message: str | None = None,
    expected_attempt: int | None = None,
) -> None:
    """转 failed 终态，写错误。重试上限的判定由 claim_stale_job 的 attempts < max_attempts 兜住。"""
    await conn.execute(
        """
        UPDATE public.tool_jobs
        SET status = 'failed',
            error_code = $2,
            error_message = $3,
            updated_at = now()
        WHERE id = $1::uuid AND status IN ('pending', 'running')
          AND ($4::int IS NULL OR attempts = $4)
        """,
        job_id,
        sanitize_text(error_code) if error_code else None,
        sanitize_text(error_message) if error_message else None,
        expected_attempt,
    )


async def heartbeat_job(conn, *, job_id: str, expected_attempt: int | None = None) -> None:
    """刷新 running 任务心跳，防长任务被 worker 误判为孤儿。"""
    await conn.execute(
        "UPDATE public.tool_jobs SET heartbeat_at = now(), updated_at = now() WHERE id = $1::uuid AND status = 'running' AND ($2::int IS NULL OR attempts = $2)",
        job_id,
        expected_attempt,
    )


async def mark_job_interrupted(conn, *, job_id: str, outcome_unknown: bool, expected_attempt: int | None = None) -> None:
    await conn.execute(
        """
        UPDATE public.tool_jobs
        SET status = $2, error_code = $3, error_message = $4, updated_at = now()
        WHERE id = $1::uuid AND status IN ('pending', 'running')
          AND ($5::int IS NULL OR attempts = $5)
        """,
        job_id,
        'outcome_unknown' if outcome_unknown else 'cancelled',
        'tool_outcome_unknown' if outcome_unknown else 'tool_cancelled',
        'Execution was interrupted after the runner started; completion is unconfirmed.'
        if outcome_unknown else 'Execution was cancelled before the runner started.',
        expected_attempt,
    )


async def claim_stale_job(conn, *, stale_after_seconds: int) -> dict[str, Any] | None:
    """原子领取一个孤儿任务：pending，或 running 但心跳超时（被重启打断）。

    并发安全核心：FOR UPDATE SKIP LOCKED 确保多 worker/多协程同时跑时同一 job 只被一个领取，
    其余跳过（不阻塞、不重复执行）。领取即转 running + attempts+1 + 刷心跳，避免立刻被重领。
    仅领 attempts < max_attempts 的——到上限的失败任务不再重试（杜绝无界重跑）。
    返回被领任务的完整行；无可领任务返回 None。
    """
    row = await conn.fetchrow(
        """
        WITH claimable AS (
          SELECT id, status AS previous_status
          FROM public.tool_jobs
          WHERE attempts < max_attempts
            AND (
              (status = 'pending'
               AND (heartbeat_at IS NULL OR heartbeat_at < now()))
              OR (status = 'running'
                  AND (heartbeat_at IS NULL
                       OR heartbeat_at < now() - make_interval(secs => $1)))
            )
          ORDER BY created_at
          FOR UPDATE SKIP LOCKED
          LIMIT 1
        )
        UPDATE public.tool_jobs t
        SET status = 'running',
            attempts = t.attempts + 1,
            heartbeat_at = now(),
            updated_at = now()
        FROM claimable
        WHERE t.id = claimable.id
        RETURNING t.id::text, t.tool_name, t.arguments, t.imagery_id, t.user_id,
                  t.conversation_id, t.attempts, t.max_attempts, claimable.previous_status
        """,
        stale_after_seconds,
    )
    if row is None:
        return None
    data = dict(row)
    data["arguments"] = parse_jsonb(data.get("arguments")) or {}
    return data


async def finalize_exhausted_jobs(conn, *, stale_after_seconds: int) -> None:
    await conn.execute(
        """
        UPDATE public.tool_jobs
        SET status = 'outcome_unknown', error_code = 'tool_recovery_exhausted',
            error_message = 'Recovery limit reached with no confirmed result.', updated_at = now()
        WHERE status IN ('pending', 'running') AND attempts >= max_attempts
          AND (heartbeat_at IS NULL OR heartbeat_at < now() - make_interval(secs => $1))
        """,
        stale_after_seconds,
    )


async def get_tool_job(conn, *, job_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    """取单条任务。给 user_id 时按属主过滤。"""
    owner_clause = "AND user_id = $2" if user_id else ""
    params: tuple[Any, ...] = (job_id, user_id) if user_id else (job_id,)
    row = await conn.fetchrow(
        f"""
        SELECT id::text, status, tool_name, arguments, imagery_id, user_id, conversation_id,
               result, error_code, error_message, attempts, max_attempts,
               heartbeat_at, created_at, updated_at
        FROM public.tool_jobs
        WHERE id = $1::uuid
        {owner_clause}
        """,
        *params,
    )
    if row is None:
        return None
    data = dict(row)
    data["arguments"] = parse_jsonb(data.get("arguments")) or {}
    data["result"] = parse_jsonb(data.get("result"))
    return data
