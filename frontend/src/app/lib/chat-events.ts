import type { Dispatch, SetStateAction } from "react";
import type { StreamHandlers } from "./sse";
import {
  appendToTurn,
  updateAnalysisStatus,
  uid,
  updateTurn,
} from "./turns";
import type {
  AgentStatus,
  AnalysisStatus,
  ChatResponse,
  ChatTurn,
  GeospatialResult,
  ToolExecutionInfo,
  Usage,
} from "../types";

type SetTurns = Dispatch<SetStateAction<ChatTurn[]>>;

export function createStreamHandlers(
  setTurns: SetTurns,
  assistantId: string,
  onConversationId?: (conversationId: string) => void,
): StreamHandlers {
  return {
    onMeta: (data) => {
      if (typeof data.conversation_id === "string") {
        onConversationId?.(data.conversation_id);
      }
      setTurns((prev) =>
        updateTurn(prev, assistantId, {
          model: typeof data.model === "string" ? data.model : undefined,
          provider: typeof data.provider === "string" ? data.provider : undefined,
        }),
      );
    },
    onDelta: (content) => {
      setTurns((prev) => appendToTurn(prev, assistantId, content));
    },
    onAnalysisStatus: (data) => {
      const status = normalizeAnalysisStatus(data.status);
      if (!status) return;
      const label = typeof data.label === "string" ? data.label : undefined;
      setTurns((prev) => updateAnalysisStatus(prev, assistantId, status, label));
    },
    onAgentStatus: (data) => {
      const status = normalizeAgentStatus(data.status);
      if (!status) return;
      const label = typeof data.label === "string" ? data.label : undefined;
      setTurns((prev) =>
        updateTurn(prev, assistantId, {
          agentStatus: status,
          agentLabel: label,
          analysisStatus: status === "final_answering" ? "answering" : "preparing",
          analysisLabel: label,
        }),
      );
    },
    onDone: (data) => {
      const geospatialResult = parseGeospatialResult(data.geospatial_result);
      const finishReason = typeof data.finish_reason === "string" ? data.finish_reason : undefined;
      const failed = finishReason === "error";
      setTurns((prev) =>
        updateTurn(prev, assistantId, {
          analysisStatus: failed ? "answering" : "complete",
          analysisLabel: failed ? "回答生成失败" : "思考完成",
          error: failed,
          usage: data.usage as Usage | undefined,
          finishReason,
          retrievedChunks:
            typeof data.retrieved_chunks === "number" ? data.retrieved_chunks : undefined,
          ragTrace:
            data.rag_trace && typeof data.rag_trace === "object"
              ? (data.rag_trace as Record<string, unknown>)
              : undefined,
          agentTrace:
            data.agent_trace && typeof data.agent_trace === "object"
              ? (data.agent_trace as Record<string, unknown>)
              : undefined,
          geospatialResult,
        }),
      );
    },
  };
}

export function appendAssistantResponse(setTurns: SetTurns, data: ChatResponse) {
  const geospatialResult = parseGeospatialResult(data.geospatial_result);
  setTurns((prev) => [
    ...prev,
    {
      id: uid(),
      role: "assistant",
      content: data.content ?? "",
      model: data.model,
      provider: data.provider,
      usage: data.usage,
      finishReason: data.finish_reason,
      retrievedChunks: data.retrieved_chunks,
      ragTrace: data.rag_trace,
      agentTrace: data.agent_trace,
      geospatialResult,
    },
  ]);
}

function normalizeAnalysisStatus(value: unknown): AnalysisStatus | null {
  if (value === "analyzing" || value === "preparing" || value === "answering" || value === "complete") {
    return value;
  }
  return null;
}

function normalizeAgentStatus(value: unknown): AgentStatus | null {
  if (
    value === "context_assembled" ||
    value === "planning" ||
    value === "planning_fallback" ||
    value === "classifier_skip" ||
    value === "classifier_force" ||
    value === "cache_hit_skip" ||
    value === "cache_hit_search" ||
    value === "tool_requested" ||
    value === "child_agent_running" ||
    value === "tool_execution_started" ||
    value === "tool_execution_completed" ||
    value === "tool_execution_failed" ||
    value === "tool_fallback_used" ||
    value === "tool_context_ready" ||
    value === "geospatial_result_ready" ||
    value === "final_answering" ||
    value === "direct_answer" ||
    value === "tool_unavailable"
  ) {
    return value;
  }
  return null;
}

function parseGeospatialResult(value: unknown): GeospatialResult | undefined {
  if (!value || typeof value !== "object") return undefined;
  const candidate = value as Record<string, unknown>;
  if (candidate.type !== "preview" && candidate.type !== "ndvi") return undefined;
  if (typeof candidate.imagery_id !== "string") return undefined;
  if (typeof candidate.result_url !== "string") return undefined;
  const bounds = candidate.bounds;
  if (bounds !== null && !isBounds(bounds)) return undefined;

  const base = {
    imagery_id: candidate.imagery_id,
    result_url: candidate.result_url,
    bounds,
  };
  if (candidate.type === "preview") {
    return { type: "preview", ...base };
  }
  if (!isStats(candidate.stats)) return undefined;
  return {
    type: "ndvi",
    ...base,
    stats: candidate.stats,
    execution: isExecution(candidate.execution) ? candidate.execution : undefined,
  };
}

function isBounds(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value) && value.length === 4 && value.every((item) => typeof item === "number");
}

function isStats(value: unknown): value is { min: number; max: number; mean: number; std: number } {
  if (!value || typeof value !== "object") return false;
  const stats = value as Record<string, unknown>;
  return ["min", "max", "mean", "std"].every((key) => typeof stats[key] === "number");
}

function isExecution(value: unknown): value is ToolExecutionInfo {
  if (!value || typeof value !== "object") return false;
  const execution = value as Record<string, unknown>;
  return (
    typeof execution.mode === "string" &&
    typeof execution.fallback_used === "boolean" &&
    (execution.error_code === undefined ||
      execution.error_code === null ||
      typeof execution.error_code === "string")
  );
}

export function applyRequestError(setTurns: SetTurns, assistantId: string, shouldStream: boolean, err: unknown) {
  const message = err instanceof Error ? err.message : String(err);
  if (shouldStream) {
    setTurns((prev) =>
      prev.map((turn) =>
        turn.id === assistantId
          ? {
              ...turn,
              content: turn.content ? `${turn.content}\n\n${message}` : message,
              error: true,
            }
          : turn,
      ),
    );
    return;
  }

  setTurns((prev) => [
    ...prev,
    {
      id: uid(),
      role: "assistant",
      content: message,
      error: true,
    },
  ]);
}
