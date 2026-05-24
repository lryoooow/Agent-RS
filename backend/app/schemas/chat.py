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


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ChatResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: Usage | None = None
    finish_reason: str | None = None
