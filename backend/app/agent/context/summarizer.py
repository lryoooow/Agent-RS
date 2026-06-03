from dataclasses import dataclass

from app.agent.context.budget import trim_to_budget
from app.agent.context.history import CLIENT_SYSTEM_PREFIX, select_recent_dialogue_messages
from app.schemas.chat import ChatMessage

SUMMARY_MAX_ITEMS = 10
MEMORY_MAX_ITEMS = 8
SNIPPET_MAX_CHARS = 180

IMPORTANT_KEYWORDS = (
    "必须",
    "不要",
    "不能",
    "需要",
    "偏好",
    "希望",
    "固定",
    "版本",
    "回退",
    "标签",
    "tag",
    "模型",
    "base-url",
    "base_url",
    "api key",
    "上下文",
    "提示词",
    "流式",
    "中文",
    "边界",
)


@dataclass(frozen=True)
class ContextSummaries:
    conversation_summary: str | None = None
    memory: str | None = None


def build_context_summaries(
    messages: list[ChatMessage],
    *,
    max_recent_messages: int | None,
    max_recent_chars: int | None,
    max_summary_chars: int | None,
    max_memory_chars: int | None,
) -> ContextSummaries:
    older_messages, _, _ = select_recent_dialogue_messages(
        messages,
        max_messages=max_recent_messages,
        max_chars=max_recent_chars,
    )
    return ContextSummaries(
        conversation_summary=summarize_older_dialogue(
            older_messages,
            max_chars=max_summary_chars,
        ),
        memory=extract_important_memory(
            older_messages,
            max_chars=max_memory_chars,
        ),
    )


def summarize_older_dialogue(
    messages: list[ChatMessage],
    *,
    max_chars: int | None,
) -> str | None:
    if not messages:
        return None

    items = [
        f"- {_role_label(message)}：{_snippet(message)}"
        for message in messages[-SUMMARY_MAX_ITEMS:]
        if message.content.strip()
    ]
    return _trim_or_none("\n".join(items), max_chars)


def extract_important_memory(
    messages: list[ChatMessage],
    *,
    max_chars: int | None,
) -> str | None:
    items: list[str] = []
    seen: set[str] = set()

    for message in messages:
        if not _has_important_signal(message.content):
            continue
        item = f"- {_role_label(message)}：{_snippet(message)}"
        if item in seen:
            continue
        seen.add(item)
        items.append(item)

    return _trim_or_none("\n".join(items[-MEMORY_MAX_ITEMS:]), max_chars)


def _trim_or_none(content: str, max_chars: int | None) -> str | None:
    text = trim_to_budget(content, max_chars)
    return text or None


def _role_label(message: ChatMessage) -> str:
    if message.role == "user":
        return "用户"
    if message.role == "assistant":
        return "助手"
    return "客户端 system 角色消息（非系统规则）"


def _snippet(message: ChatMessage) -> str:
    text = " ".join(message.content.split())
    if message.role == "system":
        text = f"{CLIENT_SYSTEM_PREFIX} {text}"
    return trim_to_budget(text, SNIPPET_MAX_CHARS)


def _has_important_signal(content: str) -> bool:
    normalized = content.lower()
    return any(keyword in normalized for keyword in IMPORTANT_KEYWORDS)
