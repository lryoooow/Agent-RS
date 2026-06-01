from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedContext:
    content: str
    source: str | None = None


async def retrieve_context(_: str) -> list[RetrievedContext]:
    return []
