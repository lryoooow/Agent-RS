"""Adapt LangGraph's events to the existing chat stream and durable trace."""
import json
from uuid import uuid4

from autogen_agentchat.messages import ModelClientStreamingChunkEvent, TextMessage, ToolCallExecutionEvent, ToolCallRequestEvent
from autogen_core.models import FunctionExecutionResult
from autogen_core import FunctionCall
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage


def message_text(message):
    if isinstance(message.content, str):
        return message.content
    return "".join(b.get("text", "") for b in message.content if isinstance(b, dict) and b.get("type") == "text")


def translate(namespace, kind, payload, model_client):
    if not namespace:
        return []
    agent = namespace[0].split(":", 1)[0]
    events = []
    if kind == "messages":
        msg, _ = payload
        if isinstance(msg, AIMessageChunk) and message_text(msg):
            events.append(ModelClientStreamingChunkEvent(source=agent, content=message_text(msg), full_message_id=msg.id))
    elif kind == "updates":
        for node in ("model", "tools"):
            for msg in (payload.get(node) or {}).get("messages", ()):
                if isinstance(msg, AIMessage):
                    model_client.collect_usage(msg.usage_metadata)
                    if msg.tool_calls:
                        calls = [FunctionCall(id=c["id"], name=c["name"], arguments=json.dumps(c["args"], ensure_ascii=False))
                                 for c in msg.tool_calls]
                        events.append(ToolCallRequestEvent(source=agent, content=calls))
                    if message_text(msg):
                        events.append(TextMessage(source=agent, content=message_text(msg)))
                elif isinstance(msg, ToolMessage):
                    item = FunctionExecutionResult(content=message_text(msg), name=msg.name or "",
                                                   call_id=msg.tool_call_id, is_error=msg.status == "error")
                    events.append(ToolCallExecutionEvent(source=agent, content=[item]))
    return events
