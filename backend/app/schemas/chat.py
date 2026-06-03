from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be empty.")
        return value


class ProviderConfig(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None
    system_prompt: str | None = None
    stream: bool = False
    provider_config: ProviderConfig | None = None
    conversation_id: str | None = None
    use_memory: bool = True
    use_rag: bool = False


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class NDVIStats(BaseModel):
    min: float
    max: float
    mean: float
    std: float


class ToolExecutionInfo(BaseModel):
    mode: Literal["docker_mcp", "local_subprocess", "local_fallback", "failed"]
    fallback_used: bool = False
    error_code: str | None = None


class GeospatialPreviewResult(BaseModel):
    type: Literal["preview"]
    imagery_id: str
    result_url: str
    bounds: tuple[float, float, float, float] | None = None


class GeospatialNDVIResult(BaseModel):
    type: Literal["ndvi"]
    imagery_id: str
    result_url: str
    bounds: tuple[float, float, float, float] | None = None
    stats: NDVIStats
    execution: ToolExecutionInfo | None = None


GeospatialResult = GeospatialPreviewResult | GeospatialNDVIResult


class ChatResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: Usage | None = None
    finish_reason: str | None = None
    conversation_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    retrieved_chunks: int = 0
    rag_trace: dict | None = None
    agent_trace: dict | None = None
    geospatial_result: GeospatialResult | None = None
