import json
import asyncio
import logging
from typing import AsyncIterator

from app.lib.ai.agents.runtime import AgentRuntime, AgentPlanResult
from app.lib.ai.agents.types import AgentEvent
from app.lib.ai.config import resolve_ai_config
from app.lib.ai.errors import AIError, map_provider_error
from app.lib.ai.normalizer import normalize_chat_response
from app.lib.ai.persistence import (
    mark_assistant_failed,
    persistence_meta,
    prepare_persistence,
    request_for_context,
    save_assistant_response,
    save_streamed_assistant,
    schedule_after_response,
)
from app.lib.ai.provider import create_chat_client
from app.lib.ai.request_builder import build_provider_request_context
from app.lib.ai.router import RequestRoute, classify_request_route
from app.lib.ai.stream import (
    agent_status_event,
    analysis_status_event,
    iter_answer_delta_parts,
    sse_event,
    stream_sse_events,
)
from app.schemas.chat import ChatRequest, ChatResponse
from app.shared.logging import log_event
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)


class AIService:
    async def chat(self, request: ChatRequest) -> ChatResponse:
        config = resolve_ai_config(
            request_model=request.model,
            provider_config=request.provider_config,
        )
        persistence = await prepare_persistence(request, model_name=config.model)
        context_request = request_for_context(request, persistence)
        route = classify_request_route(self._latest_user_text(context_request), context_request)
        provider_context = await build_provider_request_context(
            context_request,
            user_id=persistence.user_id,
            skip_retrieval=route == RequestRoute.DIRECT_CHAT,
        )
        client = create_chat_client(config)

        try:
            if route == RequestRoute.DIRECT_CHAT:
                response = await client.chat.completions.create(
                    model=config.model,
                    messages=provider_context.messages,
                    stream=False,
                    extra_body={"enable_thinking": True, "thinking_budget": get_settings().ai_thinking_budget},
                )
                final_context = provider_context
                agent_trace = None
            else:
                runtime = AgentRuntime()
                agent_result = await runtime.complete(
                    client=client,
                    config=config,
                    request=context_request,
                    initial_context=provider_context,
                    user_id=persistence.user_id,
                )
                response = agent_result.response
                final_context = agent_result.final_context
                agent_trace = self._agent_trace_payload(agent_result.trace)
        except Exception as exc:
            await mark_assistant_failed(persistence, exc)
            raise map_provider_error(exc) from exc

        result = normalize_chat_response(response, config)
        result.conversation_id = persistence.conversation_id
        result.user_message_id = persistence.user_message_id
        result.retrieved_chunks = final_context.retrieved_chunks
        result.rag_trace = final_context.rag_trace
        result.agent_trace = agent_trace
        persistence.assistant_message_id = await save_assistant_response(
            persistence,
            content=result.content,
            usage=result.usage.model_dump(exclude_none=True) if result.usage else {},
            finish_reason=result.finish_reason,
        )
        result.assistant_message_id = persistence.assistant_message_id
        schedule_after_response(persistence, assistant_content=result.content)
        log_event(
            logger,
            "chat.response",
            model=config.model,
            route=route.value,
            retrieved_chunks=final_context.retrieved_chunks,
            finish_reason=result.finish_reason,
            stream=False,
        )
        return result

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        try:
            config = resolve_ai_config(
                request_model=request.model,
                provider_config=request.provider_config,
            )
            persistence = await prepare_persistence(
                request,
                model_name=config.model,
                create_streaming_assistant=True,
            )
            context_request = request_for_context(request, persistence)
            route = classify_request_route(self._latest_user_text(context_request), context_request)
            provider_context = await build_provider_request_context(
                context_request,
                user_id=persistence.user_id,
                skip_retrieval=route == RequestRoute.DIRECT_CHAT,
            )
            client = create_chat_client(config)
            runtime = AgentRuntime() if route == RequestRoute.FULL_PIPELINE else None
        except Exception as exc:
            error = exc if isinstance(exc, AIError) else map_provider_error(exc)
            yield sse_event("error", {"code": error.code, "message": error.message})
            return

        finalized = False
        assistant_parts: list[str] = []
        done_payload: dict | None = None
        agent_result = AgentPlanResult(
            response=None,
            final_context=provider_context,
            trace=runtime.trace() if runtime else AgentRuntime().trace(),
        )
        try:
            yield sse_event(
                "meta",
                {
                    "model": config.model,
                    "provider": config.provider,
                    **persistence_meta(persistence),
                },
            )
            yield analysis_status_event("analyzing")

            if route == RequestRoute.DIRECT_CHAT:
                yield analysis_status_event("preparing")
                yield analysis_status_event("answering")
                try:
                    stream = await client.chat.completions.create(
                        model=config.model,
                        messages=provider_context.messages,
                        stream=True,
                        extra_body={"enable_thinking": True, "thinking_budget": get_settings().ai_thinking_budget},
                    )
                except Exception as exc:
                    error = exc if isinstance(exc, AIError) else map_provider_error(exc)
                    await mark_assistant_failed(persistence, exc)
                    finalized = True
                    yield sse_event("error", {"code": error.code, "message": error.message})
                    return

                async for event in stream_sse_events(stream):
                    parsed = self._parse_sse_event(event)
                    if parsed["event"] == "delta":
                        content = parsed["data"].get("content")
                        if isinstance(content, str):
                            assistant_parts.append(content)
                    if parsed["event"] == "done":
                        done_payload = parsed["data"]
                        event = sse_event(
                            "done",
                            {
                                **done_payload,
                                "retrieved_chunks": provider_context.retrieved_chunks,
                                "rag_trace": provider_context.rag_trace,
                            },
                        )
                    yield event

                assistant_content = "".join(assistant_parts)
                if done_payload and done_payload.get("finish_reason") == "error":
                    await mark_assistant_failed(persistence, RuntimeError("Stream ended with provider error."))
                    finalized = True
                    return
                await save_streamed_assistant(
                    persistence,
                    content=assistant_content,
                    done_payload=done_payload or {},
                )
                finalized = True
                schedule_after_response(persistence, assistant_content=assistant_content)
                log_event(
                    logger,
                    "chat.response",
                    model=config.model,
                    route=route.value,
                    retrieved_chunks=provider_context.retrieved_chunks,
                    finish_reason=(done_payload or {}).get("finish_reason"),
                    stream=True,
                )
                return

            event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
            try:
                plan_task = asyncio.create_task(
                    runtime.plan_stream(
                        client=client,
                        config=config,
                        request=context_request,
                        initial_context=provider_context,
                        user_id=persistence.user_id,
                        trace=agent_result.trace,
                        on_event=event_queue.put,
                    )
                )
                while True:
                    if plan_task.done() and event_queue.empty():
                        break
                    try:
                        agent_event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    yield agent_status_event(
                        agent_event.stage,
                        **agent_event.metadata,
                        elapsed_ms=agent_event.elapsed_ms,
                    )
                agent_result = await plan_task
            except Exception as exc:
                error = exc if isinstance(exc, AIError) else map_provider_error(exc)
                await mark_assistant_failed(persistence, exc)
                finalized = True
                yield sse_event("error", {"code": error.code, "message": error.message})
                return

            yield analysis_status_event("preparing")
            yield analysis_status_event("answering")

            if agent_result.response is not None:
                direct_result = normalize_chat_response(agent_result.response, config)
                yield analysis_status_event("complete")
                for part in iter_answer_delta_parts([direct_result.content]):
                    assistant_parts.append(part)
                    yield sse_event("delta", {"content": part})
                done_payload = {"finish_reason": direct_result.finish_reason}
                if direct_result.usage:
                    done_payload["usage"] = direct_result.usage.model_dump(exclude_none=True)
                payload = {
                    **done_payload,
                    "retrieved_chunks": agent_result.final_context.retrieved_chunks,
                    "rag_trace": agent_result.final_context.rag_trace,
                }
                agent_trace = self._agent_trace_payload(agent_result.trace)
                if agent_trace:
                    payload["agent_trace"] = agent_trace
                if agent_result.geospatial_result:
                    payload["geospatial_result"] = agent_result.geospatial_result
                yield sse_event("done", payload)
                await save_streamed_assistant(
                    persistence,
                    content=direct_result.content,
                    done_payload=done_payload,
                )
                finalized = True
                schedule_after_response(persistence, assistant_content=direct_result.content)
                return
            try:
                stream = await client.chat.completions.create(
                    model=config.model,
                    messages=agent_result.final_context.messages,
                    stream=True,
                    extra_body={"enable_thinking": True, "thinking_budget": get_settings().ai_thinking_budget},
                )
            except Exception as exc:
                error = exc if isinstance(exc, AIError) else map_provider_error(exc)
                await mark_assistant_failed(persistence, exc)
                finalized = True
                yield sse_event("error", {"code": error.code, "message": error.message})
                return

            async for event in stream_sse_events(stream):
                parsed = self._parse_sse_event(event)
                if parsed["event"] == "delta":
                    content = parsed["data"].get("content")
                    if isinstance(content, str):
                        assistant_parts.append(content)
                if parsed["event"] == "done":
                    done_payload = parsed["data"]
                    payload = {
                        **done_payload,
                        "retrieved_chunks": agent_result.final_context.retrieved_chunks,
                        "rag_trace": agent_result.final_context.rag_trace,
                    }
                    agent_trace = self._agent_trace_payload(agent_result.trace)
                    if agent_trace:
                        payload["agent_trace"] = agent_trace
                    if agent_result.geospatial_result:
                        payload["geospatial_result"] = agent_result.geospatial_result
                    event = sse_event("done", payload)
                yield event

            assistant_content = "".join(assistant_parts)
            if done_payload and done_payload.get("finish_reason") == "error":
                await mark_assistant_failed(persistence, RuntimeError("Stream ended with provider error."))
                finalized = True
                return
            await save_streamed_assistant(
                persistence,
                content=assistant_content,
                done_payload=done_payload or {},
            )
            finalized = True
            schedule_after_response(persistence, assistant_content=assistant_content)
            log_event(
                logger,
                "chat.response",
                model=config.model,
                route=route.value,
                retrieved_chunks=agent_result.final_context.retrieved_chunks,
                finish_reason=(done_payload or {}).get("finish_reason"),
                stream=True,
            )
        finally:
            if not finalized:
                await asyncio.shield(
                    mark_assistant_failed(persistence, RuntimeError("Stream interrupted"))
                )

    def _parse_sse_event(self, event: str) -> dict:
        event_name = "message"
        data: dict = {}
        for line in event.splitlines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    data = {}
        return {"event": event_name, "data": data}

    def _agent_trace_payload(self, trace) -> dict | None:
        payload = trace.model_dump()
        if not payload.get("enabled") and not payload.get("events"):
            return None
        return payload

    def _latest_user_text(self, request: ChatRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.content.strip()
        return ""
