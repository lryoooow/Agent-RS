from pydantic import BaseModel, Field, field_validator


class WebSearchArguments(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(
        min_length=1,
        description="聚焦的检索词；不要把整句用户提问原样丢进去",
    )
    reason: str = Field(min_length=1, description="为什么这轮回答需要联网检索")
    max_results: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="期望结果条数；服务端强制最终上限，模型说了不算",
    )
    # 复合问题（如“天气+攻略”）可拆成多个独立检索词；留空则回退到单一 query。
    # 数量上限由 effective_queries() 在运行时裁（max_queries=3），不在 schema 层硬卡，
    # 保证直接以 Python 调用的旧用法仍由方法层统一收敛。
    queries: list[str] | None = Field(
        default=None,
        description="复合问题按意图各写一条聚焦检索词（最多 3 条生效）；简单问题留空",
    )

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
        cleaned = [item.strip() for item in value or [] if isinstance(item, str) and item.strip()]
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
