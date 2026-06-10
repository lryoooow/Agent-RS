from pydantic import BaseModel, Field, field_validator


class WebSearchArguments(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    max_results: int | None = None
    # 复合问题(如“天气+攻略”)可由 planner 拆成多个独立检索词；留空则回退到单一 query，向后兼容。
    queries: list[str] | None = None

    @field_validator("query", "reason")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank.")
        return stripped

    @field_validator("queries")
    @classmethod
    def normalize_queries(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return cleaned or None

    def effective_queries(self, *, max_queries: int = 3) -> list[str]:
        """返回去重后的实际检索词列表：优先用 queries，否则回退 [query]。

        - queries 与 query 一起去重(忽略大小写/首尾空白),保持出现顺序。
        - 上限 max_queries,避免复合问题被拆得过多放大调用成本。
        """
        candidates = list(self.queries or [])
        candidates.append(self.query)
        seen: set[str] = set()
        ordered: list[str] = []
        for item in candidates:
            text = item.strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(text)
            if len(ordered) >= max_queries:
                break
        return ordered or [self.query]

    def clamped(self, max_results_limit: int) -> "WebSearchArguments":
        max_results = self.max_results or max_results_limit
        max_results = max(1, min(max_results, max_results_limit))
        return self.model_copy(update={"max_results": max_results})


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search public web pages when the answer needs fresh, external, or verifiable "
            "information. Use only when the existing conversation context is insufficient."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Focused search query for the current user question.",
                },
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 3,
                    "description": (
                        "Optional. For compound questions with multiple independent intents "
                        "(e.g. live weather AND a travel plan), provide one focused query per "
                        "intent so each topic is retrieved separately. Omit for simple questions."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Why web search is needed for this answer.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Requested result count. The backend enforces the final cap.",
                },
            },
            "required": ["query", "reason"],
            "additionalProperties": False,
        },
    },
}
