from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "0.0.0.0"
    app_port: int = 3000

    ai_provider: str = "openai-compatible"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_default_model: str = "gpt-4.1-mini"
    ai_timeout_seconds: float = 60
    ai_max_retries: int = 2
    ai_trust_env_proxy: bool = False
    ai_max_history_messages: int = 24
    ai_max_context_chars: int = 24000
    ai_context_max_total_chars: int | None = None
    ai_context_max_recent_chars: int = 16000
    ai_context_max_recent_messages: int | None = None
    ai_context_max_user_extra_chars: int = 2000
    ai_context_max_summary_chars: int = 3000
    ai_context_max_memory_chars: int = 3000
    ai_context_max_rag_chars: int = 6000
    ai_context_max_tool_chars: int = 3000
    ai_prompt_profile: str = "chatbot_core_v1"
    ai_prompt_enable_dynamic_modules: bool = True
    ai_prompt_include_reasoning_boundary: bool = True
    ai_prompt_max_core_chars: int | None = None
    ai_prompt_max_optional_chars: int | None = None
    ai_system_prompt_language: str = "zh-CN"
    ai_assistant_name: str = "Chatbot AI Assistant"

    allow_client_provider_config: bool = True
    allow_user_extra_instructions: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def context_max_total_chars(self) -> int:
        return self.ai_context_max_total_chars or self.ai_max_context_chars

    @property
    def context_max_recent_messages(self) -> int:
        return self.ai_context_max_recent_messages or self.ai_max_history_messages


@lru_cache
def get_settings() -> Settings:
    return Settings()
