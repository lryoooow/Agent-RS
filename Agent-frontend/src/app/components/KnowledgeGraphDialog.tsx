import { useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";
import type { Core } from "cytoscape";
import { Network, RefreshCw, Scan, Search, FileText, Loader2, ArrowRight } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { getKnowledgeGraph, retryKnowledgeGraph } from "../lib/knowledge-api";
import type { KnowledgeGraph, GraphNode } from "../lib/knowledge-api";
import { listDocumentChunks } from "../lib/documents-api";

const COLORS: Record<string, string> = { document: "#0ea5e9", chunk: "#64748b", tool: "#14b8a6", agent: "#a78bfa" };
const LABELS: Record<string, string> = { document: "文档", chunk: "原文片段", tool: "工具", agent: "Agent" };

export function KnowledgeGraphDialog({ open, onOpenChange, initialFocus = "*" }: {
  open: boolean; onOpenChange: (value: boolean) => void; initialFocus?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [data, setData] = useState<KnowledgeGraph | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [focus, setFocus] = useState(initialFocus);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [source, setSource] = useState("");
  const [reading, setReading] = useState(false);

  useEffect(() => { if (open) { setFocus(initialFocus); setSelected(null); setSource(""); } }, [open, initialFocus]);
  const refresh = async () => {
    setLoading(true); setError("");
    try { setData(await getKnowledgeGraph(focus)); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setLoading(false); }
  };
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true); setError("");
    getKnowledgeGraph(focus).then(result => { if (!cancelled) setData(result); })
      .catch(err => { if (!cancelled) setError(String(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, focus]);

  useEffect(() => {
    if (!open || !data || !host.current) return;
    const graph = cytoscape({ container: host.current,
      elements: [
        ...data.nodes.map(n => ({ data: { ...n, color: COLORS[n.entity_type] || "#64748b" } })),
        ...data.edges.map(e => ({ data: e })),
      ],
      style: [
        { selector: "node", style: { "background-color": "data(color)", label: "data(label)", color: "#dbeafe", "font-size": 11, "text-valign": "bottom", "text-margin-y": 8, "text-wrap": "ellipsis", "text-max-width": "140px", width: 26, height: 26, "border-width": 2, "border-color": "#0f172a" } },
        { selector: 'node[entity_type="document"], node[entity_type="agent"]', style: { width: 40, height: 40 } },
        { selector: "edge", style: { width: 1.2, "line-color": "#475569", "target-arrow-color": "#475569", "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.6 } },
        { selector: 'edge[origin="embedding_similarity"]', style: { "line-style": "dashed", "line-color": "#0f766e", "target-arrow-color": "#0f766e" } },
        { selector: ":selected", style: { "border-color": "#fbbf24", "border-width": 4 } },
        { selector: ".muted", style: { opacity: 0.15 } },
        { selector: ".match", style: { "border-color": "#fbbf24", "border-width": 4 } },
      ],
      layout: { name: "cose", animate: false, nodeDimensionsIncludeLabels: true, nodeOverlap: 30, componentSpacing: 120, nodeRepulsion: () => 50000, idealEdgeLength: () => 150, padding: 55 },
      minZoom: 0.15, maxZoom: 3,
    });
    cy.current = graph;
    graph.on("tap", "node", event => { setSelected(event.target.data() as GraphNode); setSource(""); });
    const resize = new ResizeObserver(() => { graph.resize(); });
    resize.observe(host.current);
    requestAnimationFrame(() => { graph.resize(); graph.fit(undefined, 45); });
    return () => { resize.disconnect(); graph.destroy(); cy.current = null; };
  }, [open, data]);

  useEffect(() => {
    if (!open || !data?.jobs.some(j => ["pending", "indexing"].includes(j.status))) return;
    const timer = setTimeout(() => { void refresh(); }, 3000);
    return () => clearTimeout(timer);
  }, [open, data, focus]);

  useEffect(() => {
    const graph = cy.current;
    if (!graph) return;
    graph.elements().removeClass("muted match");
    if (!query.trim()) return;
    const q = query.toLowerCase();
    const matches = graph.nodes().filter(n => `${n.data("label")} ${n.data("description") || ""}`.toLowerCase().includes(q));
    graph.elements().addClass("muted");
    matches.closedNeighborhood().removeClass("muted"); matches.addClass("match");
  }, [query, data]);

  useEffect(() => { setSource(""); }, [selected]);
  const readSource = async () => {
    if (!selected?.document_id) return;
    setReading(true); setError("");
    try {
      const chunks = await listDocumentChunks(selected.document_id, selected.chunk_index ?? 0, selected.chunk_id ? 1 : 20);
      const picked = selected.chunk_id ? chunks.filter(c => c.id === selected.chunk_id) : chunks;
      setSource((!selected.chunk_id ? "原文前 20 个片段（点击图中的片段节点可查看对应位置）\n\n" : "") + (picked.map(c => c.content).join("\n\n") || selected.description || "无可显示片段"));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setReading(false); }
  };
  const adjacent = data?.edges.filter(e => selected && (e.source === selected.id || e.target === selected.id)) || [];
  const pending = data?.jobs.filter(j => ["pending", "indexing"].includes(j.status)).length || 0;
  const failed = data?.jobs.filter(j => j.status === "failed").length || 0;

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="flex h-[88vh] w-[94vw] max-w-none flex-col gap-3 overflow-hidden p-5 sm:max-w-[1400px]">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2"><Network className="size-5 text-primary" />知识图谱</DialogTitle>
        <DialogDescription>文档 → 原文片段 → 工具 → Agent · 点击节点查看依据，拖动与滚轮缩放</DialogDescription>
      </DialogHeader>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex min-w-40 flex-1 items-center gap-2"><Search className="size-4 text-muted-foreground" /><Input aria-label="搜索图谱节点" placeholder="搜索文档、工具或 Agent" value={query} onChange={e => setQuery(e.target.value)} className="h-8" /></div>
        <Button size="sm" variant="outline" onClick={() => { setFocus("*"); setSelected(null); }} disabled={focus === "*"}>全部图谱</Button>
        <Button size="sm" variant="outline" onClick={() => cy.current?.fit(undefined, 45)}><Scan className="size-3.5" />适应画布</Button>
        <Button size="sm" variant="outline" disabled={loading} onClick={refresh}><RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />刷新</Button>
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        {Object.entries(LABELS).map(([kind, label]) => <span key={kind} className="flex items-center gap-1.5"><i className="size-2 rounded-full" style={{ background: COLORS[kind] }} />{label}</span>)}
        <span>{data?.nodes.length || 0} 节点 · {data?.edges.length || 0} 关系</span>
        {pending > 0 && <span>后台建图中：{pending} 篇，自动刷新</span>}
        {failed > 0 && <button className="text-destructive underline" onClick={async () => { try { await retryKnowledgeGraph(); await refresh(); } catch (e) { setError(String(e)); } }}>重试 {failed} 篇失败文档</button>}
      </div>
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {data?.truncated && <p className="text-xs text-amber-500">图谱较大，当前展示部分节点。请从文档列表打开单篇文档图谱。</p>}
      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
        <div ref={host} role="img" aria-label="文档与 Agent 关联图" className="min-h-[220px] min-w-0 flex-1 rounded-lg border border-border bg-[#0b1324]" />
        <aside className="max-h-[35vh] w-full shrink-0 overflow-y-auto rounded-lg border border-border bg-card p-4 md:max-h-none md:w-[330px]">
          {selected ? <>
            <p className="text-xs text-primary">{LABELS[selected.entity_type] || selected.entity_type}</p>
            <h3 className="mt-1 break-words text-sm font-semibold">{selected.label}</h3>
            <p className="mt-3 max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-xs leading-6 text-muted-foreground">{selected.description}</p>
            {selected.source_title && <p className="mt-3 text-xs">来源：{selected.source_title}</p>}
            {selected.document_id && <Button size="sm" variant="outline" className="mt-3" onClick={readSource} disabled={reading}>{reading ? <Loader2 className="size-3 animate-spin" /> : <FileText className="size-3" />}查看原文</Button>}
            {selected.document_id && <Button size="sm" variant="ghost" className="mt-3" onClick={() => setFocus("doc:" + selected.document_id)}>聚焦本文</Button>}
            {source && <pre className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs leading-6">{source}</pre>}
            {selected.entity_type === "tool" && <p className="mt-3 text-xs text-muted-foreground">资源类型：{selected.resource_kind}。注册关系来自平台配置，运行时仍会检查模型与计算服务。</p>}
            <h4 className="mt-5 text-xs font-semibold">关联关系 · {adjacent.length}</h4>
            <div className="mt-2 space-y-2">{adjacent.slice(0, 30).map(e => {
              const other = data?.nodes.find(n => n.id === (e.source === selected.id ? e.target : e.source));
              return <button key={e.id} className="flex w-full items-start gap-2 rounded border border-border p-2 text-left text-xs hover:bg-muted" onClick={() => other && setSelected(other)}>
                <ArrowRight className="mt-0.5 size-3 shrink-0" /><span><span className="text-primary">{e.relation}</span>{e.origin === "embedding_similarity" && <span className="text-muted-foreground"> · 相似度 {e.score?.toFixed(2)}</span>}<br />{other?.label || "节点"}</span>
              </button>;
            })}</div>
          </> : <>
            <h3 className="text-sm font-semibold">让知识连接工作</h3>
            <p className="mt-3 text-xs leading-6 text-muted-foreground">选择文档、工具或 Agent，查看原文依据和关联路径。虚线表示向量模型发现的语义关联，需要结合任务核实。</p>
            <p className="mt-3 text-xs leading-6 text-muted-foreground">聊天中开启知识库检索后，相关片段和图谱关系会一起提供给 Agent。</p>
            <h4 className="mt-5 text-xs font-semibold">节点列表</h4>
            <div className="mt-2 space-y-1">{data?.nodes.filter(n => !query || `${n.label} ${n.description}`.toLowerCase().includes(query.toLowerCase())).slice(0, 80).map(n => <button key={n.id} className="block w-full truncate rounded p-1.5 text-left text-xs hover:bg-muted" onClick={() => { setSelected(n); cy.current?.center(cy.current.getElementById(n.id)); }}>{LABELS[n.entity_type]} · {n.label}</button>)}</div>
          </>}
        </aside>
      </div>
      <p className="text-[11px] text-muted-foreground">{data?.engine || "LightRAG / PostgreSQL"} · {data?.embedding_model || "本地 Embedding"} · {data?.dimensions || "—"} 维 · 语义关联用于参考，调用工具仍需符合用户任务与权限。</p>
    </DialogContent>
  </Dialog>;
}
