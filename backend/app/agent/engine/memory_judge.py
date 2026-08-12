"""AutoGen structured-output runner for durable-memory decisions."""

from __future__ import annotations

import logging

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import StructuredMessage
from pydantic import BaseModel, Field

from app.agent.config import ResolvedAIConfig
from app.agent.engine.model_client import build_model_client
from app.agent.memory_types import DEFAULT_IMPORTANCE, DEFAULT_MEMORY_TYPE

logger = logging.getLogger(__name__)


class MemoryDecision(BaseModel):
    remember: bool
    content: str = ""
    memory_type: str = DEFAULT_MEMORY_TYPE
    importance: float = DEFAULT_IMPORTANCE
    tags: list[str] = Field(default_factory=list)


async def decide_memory(
    *,
    config: ResolvedAIConfig,
    model_override: str | None,
    system_message: str,
    task: str,
) -> MemoryDecision | None:
    """Run one structured AutoGen Agent call and always close its client."""
    client = build_model_client(
        config,
        model_override=model_override,
        enable_thinking=False,
    )
    try:
        agent = AssistantAgent(
            name="memory_judge",
            description="提取值得长期保存的用户记忆。",
            model_client=client,
            system_message=system_message,
            output_content_type=MemoryDecision,
        )
        result = await agent.run(task=task, output_task_messages=False)
        return next(
            (
                message.content
                for message in reversed(result.messages)
                if isinstance(message, StructuredMessage)
                and isinstance(message.content, MemoryDecision)
            ),
            None,
        )
    finally:
        try:
            await client.close()
        except Exception:
            logger.debug("Failed to close memory judge model client", exc_info=True)
