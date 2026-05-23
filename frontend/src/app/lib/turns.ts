import type { ChatMessage, ChatTurn } from "../types";

export function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export function toModelHistory(turns: ChatTurn[], nextUserMessage: string): ChatMessage[] {
  return [
    ...turns
      .filter((turn) => !turn.error)
      .map((turn) => ({ role: turn.role, content: turn.content })),
    { role: "user", content: nextUserMessage },
  ];
}

export function appendToTurn(turns: ChatTurn[], id: string, content: string) {
  return turns.map((turn) => (turn.id === id ? { ...turn, content: turn.content + content } : turn));
}

export function appendReasoningToTurn(turns: ChatTurn[], id: string, content: string) {
  return turns.map((turn) =>
    turn.id === id
      ? {
          ...turn,
          reasoning: `${turn.reasoning ?? ""}${content}`,
          reasoningParts: [...(turn.reasoningParts ?? []), content],
        }
      : turn,
  );
}

export function updateTurn(turns: ChatTurn[], id: string, patch: Partial<ChatTurn>) {
  return turns.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn));
}
