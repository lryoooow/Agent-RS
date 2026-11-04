import { useEffect, useRef, useState } from "react";
import { Network, Plus, RefreshCw, Save, Download, Search, RotateCcw, Boxes, ArrowRight, Wrench, Loader2 } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { OntologyGraph, type OntologySelection } from "./OntologyGraph";
import { OntologyEditor } from "./OntologyEditor";
import { getOntology, saveOntology, exportOntology, downloadOntology, mergeOntology, removeCustomDefinition, type OntologyDocument, type OntologySchema, type EntityType, type Relationship, type ActionBinding } from "../lib/ontology-api";

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
export function OntologyPage({ active }: { active: boolean }) {
  const [document, setDocument] = useState<OntologyDocument | null>(null);
  const [draft, setDraft] = useState<OntologySchema | null>(null);
  const [busy, setBusy] = useState(false), busyRef = useRef(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [selection, setSelection] = useState<OntologySelection | null>(null);
  const [query, setQuery] = useState(""), [showCode, setShowCode] = useState(false);
  const [tab, setTab] = useState<OntologySelection["kind"]>("entity");
  const dirty = !!draft && !!document && !same(draft, document.schema);
  const stateRef = useRef({ document, draft, dirty }); stateRef.current = { document, draft, dirty };
  const alive = useRef(true);

  const sync = async (automatic = false) => {
    if (busyRef.current || (automatic && stateRef.current.dirty)) return;
    busyRef.current = true; setBusy(true); if (!automatic) setError("");
    try {
      const next = await getOntology(); if (!alive.current) return;
      const current = stateRef.current;
      const merged = current.draft && current.document ? mergeOntology(next.schema, current.document.schema, current.draft) : next.schema;
      setDocument(next); setDraft(merged);
      if (!automatic) setNotice(current.dirty ? "代码已同步，个人草稿已保留。" : "已与当前代码同步。");
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { busyRef.current = false; if (alive.current) setBusy(false); }
  };
  const syncRef = useRef(sync); syncRef.current = sync;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!active) return;
    void syncRef.current(true);
    const refresh = () => { if (window.document.visibilityState === "visible") void syncRef.current(true); };
    const timer = setInterval(refresh, 60_000); window.addEventListener("focus", refresh);
    return () => { clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [active]);
  useEffect(() => {
    if (!dirty) return;
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", unload); return () => window.removeEventListener("beforeunload", unload);
  }, [dirty]);

  const save = async () => {
    if (!draft || !document || busyRef.current) return;
    busyRef.current = true; setBusy(true); setError("");
    try {
      const saved = await saveOntology(draft, document);
      if (alive.current) { setDocument({ ...document, ...saved, schema: draft }); setNotice("个人定义已保存，下次规划将使用更新后的图谱。"); }
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { busyRef.current = false; if (alive.current) setBusy(false); }
  };
  const change = (value: EntityType | Relationship | ActionBinding) => {
    if (!draft || !selection) return;
    if (selection.kind === "entity") setDraft({ ...draft, entity_types: draft.entity_types.map(e => e.id === value.id ? value as EntityType : e) });
    else if (selection.kind === "relationship") setDraft({ ...draft, relationships: draft.relationships.map(r => r.id === value.id ? value as Relationship : r) });
    else setDraft({ ...draft, bindings: { ...draft.bindings, action_bindings: draft.bindings.action_bindings.map(a => a.id === value.id ? value as ActionBinding : a) } });
    setNotice("");
  };
  const add = (kind: OntologySelection["kind"]) => {
    if (!draft) return;
    const id = `custom_${kind}_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
    const base = { id, name: kind === "entity" ? "新实体" : kind === "relationship" ? "新关系" : "新动作", description: "", origin: "custom" as const };
    if (kind === "entity") setDraft({ ...draft, entity_types: [...draft.entity_types, { ...base, color: "#a78bfa", properties: [{ name: "id", type: "string", description: "唯一标识", is_identifier: true }], parent: null }] });
    else if (kind === "relationship") {
      const source = selection?.kind === "entity" ? selection.id : draft.entity_types[0]?.id;
      if (!source) return;
      setDraft({ ...draft, relationships: [...draft.relationships, { ...base, source_entity: source, target_entity: draft.entity_types.find(e => e.id !== source)?.id || source, cardinality: "one-to-many" }] });
    } else {
      const relation = selection?.kind === "relationship" ? draft.relationships.find(r => r.id === selection.id) : draft.relationships[0];
      if (!relation) { setError("请先添加一条关系，再绑定工具。"); return; }
      setDraft({ ...draft, bindings: { ...draft.bindings, action_bindings: [...draft.bindings.action_bindings, { ...base, tool_name: document?.tools[0]?.name || "new_tool", relationship_id: relation.id, preconditions: [], parameter_bindings: {}, output_entities: [relation.target_entity] }] } });
    }
    setTab(kind); setSelection({ kind, id }); setQuery(""); setError("");
  };
  const remove = () => {
    if (!draft || !selection) return;
    try { setDraft(removeCustomDefinition(draft, selection.kind, selection.id)); setSelection(null); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const items = draft ? tab === "entity" ? draft.entity_types.filter(e => showCode || (!e.id.startsWith("schema.") && !e.id.startsWith("arguments."))) : tab === "relationship" ? draft.relationships.filter(r => showCode || !r.id.startsWith("args_")) : draft.bindings.action_bindings : [];
  const visible = items.filter(i => `${i.name} ${i.id} ${i.description} ${"tool_name" in i ? i.tool_name : ""}`.toLowerCase().includes(query.toLowerCase()));
  return <section aria-label="功能图谱" className={`${active ? "flex" : "hidden"} absolute inset-0 z-[38] min-w-0 flex-col overflow-y-auto bg-background p-4 lg:p-6`}>
    <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div><div className="mb-1 flex items-center gap-2 text-xs text-primary"><Network className="size-4" />ONTOLOGY</div><h1 className="text-2xl font-semibold tracking-tight">功能图谱</h1><p className="mt-1 text-xs leading-5 text-muted-foreground">浏览平台能力，连接实体与工具，定义自己的分析路径。</p></div>
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void sync()}><RefreshCw className={`size-3.5 ${busy ? "animate-spin" : ""}`} />同步代码</Button><Button size="sm" disabled={busy || !dirty || !document?.writable} onClick={() => void save()}><Save className="size-3.5" />保存定义</Button></div>
    </header>
    {error && <div role="alert" className="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs leading-5 text-destructive">{error}</div>}
    <div aria-live="polite" className="mb-3 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground"><span className={dirty ? "text-amber-500" : "text-primary"}>{dirty ? "● 有未保存修改" : "● 已同步"}</span>{notice && <span>{notice}</span>}{document && !document.writable && <span>当前未启用图谱存储，可编辑并导出定义；启用数据库后可保存。</span>}<span className="ml-auto">{draft?.entity_types.length ?? 0} 实体 · {draft?.relationships.length ?? 0} 关系 · {document?.tools.filter(t => t.registered).length ?? 0} 已注册工具</span></div>
    {!draft || !document ? <div className="grid min-h-80 flex-1 place-items-center text-sm text-muted-foreground">{busy ? <span className="flex items-center gap-2"><Loader2 className="size-4 animate-spin" />正在读取平台定义…</span> : <Button variant="outline" onClick={() => void sync()}>重新读取图谱</Button>}</div> : <>
      <div className="mb-3 flex flex-wrap items-center gap-2"><div className="relative min-w-44 flex-1"><Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" /><Input aria-label="搜索功能图谱" placeholder="搜索地物分类、目标检测、实体或工具…" value={query} onChange={e => setQuery(e.target.value)} className="h-9 pl-8 text-xs" /></div>
        <label className="mr-2 flex items-center gap-2 whitespace-nowrap text-xs text-muted-foreground"><input type="checkbox" checked={showCode} onChange={e => setShowCode(e.target.checked)} />显示代码结构</label>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => add("entity")}><Plus className="size-3.5" />实体</Button><Button variant="outline" size="sm" disabled={busy} onClick={() => add("relationship")}><Plus className="size-3.5" />关系</Button><Button variant="outline" size="sm" disabled={busy} onClick={() => add("action")}><Wrench className="size-3.5" />绑定工具</Button>
      </div>
      <div className="flex min-h-[480px] flex-none flex-col gap-3 xl:min-h-0 xl:flex-1 xl:flex-row">
        <div className="flex min-h-[360px] min-w-0 flex-1 flex-col gap-2"><OntologyGraph schema={draft} tools={document.tools} showCode={showCode} query={query} selection={selection} onSelect={s => { setSelection(s); setTab(s.kind); }} active={active} />
          <div className="flex flex-wrap items-center gap-4 px-1 text-[11px] text-muted-foreground"><span>● 业务实体</span><span className="text-blue-400">■ 工具动作</span><span>→ 数据流转</span><span>┄ 继承关系</span><span className="ml-auto">个人定义仅对当前账号生效</span></div></div>
        <aside aria-label="图谱定义编辑器" className="flex max-h-[70vh] w-full shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card xl:max-h-none xl:w-[330px]">
          <div className="flex shrink-0 gap-1 border-b border-border p-2">{([{ kind: "entity", label: "实体", icon: Boxes }, { kind: "relationship", label: "关系", icon: ArrowRight }, { kind: "action", label: "工具", icon: Wrench }] as const).map(({ kind, label, icon: Icon }) => <button key={kind} className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2 text-xs ${tab === kind ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"}`} onClick={() => { setTab(kind); setSelection(null); }}><Icon className="size-3.5" />{label}</button>)}</div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {selection ? <><button className="mb-4 text-xs text-primary hover:underline" onClick={() => setSelection(null)}>← 返回列表</button><fieldset disabled={busy}><OntologyEditor key={`${selection.kind}:${selection.id}`} schema={draft} tools={document.tools} selection={selection} onChange={change} onDelete={remove} /></fieldset></> : <>
              <p className="mb-3 text-xs text-muted-foreground">选择节点查看属性与绑定 · {visible.length} 项</p><div className="space-y-1">{visible.map(item => <button key={item.id} className="flex w-full items-center gap-2 rounded-lg px-2 py-2.5 text-left hover:bg-muted" onClick={() => setSelection({ kind: tab, id: item.id })}><span className="size-2 shrink-0 rounded-full" style={{ background: "color" in item ? item.color : tab === "action" ? "#60a5fa" : "#94a3b8" }} /><span className="min-w-0"><span className="block text-xs">{item.name}</span><span className="block truncate font-mono text-[10px] text-muted-foreground">{"tool_name" in item ? item.tool_name : item.id}</span></span>{item.origin === "custom" && <span className="ml-auto text-[10px] text-primary">个人</span>}</button>)}{!visible.length && <p className="py-8 text-center text-xs text-muted-foreground">没有匹配的定义</p>}</div>
              {tab === "action" && document.tools.some(t => !t.registered) && <div className="mt-4 rounded-lg border border-amber-500/30 p-3 text-xs"><h3 className="mb-2 text-amber-500">源码发现 · 待接入</h3>{document.tools.filter(t => !t.registered).map(t => <p key={t.name} className="mb-2 break-all leading-5">{t.name}<br /><span className="text-muted-foreground">{t.source} · 尚未注册，不可执行</span></p>)}</div>}
            </>}
          </div>
        </aside>
      </div>
      <footer className="mt-4 flex flex-wrap items-center gap-2"><Button size="sm" variant="ghost" onClick={() => downloadOntology(draft, "ontology_schema.json")}><Download className="size-3.5" />导出定义</Button><Button size="sm" variant="ghost" disabled={dirty || busy} title="导出已保存的图谱，供 Microsoft Ontology Playground 导入" onClick={async () => { try { downloadOntology(await exportOntology(), "ontology_playground.json"); } catch (e) { setError(String(e)); } }}><Download className="size-3.5" />Playground</Button><Button size="sm" variant="ghost" disabled={!dirty || busy} onClick={() => { setDraft(document.schema); setSelection(null); setError(""); setNotice("已撤销未保存的修改。"); }}><RotateCcw className="size-3.5" />撤销修改</Button><p className="ml-auto max-w-xl text-[11px] leading-5 text-muted-foreground">页面打开时每分钟自动同步；有草稿时暂停自动同步。新增工具需完成代码注册并重新加载服务，才能用于规划与执行。</p></footer>
    </>}
  </section>;
}
