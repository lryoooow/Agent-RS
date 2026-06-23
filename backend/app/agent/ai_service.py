import json
import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.agent.runtime import AgentRuntime, AgentPlanResult
from app.agent.types import AgentEvent
from app.agent.config import resolve_ai_config
from app.agent.errors import AIError, map_provider_error
from app.agent.normalizer import normalize_chat_response
from app.agent.persistence import (
    mark_assistant_failed,
    persistence_meta,
    prepare_persistence,
    request_for_context,
    save_assistant_response,
    save_streamed_assistant,
    schedule_after_response,
)
from app.agent.provider import create_chat_client
from app.agent.prompting.scenarios import latest_user_text
from app.agent.request_builder import build_provider_request_context
from app.agent.routing import build_agent_route
from app.agent.stream import (
    agent_status_event,
    analysis_status_event,
    iter_answer_delta_parts,
    sse_event,
    stream_sse_events,
)
from app.schemas.chat import ChatRequest, ChatResponse
from app.core.logging import log_event
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ChatExecutionSetup:
    config: Any
    persistence: Any
    context_request: ChatRequest
    route: Any
    provider_context: Any
    client: Any


class AIService:
    async def chat(self, request: ChatRequest) -> ChatResponse:
        setup = await self._prepare_chat_execution(request)
        config = setup.config
        persistence = setup.persistence
        context_request = setup.context_request
        route = setup.route
        provider_context = setup.provider_context
        client = setup.client

        try:
            if route.mode == "direct_chat":
                response = await client.chat.completions.create(
                    model=config.model,
                    messages=provider_context.messages,
                    stream=False,
                    extra_body={"enable_thinking": True, "thinking_budget": get_settings().ai_thinking_budget},
                )
                final_context = provider_context
                agent_trace = None
                geospatial_result = None
                tool_result = None
            else:
                runtime = AgentRuntime()
                agent_result = await runtime.complete(
                    client=client,
                    config=config,
                    request=context_request,
                    initial_context=provider_context,
                    user_id=persistence.user_id,
                    route=route,
                )
                response = agent_result.response
                final_context = agent_result.final_context
                agent_trace = self._agent_trace_payload(agent_result.trace)
                geospatial_result = agent_result.geospatial_result
                tool_result = agent_result.tool_result
        except Exception as exc:
            await mark_assistant_failed(persistence, exc)
            raise map_provider_error(exc) from exc

        result = normalize_chat_response(response, config)
        result.conversation_id = persistence.conversation_id
        result.user_message_id = persistence.user_message_id
        result.retrieved_chunks = final_context.retrieved_chunks
        result.rag_trace = final_context.rag_trace
        result.agent_trace = agent_trace
        result.geospatial_result = geospatial_result
        result.tool_result = tool_result
        persistence.assistant_message_id = await save_assistant_response(
            persistence,
            content=result.content,
            usage=result.usage.model_dump(exclude_none=True) if result.usage else {},
            finish_reason=result.finish_reason,
            geospatial_result=geospatial_result,
            tool_result=tool_result,
        )
        result.assistant_message_id = persistence.assistant_message_id
        schedule_after_response(persistence, assistant_content=result.content)
        log_event(
            logger,
            "chat.response",
            model=config.model,
            route=route.mode,
            retrieved_chunks=final_context.retrieved_chunks,
            finish_reason=result.finish_reason,
            stream=False,
        )
        return result

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        try:
            setup = await self._prepare_chat_execution(
                request,
                create_streaming_assistant=True,
            )
            config = setup.config
            persistence = setup.persistence
            context_request = setup.context_request
            route = setup.route
            provider_context = setup.provider_context
            client = setup.client
            runtime = AgentRuntime() if route.mode == "full_pipeline" else None
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

            if route.mode == "direct_chat":
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
                    route=route.mode,
                    retrieved_chunks=provider_context.retrieved_chunks,
                    finish_reason=(done_payload or {}).get("finish_reason"),
                    stream=True,
                )
                return

            event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
            plan_task: asyncio.Task | None = None
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
                        route=route,
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
                        label=agent_event.label,
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
            finally:
                # 客户端中途断连时生成器被 GeneratorExit/CancelledError 中断，
                # 取消仍在执行的 plan_task，避免孤儿 planner→docker 任务跑到超时（H5）。
                # 正常完成时 plan_task 已 done，cancel() 是 no-op。
                if plan_task is not None and not plan_task.done():
                    plan_task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await plan_task

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
                if agent_result.tool_result:
                    payload["tool_result"] = agent_result.tool_result
                yield sse_event("done", payload)
                await save_streamed_assistant(
                    persistence,
                    content=direct_result.content,
                    done_payload=done_payload,
                    geospatial_result=agent_result.geospatial_result,
                    tool_result=agent_result.tool_result,
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
                    if agent_result.tool_result:
                        payload["tool_result"] = agent_result.tool_result
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
                geospatial_result=agent_result.geospatial_result,
                tool_result=agent_result.tool_result,
            )
            finalized = True
            schedule_after_response(persistence, assistant_content=assistant_content)
            log_event(
                logger,
                "chat.response",
                model=config.model,
                route=route.mode,
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

    async def _prepare_chat_execution(
        self,
        request: ChatRequest,
        *,
        create_streaming_assistant: bool = False,
    ) -> ChatExecutionSetup:
        config = resolve_ai_config(
            request_model=request.model,
            provider_config=request.provider_config,
        )
        persistence = await prepare_persistence(
            request,
            model_name=config.model,
            create_streaming_assistant=create_streaming_assistant,
        )
        context_request = request_for_context(request, persistence)
        route = build_agent_route(latest_user_text(context_request.messages), context_request)
        provider_context = await build_provider_request_context(
            context_request,
            user_id=persistence.user_id,
            skip_retrieval=route.skip_retrieval,
        )
        client = create_chat_client(config)
        return ChatExecutionSetup(
            config=config,
            persistence=persistence,
            context_request=context_request,
            route=route,
            provider_context=provider_context,
            client=client,
        )
