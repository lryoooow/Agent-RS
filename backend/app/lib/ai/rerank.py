from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

import httpx

from app.shared.settings import get_settings
from app.shared.logging import log_event

logger = logging.getLogger(__name__)


class RerankService:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def available(self) -> bool:
        return bool(
            self.settings.rerank_enabled
            and self.settings.resolved_rerank_base_url
            and self.settings.resolved_rerank_api_key
            and self.settings.rerank_model
        )

    async def rerank(
        self,
        *,
        query: str,
        items: list[dict[str, Any]],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        started = time.perf_counter()
        if not self.available or not query.strip() or not items:
            selected = items[: top_n or len(items)]
            log_event(
                logger,
                "rag.rerank",
                enabled=False,
                candidates=len(items),
                top_n=len(selected),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
            return selected

        documents = [str(item.get("content") or "") for item in items]
        selected_top_n = min(top_n or self.settings.rerank_top_n, len(documents))
        try:
            async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
                response = await client.post(
                    self.settings.resolved_rerank_base_url,
                    headers={
                        "Authorization": f"Bearer {self.settings.resolved_rerank_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.rerank_model,
                        "input": {
                            "query": query,
                            "documents": documents,
                        },
                        "parameters": {
                            "return_documents": False,
                            "top_n": selected_top_n,
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:
            logger.warning("Rerank request failed; using original retrieval order.", exc_info=True)
            selected = items[:selected_top_n]
            log_event(
                logger,
                "rag.rerank",
                enabled=False,
                candidates=len(items),
                top_n=len(selected),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
            return selected

        ranked_items: list[dict[str, Any]] = []
        for result in payload.get("output", {}).get("results", []):
            index = result.get("index")
            if not isinstance(index, int) or index < 0 or index >= len(items):
                continue
            ranked = dict(items[index])
            ranked["rerank_score"] = result.get("relevance_score")
            ranked_items.append(ranked)

        selected = ranked_items or items[:selected_top_n]
        log_event(
            logger,
            "rag.rerank",
            enabled=True,
            candidates=len(items),
            top_n=len(selected),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return selected


@lru_cache
def get_rerank_service() -> RerankService:
    return RerankService()
