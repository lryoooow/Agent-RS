from types import SimpleNamespace

from app.agent.config import ResolvedAIConfig
from app.agent.normalizer import normalize_chat_response


def test_normalize_openai_compatible_response() -> None:
    config = ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.com/v1",
        api_key="secret",
        model="fallback-model",
        timeout_seconds=60,
        max_retries=2,
        trust_env_proxy=False,
    )
    response = SimpleNamespace(
        model="provider-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=3,
            completion_tokens=4,
            total_tokens=7,
        ),
    )

    result = normalize_chat_response(response, config)

    assert result.content == "hello"
    assert result.model == "provider-model"
    assert result.provider == "openai-compatible"
    assert result.usage
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 4
    assert result.usage.total_tokens == 7
    assert result.finish_reason == "stop"


def test_normalize_response_does_not_return_reasoning_content() -> None:
    config = ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.com/v1",
        api_key="secret",
        model="fallback-model",
        timeout_seconds=60,
        max_retries=2,
        trust_env_proxy=False,
    )
    response = SimpleNamespace(
        model="provider-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="final answer", reasoning_content="reasoning notes"),
                finish_reason="stop",
            )
        ],
        usage=None,
    )

    result = normalize_chat_response(response, config)

    assert result.content == "final answer"
    assert "reasoning" not in result.model_dump()


def test_normalize_response_splits_think_tags() -> None:
    config = ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.com/v1",
        api_key="secret",
        model="fallback-model",
        timeout_seconds=60,
        max_retries=2,
        trust_env_proxy=False,
    )
    response = SimpleNamespace(
        model="provider-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="<think>reasoning notes</think>final answer"),
                finish_reason="stop",
            )
        ],
        usage=None,
    )

    result = normalize_chat_response(response, config)

    assert result.content == "final answer"
    assert "reasoning" not in result.model_dump()
