import httpx
from app.api.errors import api_error
from fastapi import APIRouter, Depends, HTTPException

from app.agent.config import resolve_ai_config
from app.agent.engine import available_flows
from app.api.deps import require_authenticated_user
from app.core.settings import get_settings
from app.schemas.config import (
    AvailableModel,
    ConfigResponse,
    ModelListRequest,
    ModelListResponse,
)

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
        agent_framework="autogen",
        available_flows=available_flows(),
        auto_flow_enabled=settings.agent_auto_flow_enabled,
    )


@router.post(
    "/config/models",
    response_model=ModelListResponse,
    dependencies=[Depends(require_authenticated_user)],
)
async def list_models(request: ModelListRequest) -> ModelListResponse:
    """List models from the active OpenAI-compatible provider.

    Credentials arrive in the JSON body, are SSRF-validated by resolve_ai_config,
    and are used once.  The raw provider response and credentials are never logged
    or returned to the browser.
    """
    resolved = resolve_ai_config(
        request_model=request.model,
        provider_config=request.provider_config,
    )
    url = f"{resolved.base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(
            timeout=min(resolved.timeout_seconds, 20.0),
            trust_env=resolved.trust_env_proxy,
        ) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {resolved.api_key}"},
            )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            raise api_error(502, "PROVIDER_AUTH_FAILED", "模型供应商鉴权失败，请检查 API Key。") from exc
        raise api_error(502, "PROVIDER_PROBE_FAILED", f"模型供应商返回错误（HTTP {status}）。") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise api_error(502, "PROVIDER_PROBE_FAILED", "无法读取模型列表，请检查供应商地址与网络。") from exc

    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        raise api_error(502, "PROVIDER_PROBE_FAILED", "模型供应商返回了无效的模型列表。")

    models_by_id: dict[str, AvailableModel] = {}
    for raw in raw_models[:1000]:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or "").strip()
        if not model_id or len(model_id) > 256:
            continue
        created_raw = raw.get("created")
        created = created_raw if isinstance(created_raw, int) and created_raw >= 0 else None
        owner_raw = raw.get("owned_by")
        owner = str(owner_raw).strip()[:128] if owner_raw else None
        models_by_id[model_id] = AvailableModel(
            id=model_id,
            created=created,
            owned_by=owner or None,
        )
    models = sorted(
        models_by_id.values(),
        key=lambda item: (item.created is not None, item.created or 0, item.id.lower()),
        reverse=True,
    )
    return ModelListResponse(models=models, current_model=resolved.model)
