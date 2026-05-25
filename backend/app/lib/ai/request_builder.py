from app.lib.ai.context.assembler import assemble_context
from app.lib.ai.context.summarizer import build_context_summaries
from app.lib.ai.context.types import ContextAssembly
from app.lib.ai.prompting.renderer import render_prompt_context
from app.schemas.chat import ChatRequest
from app.shared.settings import get_settings


def build_provider_context(request: ChatRequest) -> ContextAssembly:
    settings = get_settings()
    summaries = build_context_summaries(
        request.messages,
        max_recent_messages=settings.context_max_recent_messages,
        max_recent_chars=settings.ai_context_max_recent_chars,
        max_summary_chars=settings.ai_context_max_summary_chars,
        max_memory_chars=settings.ai_context_max_memory_chars,
    )
    prompt_context = render_prompt_context(
        messages=request.messages,
        profile=settings.ai_prompt_profile,
        language=settings.ai_system_prompt_language,
        assistant_name=settings.ai_assistant_name,
        enable_dynamic_modules=settings.ai_prompt_enable_dynamic_modules,
        include_reasoning_boundary=settings.ai_prompt_include_reasoning_boundary,
        has_conversation_summary=bool(summaries.conversation_summary),
        has_memory=bool(summaries.memory),
        max_core_chars=settings.ai_prompt_max_core_chars,
        max_optional_chars=settings.ai_prompt_max_optional_chars,
    )
    return assemble_context(
        system_prompt=prompt_context.content,
        system_prompt_blocks=prompt_context.included_blocks,
        dropped_prompt_blocks=prompt_context.dropped_blocks,
        messages=request.messages,
        user_extra_instructions=(
            request.system_prompt if settings.allow_user_extra_instructions else None
        ),
        conversation_summary=summaries.conversation_summary,
        memory=summaries.memory,
        max_total_chars=settings.context_max_total_chars,
        max_recent_chars=settings.ai_context_max_recent_chars,
        max_recent_messages=settings.context_max_recent_messages,
        max_user_extra_chars=settings.ai_context_max_user_extra_chars,
        max_summary_chars=settings.ai_context_max_summary_chars,
        max_memory_chars=settings.ai_context_max_memory_chars,
        max_rag_chars=settings.ai_context_max_rag_chars,
        max_tool_chars=settings.ai_context_max_tool_chars,
    )


def build_provider_messages(request: ChatRequest) -> list[dict[str, str]]:
    return build_provider_context(request).messages
