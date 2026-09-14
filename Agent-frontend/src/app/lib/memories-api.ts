import { apiFetch } from "./http";

export type MemoryItem = {
  id: string;
  content: string;
  memory_type: string;
  importance: number;
  metadata?: Record<string, unknown> | null;
  created_at: string;
};

export async function listMemories(): Promise<MemoryItem[]> {
  const response = await apiFetch("/memories", {});
  const payload = (await response.json().catch(() => null)) as { memories?: MemoryItem[] } | null;
  return payload?.memories ?? [];
}

export async function deleteMemory(memoryId: string): Promise<void> {
  await apiFetch(`/memories/${memoryId}`, { method: "DELETE" });
}
