import { useEffect, useRef, useState } from "react";
import { Upload, Search, Trash2, FileText, Loader2, RefreshCw } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { ScrollArea } from "./ui/scroll-area";
import { Progress } from "./ui/progress";
import {
  listDocuments,
  uploadDocumentFile,
  getDocumentJob,
  searchDocuments,
  deleteDocument,
} from "../lib/documents-api";
import type { KnowledgeDocument, DocumentSearchResult } from "../types";

const TERMINAL = new Set(["done", "failed"]);

export function KnowledgePanel({ endpoint }: { endpoint: string }) {
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DocumentSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      setDocs(await listDocuments(endpoint));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint]);

  const handleUpload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setProgress(5);
    setError("");
    try {
      const { job_id } = await uploadDocumentFile(endpoint, file);
      // 轮询任务进度直到 done/failed。
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const job = await getDocumentJob(endpoint, job_id);
        setProgress(job.progress || 0);
        if (TERMINAL.has(job.status)) {
          if (job.status === "failed") {
            setError(job.error_message || "文档处理失败");
          }
          break;
        }
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
      setProgress(0);
    }
  };

  const runSearch = async () => {
    if (!query.trim()) {
      setResults(null);
      return;
    }
    setSearching(true);
    setError("");
    try {
      const res = await searchDocuments(endpoint, query.trim());
      setResults(res.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteDocument(endpoint, id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex h-full flex-col gap-3">
      {/* upload + search bar */}
      <div className="flex flex-col gap-2">
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,.markdown,.pdf,.docx,.pptx,.xlsx"
          className="hidden"
          onChange={(e) => {
            handleUpload(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={uploading}
            onClick={() => fileRef.current?.click()}
            className="gap-1.5"
          >
            {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
            上传文档
          </Button>
          <Button size="sm" variant="ghost" onClick={refresh} disabled={loading} className="gap-1.5">
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
            刷新
          </Button>
          <span className="ml-auto self-center font-mono text-[10px] text-muted-foreground">
            {docs.length} 篇
          </span>
        </div>
        {uploading && <Progress value={progress} className="h-1.5" />}
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            placeholder="检索知识库（向量 + BM25 + Rerank）"
            className="h-8 bg-input-background text-[12px]"
          />
          <Button size="sm" onClick={runSearch} disabled={searching} className="gap-1.5">
            {searching ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}
          </Button>
        </div>
      </div>

      {error && <p className="font-mono text-[11px] text-destructive">{error}</p>}

      <ScrollArea className="min-h-0 flex-1">
        {results !== null ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                检索结果 {results.length}
              </span>
              <button
                onClick={() => {
                  setResults(null);
                  setQuery("");
                }}
                className="font-mono text-[10px] text-primary hover:underline"
              >
                返回列表
              </button>
            </div>
            {results.map((r) => (
              <div key={r.id} className="rounded-lg border border-border bg-card p-2.5">
                <p className="line-clamp-3 text-[12px] text-foreground">{r.content_preview}</p>
                <div className="mt-1.5 flex flex-wrap gap-x-3 font-mono text-[10px] text-muted-foreground">
                  {r.rerank_score != null && <span>rerank {r.rerank_score.toFixed(3)}</span>}
                  {r.vector_score != null && <span>vec {r.vector_score.toFixed(3)}</span>}
                  {r.text_score != null && <span>bm25 {r.text_score.toFixed(3)}</span>}
                </div>
              </div>
            ))}
            {results.length === 0 && (
              <p className="py-8 text-center text-[12px] text-muted-foreground">无匹配结果</p>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {docs.map((d) => (
              <div key={d.id} className="flex items-start gap-2 rounded-lg border border-border bg-card p-2.5">
                <FileText className="mt-0.5 size-4 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] text-foreground">{d.title}</div>
                  <div className="font-mono text-[10px] text-muted-foreground">
                    {d.doc_type ?? "text"} · {d.chunk_count} chunks
                    {d.latest_job_status ? ` · ${d.latest_job_status}` : ""}
                  </div>
                </div>
                <button
                  onClick={() => remove(d.id)}
                  className="grid size-6 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:text-destructive"
                  title="删除文档"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))}
            {!loading && docs.length === 0 && (
              <p className="py-8 text-center text-[12px] text-muted-foreground">
                尚无文档，上传后用于 RAG 检索
              </p>
            )}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
