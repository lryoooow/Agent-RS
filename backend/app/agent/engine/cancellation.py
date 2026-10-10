"""Cancellation at the Agent boundary, including AutoGen's tool event wait."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import Response
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage
from autogen_core import CancellationToken


class CancellableAssistantAgent(AssistantAgent):
    async def on_messages_stream(
        self, messages: Sequence[BaseChatMessage], cancellation_token: CancellationToken,
    ) -> AsyncGenerator[BaseAgentEvent | BaseChatMessage | Response, None]:
        source = super().on_messages_stream(messages, cancellation_token)
        active_read: asyncio.Task | None = None
        loop = asyncio.get_running_loop()

        def cancel_read() -> None:
            # Tools run in detached tasks. Their cancellation does not send EOF
            # to AutoGen's event queue, so cancel its current consumer as well.
            if active_read is not None and not active_read.done():
                loop.call_soon_threadsafe(active_read.cancel)

        cancellation_token.add_callback(cancel_read)
        try:
            while True:
                if cancellation_token.is_cancelled():
                    raise asyncio.CancelledError()
                active_read = asyncio.current_task()
                try:
                    item = await anext(source)
                except StopAsyncIteration:
                    return
                finally:
                    active_read = None
                yield item
        finally:
            await source.aclose()
