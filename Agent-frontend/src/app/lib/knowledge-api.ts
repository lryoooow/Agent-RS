import { apiFetch } from "./http";

export interface GraphNode {
  id: string; label: string; entity_type: string; description?: string;
  document_id?: string; chunk_id?: string; source_title?: string;
  chunk_index?: number;
  resource_kind?: string; configured?: boolean;
}
export interface GraphEdge {
  id: string; source: string; target: string; relation: string; origin?: string;
  score?: number; source_title?: string;
}
export interface KnowledgeGraph {
  nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean; engine: string;
  embedding_model: string; dimensions: number; relation_mode: string;
  jobs: { document_id: string; status: string; attempts: number; error_code?: string }[];
}
export async function getKnowledgeGraph(focus = "*"): Promise<KnowledgeGraph> {
  const res = await apiFetch(`/knowledge/graph?focus=${encodeURIComponent(focus)}`, {});
  return res.json();
}
export async function importPlatformGuides(): Promise<void> {
  await apiFetch("/knowledge/guides", { method: "POST", timeoutMs: 300_000 });
}
export async function retryKnowledgeGraph(): Promise<void> {
  await apiFetch("/knowledge/retry", { method: "POST" });
}
