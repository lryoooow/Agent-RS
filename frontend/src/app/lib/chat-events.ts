import type { Dispatch, SetStateAction } from "react";
import type { StreamHandlers } from "./sse";
import {
  appendReasoningToTurn,
  appendToTurn,
  uid,
  updateTurn,
} from "./turns";
import type { ChatResponse, ChatTurn, Usage } from "../types";

type SetTurns = Dispatch<SetStateAction<ChatTurn[]>>;

export function createStreamHandlers(setTurns: SetTurns, assistantId: string): StreamHandlers {
  return {
    onMeta: (data) => {
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
    onReasoningDelta: (content) => {
      setTurns((prev) => appendReasoningToTurn(prev, assistantId, content));
    },
    onDone: (data) => {
      setTurns((prev) =>
        updateTurn(prev, assistantId, {
          usage: data.usage as Usage | undefined,
          finishReason: typeof data.finish_reason === "string" ? data.finish_reason : undefined,
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
      reasoning: data.reasoning,
      reasoningParts: data.reasoning ? [data.reasoning] : undefined,
      model: data.model,
      provider: data.provider,
      usage: data.usage,
      finishReason: data.finish_reason,
    },
  ]);
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
