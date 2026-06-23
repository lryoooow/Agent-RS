from __future__ import annotations

import json
import logging

from app.agent.config import resolve_ai_config
from app.agent.embedding.service import get_embedding_service
from app.agent.provider import create_chat_client
from app.db.pool import fetch_optional_pool
from app.db.repositories.memory import insert_memory
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

MEMORY_JUDGE_INPUT_MAX_CHARS = 3000

MEMORY_JUDGE_PROMPT = """你负责判断对话片段是否值得长期记忆。
只记录用户稳定偏好、长期事实、项目约束、反复需要遵守的工作方式。
不要记录一次性问题、普通寒暄、模型内部过程、密钥、隐私敏感信息。
只返回 JSON：{"remember": true|false, "content": "...", "tags": ["..."]}

示例（仅供格式与判别参考，不要照搬内容）：
用户: 以后回复我都用中文，并且固定用 qwen3.7-max 模型。
-> {"remember": true, "content": "用户偏好：始终用中文回复，固定使用 qwen3.7-max 模型。", "tags": ["语言偏好", "模型偏好"]}
用户: 帮我算一下 3 乘以 7 等于多少？
-> {"remember": false, "content": "", "tags": []}
用户: 你好呀，在吗？
-> {"remember": false, "content": "", "tags": []}
用户: 我们项目规定影像分析结论必须标注数据来源和时间。
-> {"remember": true, "content": "项目约束：影像分析结论必须标注数据来源与时间。", "tags": ["项目约束"]}"""


def _parse_memory_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("Memory judge payload is not a JSON object.", raw, 0)
    return payload


def _short_log_value(value: str, limit: int = 240) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


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
    pool = await fetch_optional_pool()
    if pool is None:
        return

    clipped_user_content = user_content[:MEMORY_JUDGE_INPUT_MAX_CHARS]
    clipped_assistant_content = assistant_content[:MEMORY_JUDGE_INPUT_MAX_CHARS]

    try:
        config = resolve_ai_config(request_model=settings.memory_judge_model or None)
        client = create_chat_client(config)
        response = await client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": MEMORY_JUDGE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "用户消息：\n"
                        f"{clipped_user_content}\n\n助手回复：\n{clipped_assistant_content}"
                    ),
                },
            ],
            stream=False,
        )
        raw = response.choices[0].message.content or "{}"
        try:
            payload = _parse_memory_payload(raw)
        except json.JSONDecodeError:
            logger.warning("Memory judge returned non-JSON payload: %s", _short_log_value(raw))
            return
        if not payload.get("remember"):
            return
        content = str(payload.get("content") or "").strip()
        if not content:
            return
        embedding = await get_embedding_service().embed_text(content)
        async with pool.acquire() as conn:
            await insert_memory(
                conn,
                user_id=user_id,
                content=content,
                embedding=embedding,
                source_session_id=conversation_id,
                metadata={
                    "tags": payload.get("tags") or [],
                    "source_message_id": source_message_id,
                },
            )
    except Exception:
        logger.exception("Memory judge pipeline failed.")
