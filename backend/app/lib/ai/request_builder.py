from app.lib.ai.prompts import build_messages
from app.schemas.chat import ChatRequest
from app.shared.settings import get_settings


def build_provider_messages(request: ChatRequest) -> list[dict[str, str]]:
    settings = get_settings()
    return build_messages(
        request.messages,
        request.system_prompt,
        max_history_messages=settings.ai_max_history_messages,
        max_context_chars=settings.ai_max_context_chars,
        system_prompt_template=settings.ai_system_prompt_template,
        system_prompt_language=settings.ai_system_prompt_language,
        assistant_name=settings.ai_assistant_name,
        allow_user_extra_instructions=settings.allow_user_extra_instructions,
    )
