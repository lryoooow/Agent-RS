from app.lib.ai.prompting.types import PromptModule
from app.schemas.chat import ChatMessage

DEFAULT_PROMPT_PROFILE = "chatbot_core_v1"

PROMPT_PROFILES: dict[str, tuple[str, ...]] = {
    DEFAULT_PROMPT_PROFILE: ("core_identity_v1", "security_boundary_v1", "context_priority_v1"),
}

PROMPT_MODULES: dict[str, PromptModule] = {
    "core_identity_v1": PromptModule("core_identity_v1", "core_identity_v1", required=True),
    "context_priority_v1": PromptModule(
        "context_priority_v1",
        "context_priority_v1",
        required=True,
    ),
    "security_boundary_v1": PromptModule(
        "security_boundary_v1",
        "security_boundary_v1",
        required=True,
    ),
    "output_format_v1": PromptModule("output_format_v1", "output_format_v1"),
    "document_task_v1": PromptModule("document_task_v1", "document_task_v1"),
    "memory_policy_v1": PromptModule("memory_policy_v1", "memory_policy_v1"),
    "rag_policy_v1": PromptModule("rag_policy_v1", "rag_policy_v1"),
    "tool_policy_v1": PromptModule("tool_policy_v1", "tool_policy_v1"),
    "reasoning_boundary_v1": PromptModule("reasoning_boundary_v1", "reasoning_boundary_v1"),
}

DOCUMENT_KEYWORDS = (
    "文档",
    "文件",
    "摘要",
    "总结",
    "提纲",
    "改写",
    "润色",
    "翻译",
    "提取",
    "字段",
)
FORMAT_KEYWORDS = (
    "json",
    "表格",
    "markdown",
    "代码",
    "配置",
    "命令",
    "步骤",
    "清单",
)


def select_prompt_modules(
    *,
    profile: str,
    messages: list[ChatMessage],
    enable_dynamic_modules: bool,
    include_reasoning_boundary: bool,
    has_conversation_summary: bool = False,
    has_memory: bool = False,
    has_rag_context: bool = False,
    has_tool_context: bool = False,
) -> list[PromptModule]:
    module_names = list(PROMPT_PROFILES.get(profile, ()))
    if not module_names:
        from app.lib.ai.errors import ConfigError

        raise ConfigError(f"AI prompt profile not found: {profile}")

    text = _message_text(messages)

    if include_reasoning_boundary:
        module_names.append("reasoning_boundary_v1")
    if enable_dynamic_modules:
        if _contains_any(text, DOCUMENT_KEYWORDS) or _has_long_user_message(messages):
            module_names.append("document_task_v1")
        if _contains_any(text, FORMAT_KEYWORDS):
            module_names.append("output_format_v1")
    if has_conversation_summary or has_memory:
        module_names.append("memory_policy_v1")
    if has_rag_context:
        module_names.append("rag_policy_v1")
    if has_tool_context:
        module_names.append("tool_policy_v1")

    return [PROMPT_MODULES[name] for name in _dedupe(module_names)]


def _message_text(messages: list[ChatMessage]) -> str:
    return "\n".join(message.content for message in messages if message.role == "user").lower()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _has_long_user_message(messages: list[ChatMessage]) -> bool:
    return any(message.role == "user" and len(message.content) >= 1200 for message in messages)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
