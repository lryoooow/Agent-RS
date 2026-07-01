from fastapi import APIRouter

from app.schemas.config import ConfigResponse
from app.core.settings import get_settings

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigResponse)
async def config() -> ConfigResponse:
    settings = get_settings()
    return ConfigResponse(
        provider=settings.ai_provider,
        base_url_configured=bool(settings.ai_base_url),
        api_key_configured=bool(settings.ai_api_key),
        default_model=settings.ai_default_model,
        allow_client_provider_config=settings.allow_client_provider_config,
        prompt_profile=settings.ai_prompt_profile,
        prompt_dynamic_modules_enabled=settings.ai_prompt_enable_dynamic_modules,
        system_prompt_language=settings.ai_system_prompt_language,
        allow_user_extra_instructions=settings.allow_user_extra_instructions,
        web_search_enabled=bool(
            settings.tavily_api_key.strip() and settings.agent_web_search_max_calls > 0
        ),
        web_search_configured=bool(settings.tavily_api_key.strip()),
        auth_required=settings.auth_required,
        invite_required=False,  # 邀请码准入已于 2026-06-24 移除
    )
