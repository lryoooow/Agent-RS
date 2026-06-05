import pytest

from app.agent.search.cache import CachedDecision, DecisionCache
from app.agent.embedding.service import EmbeddingService
from app.core.logging import _format_field


def test_decision_cache_is_scoped() -> None:
    cache = DecisionCache()
    cache.put_decision("latest python", CachedDecision.SEARCH, scope="user-a|conv-a")
    cache.put_decision("latest python", CachedDecision.NO_SEARCH, scope="user-b|conv-b")

    assert cache.get_decision("latest python", scope="user-a|conv-a") == CachedDecision.SEARCH
    assert cache.get_decision("latest python", scope="user-b|conv-b") == CachedDecision.NO_SEARCH
    assert cache.get_decision("latest python", scope="user-a|conv-b") is None


@pytest.mark.asyncio
async def test_embedding_batch_retries_transient_failures(monkeypatch) -> None:
    service = EmbeddingService()
    service.settings.embedding_max_retries = 2
    service.settings.embedding_retry_base_delay_seconds = 0
    calls = 0

    async def fake_embed_once(texts):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("rate limited")
        return [[0.1] * service.settings.embedding_dimensions for _ in texts]

    monkeypatch.setattr(service, "_embed_batch_once", fake_embed_once)

    vectors = await service._embed_batch_with_retry(["hello"])

    assert calls == 2
    assert len(vectors) == 1


def test_log_event_masks_sensitive_fields() -> None:
    assert _format_field("api_key", "secret-value") == "api_key=***"
    assert _format_field("authorization", "Bearer token") == "authorization=***"
    assert _format_field("normal", "value") == "normal=value"
