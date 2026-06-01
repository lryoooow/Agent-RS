import type { AnalysisStatus, ChatMessage, ChatTurn } from "../types";

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

export function updateAnalysisStatus(
  turns: ChatTurn[],
  id: string,
  status: AnalysisStatus,
  label?: string,
) {
  return turns.map((turn) =>
    turn.id === id
      ? {
          ...turn,
          analysisStatus: status,
          analysisLabel: label,
        }
      : turn,
  );
}

export function updateTurn(turns: ChatTurn[], id: string, patch: Partial<ChatTurn>) {
  return turns.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn));
}
