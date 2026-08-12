"""AutoGen structured Agent that extracts durable user memories."""

from __future__ import annotations

import logging

from app.agent.config import resolve_ai_config
from app.agent.engine import MemoryDecision, PgVectorMemory, decide_memory
from app.agent.memory_types import DEFAULT_IMPORTANCE, DEFAULT_MEMORY_TYPE, MEMORY_TYPES
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool

logger = logging.getLogger(__name__)

MEMORY_JUDGE_INPUT_MAX_CHARS = 3000

MEMORY_JUDGE_PROMPT = """你负责判断对话片段是否值得长期记忆。
只记录用户稳定偏好、长期事实、项目约束和反复需要遵守的工作方式。
不要记录一次性问题、寒暄、模型内部过程、密钥或隐私敏感信息。

memory_type 只能是 fact、preference、constraint、project：
- preference：用户稳定偏好；constraint：违反就会出错的硬约束；
- project：长期项目与数据设定；fact：其它稳定客观事实。
importance 为 0.0-1.0；低于 0.4 的普通信息通常 remember=false。
remember=false 时 content 为空、tags 为空。
""".strip()


def _normalize_memory_type(value: object) -> str:
    if isinstance(value, str) and value in MEMORY_TYPES:
        return value
    if value not in (None, ""):
        logger.info("记忆判官给出未知 memory_type=%r，回退为 %s", value, DEFAULT_MEMORY_TYPE)
    return DEFAULT_MEMORY_TYPE


def _normalize_importance(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_IMPORTANCE
    if number > 1.0:
        number = number / 100.0 if number <= 100.0 else 1.0
    return min(1.0, max(0.0, number))


async def maybe_store_memory(
    *,
    user_id: str,
    conversation_id: str,
    user_content: str,
    assistant_content: str,
    source_message_id: str,
) -> None:
    settings = get_settings()
    if not settings.storage_active or not settings.memory_judge_enabled:
        return
    if len(user_content.strip()) < settings.memory_judge_min_user_chars:
        return
    if await fetch_optional_pool() is None:
        return

    config = resolve_ai_config(request_model=settings.memory_judge_model or None)
    try:
        task = (
            "用户消息：\n"
            f"{user_content[:MEMORY_JUDGE_INPUT_MAX_CHARS]}\n\n"
            "助手回复：\n"
            f"{assistant_content[:MEMORY_JUDGE_INPUT_MAX_CHARS]}"
        )
        decision = await decide_memory(
            config=config,
            model_override=settings.memory_judge_model or None,
            system_message=MEMORY_JUDGE_PROMPT,
            task=task,
        )
        if decision is None:
            logger.warning("Memory judge returned no structured decision; skipping extraction.")
            return
        content = decision.content.strip()
        if not decision.remember or not content:
            return

        await PgVectorMemory(user_id=user_id).add_text(
            content,
            metadata={
                "memory_type": _normalize_memory_type(decision.memory_type),
                "importance": _normalize_importance(decision.importance),
                "tags": decision.tags,
                "source_session_id": conversation_id,
                "source_message_id": source_message_id,
            },
        )
    except Exception:
        logger.exception("Memory judge pipeline failed.")
