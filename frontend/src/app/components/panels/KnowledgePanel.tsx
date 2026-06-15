import { FileText, RefreshCw, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  createDocument,
  deleteDocument,
  getDocumentJob,
  listDocuments,
  listDocumentChunks,
  searchDocuments,
  uploadDocumentFile,
} from "../../lib/documents-api";
import type { DocumentChunk, DocumentJob, DocumentSearchResponse, KnowledgeDocument } from "../../types";

type KnowledgePanelProps = {
  endpoint: string;
};

export function KnowledgePanel({ endpoint }: KnowledgePanelProps) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [activeJob, setActiveJob] = useState<DocumentJob | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocument | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResult, setSearchResult] = useState<DocumentSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const canUpload = title.trim().length > 0 && content.trim().length > 0 && !uploading;

  const totalChunks = useMemo(
    () => documents.reduce((sum, document) => sum + document.chunk_count, 0),
    [documents],
  );

  async function refreshDocuments() {
    setLoading(true);
    setError("");
    try {
      setDocuments(await listDocuments(endpoint));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refreshDocuments();
  }, [endpoint]);

  async function handleFileChange(file: File | undefined) {
    if (!file) return;
    setError("");
    setStatus("");

    if (isEditableTextFile(file)) {
      const text = await readUtf8TextFile(file);
      if (text !== null) {
        setTitle((current) => (current.trim() ? current : titleFromFilename(file.name)));
        setContent(text);
        setStatus("loaded · edit then upload");
        if (fileInputRef.current) fileInputRef.current.value = "";
        return;
      }
      setStatus("encoding fallback upload");
    }

    setUploading(true);
    try {
      const result = await uploadDocumentFile(endpoint, file, title || file.name, {
        source: "frontend_file_upload",
      });
      setStatus(`job queued · ${result.job_id}`);
      setTitle("");
      setContent("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      await pollJob(result.job_id);
      await refreshDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  async function handleUpload() {
    if (!canUpload) return;
    setUploading(true);
    setError("");
    setStatus("");
    try {
      const result = await createDocument(endpoint, {
        title: title.trim(),
        content: content.trim(),
        doc_type: "text",
        metadata: { source: "frontend_text_panel" },
      });
      setStatus(`uploaded · ${result.chunk_count} chunks`);
      setTitle("");
      setContent("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refreshDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId: string) {
    setError("");
    setStatus("");
    try {
      await deleteDocument(endpoint, documentId);
      setStatus("deleted");
      await refreshDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function pollJob(jobId: string) {
    for (let attempt = 0; attempt < 240; attempt += 1) {
      const job = await getDocumentJob(endpoint, jobId);
      setActiveJob(job);
      setStatus(`${job.status} · ${job.progress}%`);
      if (job.status === "complete" || job.status === "failed") return;
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
  }

  async function handleSelectDocument(document: KnowledgeDocument) {
    setSelectedDocument(document);
    setError("");
    try {
      setChunks(await listDocumentChunks(endpoint, document.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setError("");
    try {
      setSearchResult(await searchDocuments(endpoint, searchQuery.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="border-b border-border bg-card/60 px-6 md:px-10 py-5">
      <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <div
              className="text-[11px] tracking-[0.18em] uppercase text-muted-foreground"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              knowledge input
            </div>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center gap-1.5 border border-border rounded-md px-3 py-1.5 text-xs hover:bg-muted transition-colors"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              <FileText className="size-3.5" />
              txt / md / pdf / docx
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.md,.markdown,.pdf,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="hidden"
              onChange={(event) => handleFileChange(event.target.files?.[0])}
            />
          </div>

          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="document title"
            className="w-full bg-transparent border border-border rounded-md px-3 py-2 text-sm outline-none focus:border-foreground/40 transition-colors placeholder:text-muted-foreground/60"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          />

          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="Paste text, or load a .txt / .md file."
            rows={8}
            className="w-full resize-none bg-transparent border border-border rounded-md px-3 py-2 text-sm outline-none focus:border-foreground/40 transition-colors placeholder:text-muted-foreground/60"
          />

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={!canUpload}
              onClick={handleUpload}
              className="inline-flex items-center gap-1.5 border border-border rounded-md px-3 py-2 text-xs hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              <Upload className="size-3.5" />
              {uploading ? "uploading" : "upload"}
            </button>
            {status && (
              <span
                className="text-xs text-muted-foreground"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {status}
              </span>
            )}
            {error && (
              <span
                className="text-xs text-destructive"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {error}
              </span>
            )}
          </div>
          {activeJob && (
            <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
              <div
                className="uppercase tracking-[0.14em]"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                ingest job · {activeJob.status} · {activeJob.progress}%
              </div>
              <div className="mt-2 h-1.5 rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-foreground transition-all"
                  style={{ width: `${activeJob.progress}%` }}
                />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <span>chunks · {activeJob.chunk_count ?? "-"}</span>
                <span>embeddings · {activeJob.embedding_batches ?? "-"}</span>
                <span>text · {activeJob.text_length ?? "-"}</span>
                <span>document · {activeJob.document_id ?? "-"}</span>
              </div>
              {activeJob.error_message && (
                <div className="mt-2 text-destructive">{activeJob.error_message}</div>
              )}
            </div>
          )}
        </section>

        <section className="flex min-h-0 flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <div
              className="text-[11px] tracking-[0.18em] uppercase text-muted-foreground"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              documents · {documents.length} · chunks {totalChunks}
            </div>
            <button
              type="button"
              onClick={refreshDocuments}
              disabled={loading}
              className="inline-flex items-center gap-1.5 border border-border rounded-md px-3 py-1.5 text-xs hover:bg-muted transition-colors disabled:opacity-40"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
              refresh
            </button>
          </div>

          <div className="max-h-72 overflow-y-auto border border-border rounded-md">
            {documents.length === 0 ? (
              <div
                className="px-3 py-8 text-center text-xs text-muted-foreground"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                no documents
              </div>
            ) : (
              <div className="divide-y divide-border">
                {documents.map((document) => (
                  <div key={document.id} className="flex items-start justify-between gap-3 px-3 py-3">
                    <button
                      type="button"
                      onClick={() => handleSelectDocument(document)}
                      className="min-w-0 text-left"
                    >
                      <div className="truncate text-sm">{document.title}</div>
                      <div
                        className="mt-1 text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
                        style={{ fontFamily: "'JetBrains Mono', monospace" }}
                      >
                        {document.doc_type || "document"} · {document.chunk_count} chunks ·{" "}
                        {formatDate(document.created_at)}
                        {document.latest_job_status ? ` · ${document.latest_job_status}` : ""}
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(document.id)}
                      className="shrink-0 inline-flex size-8 items-center justify-center border border-border rounded-md hover:bg-muted transition-colors"
                      aria-label={`delete ${document.title}`}
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section className="border border-border rounded-md p-3">
          <div
            className="text-[11px] tracking-[0.18em] uppercase text-muted-foreground"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            chunks · {selectedDocument?.title ?? "select a document"}
          </div>
          <div className="mt-3 max-h-72 overflow-y-auto divide-y divide-border">
            {chunks.map((chunk) => (
              <div key={chunk.id} className="py-3 text-xs">
                <div
                  className="mb-1 uppercase tracking-[0.14em] text-muted-foreground"
                  style={{ fontFamily: "'JetBrains Mono', monospace" }}
                >
                  #{chunk.chunk_index} · {chunk.char_count} chars
                </div>
                <div className="line-clamp-4 whitespace-pre-wrap">{chunk.content}</div>
              </div>
            ))}
            {selectedDocument && chunks.length === 0 && (
              <div className="py-6 text-center text-xs text-muted-foreground">no chunks</div>
            )}
          </div>
        </section>
        <section className="border border-border rounded-md p-3">
          <div
            className="text-[11px] tracking-[0.18em] uppercase text-muted-foreground"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            retrieval test
          </div>
          <div className="mt-3 flex gap-2">
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="query knowledge base"
              className="min-w-0 flex-1 bg-transparent border border-border rounded-md px-3 py-2 text-sm outline-none focus:border-foreground/40"
            />
            <button
              type="button"
              onClick={handleSearch}
              disabled={searching || !searchQuery.trim()}
              className="border border-border rounded-md px-3 py-2 text-xs disabled:opacity-40"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              search
            </button>
          </div>
          {searchResult && (
            <div className="mt-3 max-h-72 overflow-y-auto divide-y divide-border text-xs">
              <pre className="mb-2 overflow-x-auto text-[10px] text-muted-foreground">
                {JSON.stringify(searchResult.trace, null, 2)}
              </pre>
              {searchResult.results.map((item) => (
                <div key={item.id} className="py-3">
                  <div
                    className="mb-1 uppercase tracking-[0.14em] text-muted-foreground"
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    vector {fmt(item.vector_score)} · text {fmt(item.text_score)} · rrf{" "}
                    {fmt(item.rrf_score)} · rerank {fmt(item.rerank_score)} · mmr{" "}
                    {item.selected_by_mmr ? "yes" : "no"}
                  </div>
                  <div className="line-clamp-4 whitespace-pre-wrap">{item.content_preview}</div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
}

function isEditableTextFile(file: File) {
  const name = file.name.toLowerCase();
  return name.endsWith(".txt") || name.endsWith(".md") || name.endsWith(".markdown");
}

async function readUtf8TextFile(file: File) {
  try {
    const buffer = await file.arrayBuffer();
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer).replace(/^\uFEFF/, "");
  } catch {
    return null;
  }
}

function titleFromFilename(filename: string) {
  return filename.replace(/\.[^.]+$/, "") || filename;
}

function fmt(value?: number | null) {
  return typeof value === "number" ? value.toFixed(3) : "-";
}
