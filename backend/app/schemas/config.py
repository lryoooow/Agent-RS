from pydantic import BaseModel


class ConfigResponse(BaseModel):
    provider: str
    base_url_configured: bool
    api_key_configured: bool
    default_model: str | None = None
    allow_client_provider_config: bool
    system_prompt_template: str
    system_prompt_language: str
    allow_user_extra_instructions: bool
