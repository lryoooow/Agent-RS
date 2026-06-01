from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache

from app.lib.ai.embedding.client import create_embedding_client
from app.shared.logging import log_event
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)


class EmbeddingUnavailableError(RuntimeError):
    pass


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._semaphore = asyncio.Semaphore(self.settings.embedding_background_concurrency)
        self._client = create_embedding_client(self.settings) if self.available else None

    @property
    def available(self) -> bool:
        return bool(
            self.settings.resolved_embedding_base_url
            and self.settings.resolved_embedding_api_key
            and self.settings.embedding_model
            and self.settings.embedding_dimensions > 0
        )

    async def embed_text(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        cleaned = [text.strip() for text in texts]
        if not cleaned or any(not text for text in cleaned):
            raise EmbeddingUnavailableError("Embedding input cannot be empty.")
        if not self.available:
            raise EmbeddingUnavailableError("Embedding service is not configured.")

        vectors: list[list[float]] = []
        batch_size = max(1, self.settings.embedding_batch_size)
        for cursor in range(0, len(cleaned), batch_size):
            vectors.extend(await self._embed_batch_once(cleaned[cursor : cursor + batch_size]))
        log_event(
            logger,
            "embedding.batch",
            total=len(cleaned),
            batches=(len(cleaned) + batch_size - 1) // batch_size,
            model=self.settings.embedding_model,
            dimensions=self.settings.embedding_dimensions,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return vectors

    async def _embed_batch_once(self, texts: list[str]) -> list[list[float]]:
        async with self._semaphore:
            if self._client is None:
                self._client = create_embedding_client(self.settings)
            response = await self._client.embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
                dimensions=self.settings.embedding_dimensions,
                encoding_format="float",
            )

        response_data = sorted(
            response.data,
            key=lambda item: _read_embedding_item(item, "index", 0),
        )
        if len(response_data) != len(texts):
            raise EmbeddingUnavailableError(
                f"Embedding response count mismatch: expected {len(texts)}, got {len(response_data)}."
            )
        vectors = [_read_embedding_item(item, "embedding", []) for item in response_data]
        for vector in vectors:
            if len(vector) != self.settings.embedding_dimensions:
                raise EmbeddingUnavailableError(
                    "Embedding dimensions mismatch: "
                    f"expected {self.settings.embedding_dimensions}, got {len(vector)}."
                )
        return vectors

    async def ping(self) -> bool:
        if not self.available:
            return False
        try:
            await self.embed_text("ping")
        except Exception:
            logger.warning("Embedding startup ping failed.", exc_info=True)
            return False
        logger.info("Embedding startup ping succeeded.")
        return True


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


def _read_embedding_item(item, field: str, default):
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)
