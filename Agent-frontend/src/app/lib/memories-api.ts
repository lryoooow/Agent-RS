import { getApiBaseEndpoint } from "../config";
import { readErrorMessage } from "./errors";

export type MemoryItem = {
  id: string;
  content: string;
  memory_type: string;
  importance: number;
  metadata?: Record<string, unknown> | null;
  created_at: string;
};

export async function listMemories(chatEndpoint: string): Promise<MemoryItem[]> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/memories`, {
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { memories?: MemoryItem[] };
  return payload.memories ?? [];
}

export async function deleteMemory(chatEndpoint: string, memoryId: string): Promise<void> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/memories/${memoryId}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
}

async function readApiError(res: Response) {
  const payload = await res.json().catch(() => null);
  return new Error(readErrorMessage(payload) ?? `${res.status} ${res.statusText}`);
}
