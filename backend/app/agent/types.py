from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal

from app.schemas.chat import GeospatialResult, ToolResult


AgentStage = Literal[
    "context_assembled",
    "routing_selected",
    "agent_selected",
    "tool_requested",
    "child_agent_running",
    "tool_execution_started",
    "tool_execution_completed",
    "tool_execution_failed",
    "tool_context_ready",
    "geospatial_result_ready",
    "final_answering",
]


@dataclass
class AgentEvent:
    stage: AgentStage
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0


class AgentTrace:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._started = perf_counter()
        self.events: list[AgentEvent] = []

    def add(self, stage: AgentStage, label: str, **metadata: Any) -> AgentEvent:
        event = AgentEvent(
            stage=stage,
            label=label,
            metadata={key: value for key, value in metadata.items() if value is not None},
            elapsed_ms=int((perf_counter() - self._started) * 1000),
        )
        self.events.append(event)
        return event

    def model_dump(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "events": [
                {
                    "stage": event.stage,
                    "label": event.label,
                    "metadata": event.metadata,
                    "elapsed_ms": event.elapsed_ms,
                }
                for event in self.events
            ],
        }


@dataclass(frozen=True)
class AgentArtifact:
    type: str
    payload: dict[str, Any]
    visibility: Literal["response_metadata", "tool_context"] = "response_metadata"


@dataclass(frozen=True)
class ToolRunResult:
    tool_context: str
    result_count: int = 0
    query: str = ""
    error: str | None = None
    geospatial_result: GeospatialResult | None = None
    tool_result: ToolResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: list[AgentArtifact] = field(default_factory=list)
