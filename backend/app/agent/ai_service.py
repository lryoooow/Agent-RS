"""HTTP-facing chat service backed exclusively by the AutoGen engine."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.agent.config import resolve_ai_config
from app.agent.engine import complete_turn, stream_turn_events
from app.agent.errors import AIError, map_provider_error
from app.agent.persistence import (
    mark_assistant_failed,
    persistence_meta,
    prepare_persistence,
    request_for_context,
    save_assistant_response,
    save_streamed_assistant,
    schedule_after_response,
)
from app.agent.stream import (
    agent_status_event,
    analysis_status_event,
    iter_answer_delta_parts,
    sse_event,
)
from app.agent.thinking_summary import ThinkingSummaryTracker
from app.core.logging import log_event
from app.schemas.chat import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


@dataclass
class ChatExecutionSetup:
    config: Any
    persistence: Any
    context_request: ChatRequest


def _finish_reason_from_stop(stop_reason: str | None) -> str:
    if not stop_reason:
        return "stop"
    text = stop_reason.lower()
    if "maximum" in text or "max message" in text or "limit" in text:
        return "length"
    return "stop"


class AIService:
    async def chat(self, request: ChatRequest) -> ChatResponse:
        setup = await self._prepare_chat_execution(request)
        persistence = setup.persistence
        try:
            turn = await complete_turn(
                request=setup.context_request,
                user_id=persistence.user_id,
                config=setup.config,
            )
        except Exception as exc:
            await mark_assistant_failed(persistence, exc)
            raise map_provider_error(exc) from exc

        finish_reason = _finish_reason_from_stop(turn.stop_reason)
        result = ChatResponse(
            content=turn.content,
            model=setup.config.model,
            provider=setup.config.provider,
            usage=turn.usage,
            finish_reason=finish_reason,
            conversation_id=persistence.conversation_id,
            user_message_id=persistence.user_message_id,
            retrieved_chunks=turn.retrieved_chunks,
            rag_trace=turn.rag_trace,
            agent_trace=self._agent_trace_payload(turn.trace),
            geospatial_result=turn.geospatial_result,
            tool_result=turn.tool_result,
        )
        persistence.assistant_message_id = await save_assistant_response(
            persistence,
            content=result.content,
            usage=turn.usage or {},
            finish_reason=finish_reason,
            geospatial_result=turn.geospatial_result,
            tool_result=turn.tool_result,
        )
        result.assistant_message_id = persistence.assistant_message_id
        schedule_after_response(persistence, assistant_content=result.content)
        self._log_response(setup, turn, finish_reason=finish_reason, stream=False)
        return result

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        try:
            setup = await self._prepare_chat_execution(
                request,
                create_streaming_assistant=True,
            )
        except Exception as exc:
            error = exc if isinstance(exc, AIError) else map_provider_error(exc)
            yield sse_event("error", {"code": error.code, "message": error.message})
            return

        persistence = setup.persistence
        finalized = False
        parts: list[str] = []
        try:
            yield sse_event(
                "meta",
                {
                    "model": setup.config.model,
                    "provider": setup.config.provider,
                    **persistence_meta(persistence),
                },
            )
            yield analysis_status_event("analyzing")

            turn = None
            answering_announced = False
            summary = ThinkingSummaryTracker()
            if summary_data := summary.advance("context"):
                yield sse_event("thinking_summary", summary_data)
            async for kind, payload in stream_turn_events(
                request=setup.context_request,
                user_id=persistence.user_id,
                config=setup.config,
            ):
                if kind == "status":
                    yield agent_status_event(
                        payload.stage,
                        label=payload.label,
                        **payload.metadata,
                        elapsed_ms=payload.elapsed_ms,
                    )
                    if summary_data := summary.advance_for_agent_event(payload.stage):
                        yield sse_event("thinking_summary", summary_data)
                elif kind == "delta":
                    if not answering_announced:
                        yield analysis_status_event("preparing")
                        yield analysis_status_event("answering")
                        if summary_data := summary.advance("answer"):
                            yield sse_event("thinking_summary", summary_data)
                        answering_announced = True
                    parts.append(payload)
                    yield sse_event("delta", {"content": payload})
                elif kind == "map_control":
                    yield sse_event("map_control", payload)
                elif kind == "final":
                    turn = payload

            if turn is None:
                raise RuntimeError("AutoGen 编排没有产出最终结果")

            content = turn.content or "".join(parts)
            if not answering_announced:
                yield analysis_status_event("preparing")
                yield analysis_status_event("answering")
                if summary_data := summary.advance("answer"):
                    yield sse_event("thinking_summary", summary_data)
                for part in iter_answer_delta_parts([content]):
                    parts.append(part)
                    yield sse_event("delta", {"content": part})

            finish_reason = _finish_reason_from_stop(turn.stop_reason)
            done_payload: dict[str, Any] = {
                "finish_reason": finish_reason,
                "retrieved_chunks": turn.retrieved_chunks,
                "rag_trace": turn.rag_trace,
            }
            if turn.usage:
                done_payload["usage"] = turn.usage
            if turn.map_target:
                done_payload["map_target"] = turn.map_target
            if agent_trace := self._agent_trace_payload(turn.trace):
                done_payload["agent_trace"] = agent_trace
            if turn.geospatial_result:
                done_payload["geospatial_result"] = turn.geospatial_result
            if turn.tool_result:
                done_payload["tool_result"] = turn.tool_result
            await save_streamed_assistant(
                persistence,
                content=content,
                done_payload=done_payload,
                geospatial_result=turn.geospatial_result,
                tool_result=turn.tool_result,
            )
            finalized = True
            schedule_after_response(persistence, assistant_content=content)
            self._log_response(setup, turn, finish_reason=finish_reason, stream=True)
            # done 是协议终点：持久化已经成功，客户端收到后无需继续等待 HTTP EOF。
            yield sse_event("done", done_payload)
        except Exception as exc:
            error = exc if isinstance(exc, AIError) else map_provider_error(exc)
            await mark_assistant_failed(persistence, exc, content="".join(parts))
            finalized = True
            yield sse_event("error", {"code": error.code, "message": error.message})
        finally:
            if not finalized:
                await asyncio.shield(
                    mark_assistant_failed(
                        persistence,
                        RuntimeError("Stream interrupted"),
                        content="".join(parts),
                    )
                )

    async def _prepare_chat_execution(
        self,
        request: ChatRequest,
        *,
        create_streaming_assistant: bool = False,
    ) -> ChatExecutionSetup:
        config = resolve_ai_config(
            request_model=request.model,
            provider_config=request.provider_config,
            thinking_strength=request.thinking_strength,
        )
        persistence = await prepare_persistence(
            request,
            model_name=config.model,
            create_streaming_assistant=create_streaming_assistant,
        )
        return ChatExecutionSetup(
            config=config,
            persistence=persistence,
            context_request=request_for_context(request, persistence),
        )

    @staticmethod
    def _agent_trace_payload(trace) -> dict | None:
        payload = trace.model_dump()
        if not payload.get("enabled") and not payload.get("events"):
            return None
        return payload

    @staticmethod
    def _log_response(setup, turn, *, finish_reason: str, stream: bool) -> None:
        log_event(
            logger,
            "chat.response",
            model=setup.config.model,
            route=f"autogen:{turn.strategy}",
            flow_name=turn.flow_name,
            # route_reason 可能是路由模型生成的自由文本，不应进入服务端日志。
            route_reason_class=_route_reason_class(turn.route_reason),
            retrieved_chunks=turn.retrieved_chunks,
            finish_reason=finish_reason,
            total_tokens=(turn.usage or {}).get("total_tokens"),
            stream=stream,
        )


def _route_reason_class(reason: str | None) -> str:
    """把自由文本路由理由压成安全类别，避免用户内容/模型分析进入日志。"""
    if reason == "auto_flow_disabled":
        return "auto_flow_disabled"
    if reason and reason.startswith("router_fallback:"):
        return "router_fallback"
    return "model_decision" if reason else "none"
