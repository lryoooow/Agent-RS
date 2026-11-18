import asyncio
from contextlib import aclosing

from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import ModelClientStreamingChunkEvent
from autogen_core.models import AssistantMessage, SystemMessage, UserMessage
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage as LCSystemMessage

from app.core.settings import get_settings
from .event_adapter import translate
from .sop_flows import build_graph


class LangGraphTeam:
    def __init__(self, turn, route, client, memory):
        self.turn, self.route, self.client, self.memory = turn, route, client, memory

    async def run_stream(self, *, task, cancellation_token, output_task_messages=False):
        ctx = self.turn.context()
        await ctx.add_message(UserMessage(content=self.turn.query, source="user"))
        for memory in self.memory:
            await memory.update_context(ctx)
        messages = []
        for msg in await ctx.get_messages():
            if isinstance(msg, SystemMessage):
                messages.append(LCSystemMessage(content=msg.content))
            elif isinstance(msg, UserMessage):
                messages.append(HumanMessage(content=msg.content))
            elif isinstance(msg, AssistantMessage) and isinstance(msg.content, str):
                messages.append(AIMessage(content=msg.content))
        graph = build_graph(self.client.model, self.route, cancellation_token)
        config = {"recursion_limit": 2 * get_settings().agent_max_tool_iterations + 4}
        trace = []
        stream = graph.astream({"messages": messages}, config, stream_mode=["messages", "updates"], subgraphs=True)
        async with aclosing(stream):
            async for namespace, kind, payload in stream:
                if cancellation_token.is_cancelled():
                    raise asyncio.CancelledError()
                for event in translate(namespace, kind, payload, self.client):
                    if not isinstance(event, ModelClientStreamingChunkEvent):
                        trace.append(event)
                    yield event
        yield TaskResult(messages=trace, stop_reason="langgraph_completed")

    async def run(self, **kwargs):
        async with aclosing(self.run_stream(**kwargs)) as stream:
            async for event in stream:
                if isinstance(event, TaskResult):
                    return event
        raise RuntimeError("LangGraph returned no task result")
