import type { Dispatch, SetStateAction } from "react";
import type { StreamHandlers } from "./sse";
import {
  appendToTurn,
  updateAnalysisStatus,
  uid,
  updateTurn,
} from "./turns";
import type { AgentStatus, AnalysisStatus, ChatResponse, ChatTurn, Usage } from "../types";

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
      setTurns((prev) =>
        updateTurn(prev, assistantId, {
          analysisStatus: "complete",
          analysisLabel: "思考完成",
          usage: data.usage as Usage | undefined,
          finishReason: typeof data.finish_reason === "string" ? data.finish_reason : undefined,
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
        }),
      );
    },
  };
}

export function appendAssistantResponse(setTurns: SetTurns, data: ChatResponse) {
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
    value === "planning" ||
    value === "tool_requested" ||
    value === "child_agent_running" ||
    value === "tool_context_ready" ||
    value === "final_answering" ||
    value === "direct_answer" ||
    value === "tool_unavailable"
  ) {
    return value;
  }
  return null;
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
