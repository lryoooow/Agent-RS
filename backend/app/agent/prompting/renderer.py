from datetime import date
from app.core.settings import get_settings

from app.agent.context.budget import TRUNCATION_MARKER, trim_to_budget
from app.agent.prompting.loader import render_template
from app.agent.prompting.selector import DEFAULT_PROMPT_PROFILE, select_prompt_modules
from app.agent.prompting.types import PromptRenderResult
from app.schemas.chat import ChatMessage


def _as_of_date() -> date:
    """提示词里的"当前日期"。生产默认今天；AGENT_AS_OF_DATE 可覆盖。

    覆盖口是为评测可复现性开的：录制/重放的 pins 哈希必须与日期解耦，
    否则任何跨天续录或隔日重放都会被判 stale（2026-10-03 盲测中断暴露）。
    """
    override = get_settings().agent_as_of_date
    if override:
        return date.fromisoformat(override)
    return date.today()


def render_prompt_context(
    *,
    messages: list[ChatMessage],
    profile: str = DEFAULT_PROMPT_PROFILE,
    language: str = "zh-CN",
    assistant_name: str = "Agent-RS Assistant",
    current_date: date | None = None,
    enable_dynamic_modules: bool = True,
    include_reasoning_boundary: bool = True,
    has_conversation_summary: bool = False,
    has_memory: bool = False,
    has_rag_context: bool = False,
    has_tool_context: bool = False,
    max_core_chars: int | None = None,
    max_optional_chars: int | None = None,
) -> PromptRenderResult:
    modules = select_prompt_modules(
        profile=profile,
        messages=messages,
        enable_dynamic_modules=enable_dynamic_modules,
        include_reasoning_boundary=include_reasoning_boundary,
        has_conversation_summary=has_conversation_summary,
        has_memory=has_memory,
        has_rag_context=has_rag_context,
        has_tool_context=has_tool_context,
    )
    variables = {
        "template_version": "",
        "prompt_profile": profile,
        "language": language,
        "current_date": (current_date or _as_of_date()).isoformat(),
        "assistant_name": assistant_name,
    }

    rendered: list[str] = []
    included_blocks: list[str] = []
    dropped_blocks: list[str] = []

    for module in modules:
        variables["template_version"] = module.name
        content = render_template(module.template, variables)
        budget = max_core_chars if module.required else max_optional_chars
        content = trim_to_budget(content, budget)
        if not content:
            dropped_blocks.append(f"prompt:{module.name}")
            continue
        # 系统规则层若被预算从句中截断，显式标记（不静默生效半截规则）。
        if content.endswith(TRUNCATION_MARKER.strip()) or TRUNCATION_MARKER in content:
            dropped_blocks.append(f"prompt:{module.name}:truncated")
        rendered.append(content)
        included_blocks.append(f"prompt:{module.name}")

    content = "\n\n".join(rendered).strip()
    return PromptRenderResult(
        content=content,
        included_blocks=included_blocks,
        dropped_blocks=dropped_blocks,
        used_chars=len(content),
        profile=profile,
    )
