from pydantic import BaseModel, Field

from app.schemas.chat import ProviderConfig


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
    agent_framework: str = "autogen"
    available_flows: list[str] = Field(default_factory=list)
    auto_flow_enabled: bool = True


class ModelListRequest(BaseModel):
    provider_config: ProviderConfig | None = None
    model: str | None = None


class AvailableModel(BaseModel):
    id: str
    created: int | None = None
    owned_by: str | None = None


class ModelListResponse(BaseModel):
    models: list[AvailableModel] = Field(default_factory=list)
    current_model: str
