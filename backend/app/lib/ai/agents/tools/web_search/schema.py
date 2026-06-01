from pydantic import BaseModel, Field, field_validator


class WebSearchArguments(BaseModel):
    query: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    max_results: int | None = None

    @field_validator("query", "reason")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank.")
        return stripped

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
