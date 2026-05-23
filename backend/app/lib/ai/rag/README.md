RAG is intentionally not connected to the current `/api/chat` path.

Keep future retrieval and context-building code in this package so it can be
added behind `AIService` without changing API routes or provider code.
