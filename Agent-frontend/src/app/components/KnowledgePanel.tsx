import { useEffect, useRef, useState } from "react";
import { Upload, Search, Trash2, FileText, Loader2, RefreshCw, Network, BookOpen } from "lucide-react";
import { KnowledgeGraphDialog } from "./KnowledgeGraphDialog";
import { importPlatformGuides } from "../lib/knowledge-api";
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

const TERMINAL = new Set(["done", "complete", "failed"]);

export function KnowledgePanel() {
  const [graphOpen, setGraphOpen] = useState(false);
  const [graphFocus, setGraphFocus] = useState("*");
  const [importing, setImporting] = useState(false);
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
      setDocs(await listDocuments());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleUpload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setProgress(5);
    setError("");
    try {
      const { job_id } = await uploadDocumentFile(file);
      // The backend uses complete for successful ingestion.
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const job = await getDocumentJob(job_id);
        setProgress(job.progress || 0);
        if (TERMINAL.has(job.status)) {
          if (job.status === "failed") {
            throw new Error(job.error_message || "文档处理失败");
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
      const res = await searchDocuments(query.trim());
      setResults(res.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteDocument(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <KnowledgeGraphDialog open={graphOpen} onOpenChange={setGraphOpen} initialFocus={graphFocus} />
      <div className="rounded-lg border border-primary/25 bg-primary/5 p-3">
        <p className="text-xs font-medium">文档与 Agent 知识网络</p>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">关联原文、工具与 Agent，为检索和任务提供依据。</p>
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={() => { setGraphFocus("*"); setGraphOpen(true); }}><Network className="size-3.5" />知识图谱</Button>
          <Button size="sm" variant="outline" disabled={importing} onClick={async () => {
            setImporting(true); setError("");
            try { await importPlatformGuides(); await refresh(); }
            catch (err) { setError(err instanceof Error ? err.message : String(err)); }
            finally { setImporting(false); }
          }}>{importing ? <Loader2 className="size-3.5 animate-spin" /> : <BookOpen className="size-3.5" />}导入平台指南</Button>
        </div>
      </div>
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
            placeholder="检索文档内容与方法依据"
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
                  <button className="block max-w-full truncate text-left text-[12.5px] text-foreground hover:text-primary" onClick={() => { setGraphFocus("doc:" + d.id); setGraphOpen(true); }}>{d.title}</button>
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
