from dataclasses import dataclass, field
from typing import Literal

ContextRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ContextBlock:
    name: str
    role: ContextRole
    content: str
    priority: int
    budget_chars: int | None = None
    required: bool = False
    source: str | None = None


@dataclass(frozen=True)
class ContextAssembly:
    messages: list[dict[str, str]]
    included_blocks: list[str] = field(default_factory=list)
    dropped_blocks: list[str] = field(default_factory=list)
    used_chars: int = 0

