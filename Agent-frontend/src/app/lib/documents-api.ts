import { getDocumentsEndpoint } from "../config";
import type {
  DocumentChunk,
  DocumentJob,
  DocumentSearchResponse,
  KnowledgeDocument,
} from "../types";
import { readErrorMessage } from "./errors";

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

export async function listDocuments(chatEndpoint: string): Promise<KnowledgeDocument[]> {
  const res = await fetch(getDocumentsEndpoint(chatEndpoint), { credentials: "include" });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { documents?: KnowledgeDocument[] };
  return payload.documents ?? [];
}

export async function createDocument(
  chatEndpoint: string,
  body: DocumentCreateBody,
): Promise<DocumentCreateResult> {
  const res = await fetch(getDocumentsEndpoint(chatEndpoint), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await readApiError(res);
  return (await res.json()) as DocumentCreateResult;
}

export async function uploadDocumentFile(
  chatEndpoint: string,
  file: File,
  title?: string,
  metadata?: Record<string, unknown>,
): Promise<DocumentUploadJobResult> {
  const formData = new FormData();
  formData.append("file", file);
  if (title?.trim()) formData.append("title", title.trim());
  if (metadata) formData.append("metadata", JSON.stringify(metadata));

  const res = await fetch(`${getDocumentsEndpoint(chatEndpoint).replace(/\/$/, "")}/upload`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (!res.ok) throw await readApiError(res);
  return (await res.json()) as DocumentUploadJobResult;
}

export async function getDocumentJob(chatEndpoint: string, jobId: string): Promise<DocumentJob> {
  const base = getDocumentsEndpoint(chatEndpoint).replace(/\/$/, "");
  const res = await fetch(`${base}/jobs/${jobId}`, { credentials: "include" });
  if (!res.ok) throw await readApiError(res);
  return (await res.json()) as DocumentJob;
}

export async function listDocumentChunks(
  chatEndpoint: string,
  documentId: string,
): Promise<DocumentChunk[]> {
  const base = getDocumentsEndpoint(chatEndpoint).replace(/\/$/, "");
  const res = await fetch(`${base}/${documentId}/chunks?limit=50`, { credentials: "include" });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { chunks?: DocumentChunk[] };
  return payload.chunks ?? [];
}

export async function searchDocuments(
  chatEndpoint: string,
  query: string,
): Promise<DocumentSearchResponse> {
  const base = getDocumentsEndpoint(chatEndpoint).replace(/\/$/, "");
  const res = await fetch(`${base}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ query, limit: 8 }),
  });
  if (!res.ok) throw await readApiError(res);
  return (await res.json()) as DocumentSearchResponse;
}

export async function deleteDocument(chatEndpoint: string, documentId: string): Promise<void> {
  const base = getDocumentsEndpoint(chatEndpoint).replace(/\/$/, "");
  const res = await fetch(`${base}/${documentId}`, { method: "DELETE", credentials: "include" });
  if (!res.ok) throw await readApiError(res);
}

async function readApiError(res: Response) {
  const payload = await res.json().catch(() => null);
  return new Error(readErrorMessage(payload) ?? `${res.status} ${res.statusText}`);
}
