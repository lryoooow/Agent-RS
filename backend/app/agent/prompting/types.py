from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptModule:
    name: str
    template: str
    required: bool = False
    budget_chars: int | None = None


@dataclass(frozen=True)
class PromptRenderResult:
    content: str
    included_blocks: list[str] = field(default_factory=list)
    dropped_blocks: list[str] = field(default_factory=list)
    used_chars: int = 0
    profile: str = ""

