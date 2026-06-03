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
    app_reload: bool = False
    log_level: str = "INFO"
    storage_upload_dir: str = "backend/storage/uploads"
    storage_orphan_max_age_hours: int = 24

    ai_provider: str = "openai-compatible"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_default_model: str = "gpt-4.1-mini"
    ai_thinking_budget: int = 2048
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
    ai_assistant_name: str = "Agent-RS Assistant"

    allow_client_provider_config: bool = False
    allow_user_extra_instructions: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_json_body_bytes: int = 2_000_000

    tavily_api_key: str = ""
    tavily_search_url: str = "https://api.tavily.com/search"
    tavily_search_depth: str = "basic"
    agent_planning_model: str = "qwen3.6-flash"
    agent_web_search_max_calls: int = 1
    agent_web_search_max_results: int = 5
    agent_web_search_min_score: float = 0.4
    agent_web_search_timeout_seconds: float = 15
    agent_web_search_input_max_chars: int = 2000
    agent_web_search_result_max_chars: int = 6000
    agent_decision_cache_ttl_seconds: float = 1800
    agent_decision_cache_max_size: int = 256
    agent_result_cache_ttl_seconds: float = 300
    agent_result_cache_max_size: int = 64
    agent_web_search_rerank_enabled: bool = True
    agent_web_search_rerank_top_n: int = 5

    auth_enabled: bool = True
    auth_secret_key: str = "dev-change-me"
    auth_session_cookie_name: str = "chatbot_session"
    auth_session_days: int = 14
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_password_min_length: int = 8

    database_enabled: bool = False
    database_url: str = ""
    database_pool_min_size: int = 1
    database_pool_max_size: int = 5

    default_user_id: str = "00000000-0000-4000-8000-000000000001"
    default_workspace_id: str = "00000000-0000-4000-8000-000000000001"
    default_user_email: str = "default@local.chatbot"
    default_user_name: str = "Default User"
    default_workspace_slug: str = "default"
    default_workspace_name: str = "Default Workspace"

    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 10
    embedding_background_concurrency: int = 8
    embedding_max_retries: int = 2
    embedding_retry_base_delay_seconds: float = 0.5

    rerank_enabled: bool = True
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = "gte-rerank-v2"
    rerank_top_n: int = 5
    rag_candidate_limit: int = 12
    rag_rrf_k: int = 60
    rag_mmr_enabled: bool = True
    rag_mmr_lambda: float = 0.7

    memory_judge_enabled: bool = True
    memory_judge_model: str = ""
    memory_judge_min_user_chars: int = 10
    memory_retrieval_limit: int = 5
    rag_retrieval_limit: int = 5

    document_max_file_bytes: int = 20 * 1024 * 1024
    document_max_pdf_pages: int = 200
    document_max_chunks: int = 50
    chunk_size: int = 800
    chunk_overlap: int = 100
    chunk_min_size: int = 200
    document_ocr_max_pages: int = 20
    document_ocr_timeout_seconds: int = 120
    document_ocr_min_chars_per_page: int = 50
    document_ocr_languages: str = "chi_sim+eng"

    imagery_upload_dir: str = "storage/imagery"
    imagery_max_file_bytes: int = 500_000_000
    imagery_working_max_dimension: int = 4096
    imagery_preview_max_dimension: int = 2048
    imagery_compression: str = "deflate"
    ndvi_docker_timeout_seconds: int = 120
    ndvi_mcp_image: str = "ndvi-mcp:0.1.0"
    ndvi_mcp_use_docker: bool = True
    ndvi_mcp_allow_local_fallback: bool = True
    ndvi_mcp_memory_limit: str = "2g"
    ndvi_mcp_cpus: float = 2.0
    ndvi_mcp_network: str = "none"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def context_max_total_chars(self) -> int:
        return self.ai_context_max_total_chars or self.ai_max_context_chars

    @property
    def context_max_recent_messages(self) -> int:
        return self.ai_context_max_recent_messages or self.ai_max_history_messages

    @property
    def resolved_embedding_base_url(self) -> str:
        return self.embedding_base_url or self.ai_base_url

    @property
    def resolved_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.ai_api_key

    @property
    def resolved_rerank_base_url(self) -> str:
        if self.rerank_base_url:
            return self.rerank_base_url
        if "dashscope.aliyuncs.com" in self.ai_base_url:
            return "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        return ""

    @property
    def resolved_rerank_api_key(self) -> str:
        return self.rerank_api_key or self.ai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
