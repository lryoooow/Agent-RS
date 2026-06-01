import pytest

from app.lib.ai.embedding.service import EmbeddingService
from app.shared.settings import get_settings


@pytest.mark.asyncio
async def test_embedding_service_batches_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class FakeEmbeddings:
        async def create(self, **kwargs):
            batch = kwargs["input"]
            calls.append(batch)
            assert kwargs["model"] == "text-embedding-v4"
            assert kwargs["dimensions"] == 3
            assert kwargs["encoding_format"] == "float"
            return FakeResponse(
                [
                    {"index": index, "embedding": [float(index), 0.0, 1.0]}
                    for index, _ in enumerate(batch)
                ]
            )

    class FakeClient:
        embeddings = FakeEmbeddings()

    class FakeResponse:
        def __init__(self, data):
            self.data = data

    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-v4")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "3")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "10")
    get_settings.cache_clear()
    monkeypatch.setattr("app.lib.ai.embedding.service.create_embedding_client", lambda _: FakeClient())

    try:
        vectors = await EmbeddingService().embed_batch([f"text-{index}" for index in range(25)])
    finally:
        get_settings.cache_clear()

    assert [len(call) for call in calls] == [10, 10, 5]
    assert len(vectors) == 25
    assert all(len(vector) == 3 for vector in vectors)
