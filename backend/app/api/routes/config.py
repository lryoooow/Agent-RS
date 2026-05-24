from fastapi import APIRouter

from app.schemas.config import ConfigResponse
from app.shared.settings import get_settings

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
    )
