from pydantic import BaseModel


class ConfigResponse(BaseModel):
    provider: str
    base_url_configured: bool
    api_key_configured: bool
    default_model: str | None = None
    allow_client_provider_config: bool
    prompt_profile: str
    prompt_dynamic_modules_enabled: bool
    system_prompt_language: str
    allow_user_extra_instructions: bool
    web_search_enabled: bool = False
    web_search_configured: bool = False
    # 强制登录：前端据此决定是否在未登录时全屏拦截到 AuthGate。
    auth_required: bool = False
    # 注册需邀请码：前端据此在注册表单显示邀请码输入框。
    invite_required: bool = True
