import type { AnalysisStatus, ChatMessage, ChatTurn, ThinkingSummaryStage } from "../types";

export function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export const CHAT_MESSAGE_MAX_CHARS = 16000;
export const CHAT_MAX_MESSAGES = 64;
export function exceedsMessageLimit(value: string) {
  let count = 0;
  for (const ignored of value) { if (++count > CHAT_MESSAGE_MAX_CHARS) return true; }
  return false;
}
export function toModelHistory(turns: ChatTurn[], nextUserMessage: string): ChatMessage[] {
  return [
    ...turns
      .filter((turn) => !turn.error && !turn.historyExcluded && turn.role !== "system" && turn.content.trim() && !exceedsMessageLimit(turn.content))
      .slice(-(CHAT_MAX_MESSAGES - 1))
      .map((turn) => ({ role: turn.role, content: turn.content })),
    { role: "user", content: nextUserMessage },
  ];
}

export function appendToTurn(turns: ChatTurn[], id: string, content: string) {
  return turns.map((turn) => (turn.id === id ? { ...turn, content: turn.content + content } : turn));
}

export function appendThinkingSummary(
  turns: ChatTurn[],
  id: string,
  stage: ThinkingSummaryStage,
) {
  return turns.map((turn) =>
    turn.id === id
      ? {
          ...turn,
          thinkingSummary: turn.thinkingSummary?.some((item) => item.stage === stage)
            ? turn.thinkingSummary
            : [
                ...(turn.thinkingSummary ?? []).map((item) => ({
                  ...item,
                  status: "complete" as const,
                })),
                { stage, status: "active" as const },
              ],
        }
      : turn,
  );
}

export function completeThinkingSummary(turns: ChatTurn[], id: string) {
  return turns.map((turn) =>
    turn.id === id && turn.thinkingSummary
      ? {
          ...turn,
          thinkingSummary: turn.thinkingSummary.map((item) => ({
            ...item,
            status: "complete" as const,
          })),
        }
      : turn,
  );
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
