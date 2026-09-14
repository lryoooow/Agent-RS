import { apiFetch } from "./http";
import type {
  DocumentChunk,
  DocumentJob,
  DocumentSearchResponse,
  KnowledgeDocument,
} from "../types";

export type DocumentCreateBody = {
  title: string;
  content: string;
  source_url?: string;
  doc_type?: string;
  metadata?: Record<string, unknown>;
};

export type DocumentCreateResult = {
  document_id: string;
  chunk_count: number;
};

export type DocumentUploadJobResult = {
  job_id: string;
  status: string;
};

export async function listDocuments(): Promise<KnowledgeDocument[]> {
  const response = await apiFetch("/documents", {});
  const payload = (await response.json().catch(() => null)) as { documents?: KnowledgeDocument[] } | null;
  return payload?.documents ?? [];
}

export async function createDocument(body: DocumentCreateBody): Promise<DocumentCreateResult> {
  const response = await apiFetch("/documents", { method: "POST", json: body });
  return (await response.json()) as DocumentCreateResult;
}

export async function uploadDocumentFile(
  file: File,
  title?: string,
  metadata?: Record<string, unknown>,
): Promise<DocumentUploadJobResult> {
  const formData = new FormData();
  formData.append("file", file);
  if (title?.trim()) formData.append("title", title.trim());
  if (metadata) formData.append("metadata", JSON.stringify(metadata));

  const response = await apiFetch("/documents/upload", {
    method: "POST",
    formData,
    // 上传大文件：放宽到 5 分钟，不走默认 30s。
    timeoutMs: 300_000,
  });
  return (await response.json()) as DocumentUploadJobResult;
}

export async function getDocumentJob(jobId: string): Promise<DocumentJob> {
  const response = await apiFetch(`/documents/jobs/${jobId}`, {});
  return (await response.json()) as DocumentJob;
}

export async function listDocumentChunks(documentId: string): Promise<DocumentChunk[]> {
  const response = await apiFetch(`/documents/${documentId}/chunks?limit=50`, {});
  const payload = (await response.json().catch(() => null)) as { chunks?: DocumentChunk[] } | null;
  return payload?.chunks ?? [];
}

export async function searchDocuments(query: string): Promise<DocumentSearchResponse> {
  const response = await apiFetch("/documents/search", {
    method: "POST",
    json: { query, limit: 8 },
  });
  return (await response.json()) as DocumentSearchResponse;
}

export async function deleteDocument(documentId: string): Promise<void> {
  await apiFetch(`/documents/${documentId}`, { method: "DELETE" });
}
