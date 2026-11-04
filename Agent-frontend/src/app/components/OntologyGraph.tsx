import { useEffect, useMemo, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { Scan, ZoomIn, ZoomOut } from "lucide-react";
import type { OntologySchema, CatalogTool } from "../lib/ontology-api";

export type OntologySelection = { kind: "entity" | "relationship" | "action"; id: string };

export function ontologyElements(schema: OntologySchema, tools: CatalogTool[], showCode: boolean): ElementDefinition[] {
  const entities = schema.entity_types.filter(e => showCode || (!e.id.startsWith("arguments.") && !e.id.startsWith("schema.")));
  const ids = new Set(entities.map(e => e.id));
  const relations = schema.relationships.filter(r => ids.has(r.source_entity) && ids.has(r.target_entity));
  const actions = schema.bindings.action_bindings.filter(a => relations.some(r => r.id === a.relationship_id));
  const elements: ElementDefinition[] = entities.map(e => ({ data: { id: `entity:${e.id}`, ref: e.id, kind: "entity", label: e.name, color: e.color, description: e.description } }));
  for (const a of actions) {
    const tool = tools.find(t => t.name === a.tool_name);
    const r = relations.find(r => r.id === a.relationship_id)!;
    elements.push({ data: { id: `action:${a.id}`, ref: a.id, kind: "action", label: a.name, color: tool?.registered && tool.enabled ? "#60a5fa" : "#94a3b8", description: a.tool_name } });
    elements.push({ data: { id: `in:${a.id}`, ref: r.id, kind: "relationship", source: `entity:${r.source_entity}`, target: `action:${a.id}`, label: "输入", color: "#426078" } });
    for (const target of a.output_entities.length ? a.output_entities : [r.target_entity]) {
      if (ids.has(target)) elements.push({ data: { id: `out:${a.id}:${target}`, ref: r.id, kind: "relationship", source: `action:${a.id}`, target: `entity:${target}`, label: r.name, color: "#426078" } });
    }
  }
  for (const r of relations.filter(r => !actions.some(a => a.relationship_id === r.id))) {
    elements.push({ data: { id: `relationship:${r.id}`, ref: r.id, kind: "relationship", source: `entity:${r.source_entity}`, target: `entity:${r.target_entity}`, label: r.name, color: "#426078" } });
  }
  for (const e of entities.filter(e => e.parent && ids.has(e.parent))) {
    elements.push({ data: { id: `parent:${e.id}`, ref: e.id, kind: "entity", source: `entity:${e.id}`, target: `entity:${e.parent}`, label: "属于", color: "#6c6287", inheritance: true } });
  }
  return elements;
}

export function OntologyGraph({ schema, tools, showCode, query, selection, onSelect, active }: {
  schema: OntologySchema; tools: CatalogTool[]; showCode: boolean; query: string;
  selection: OntologySelection | null; onSelect: (selection: OntologySelection) => void; active: boolean;
}) {
  const host = useRef<HTMLDivElement>(null), cy = useRef<Core | null>(null), topology = useRef("");
  const select = useRef(onSelect); select.current = onSelect;
  const elements = useMemo(() => ontologyElements(schema, tools, showCode), [schema, tools, showCode]);
  useEffect(() => {
    if (!host.current) return;
    const graph = cytoscape({ container: host.current, elements: [], minZoom: 0.12, maxZoom: 3,
      style: [
        { selector: "node", style: { label: "data(label)", "background-color": "data(color)", color: "#e2e8f0", width: 40, height: 40, "font-size": 12, "text-valign": "bottom", "text-margin-y": 9, "text-wrap": "wrap", "text-max-width": "125px", "border-width": 3, "border-color": "#182a3c" } },
        { selector: 'node[kind="action"]', style: { shape: "round-rectangle", width: 28, height: 28, "font-size": 11, "border-width": 1 } },
        { selector: "edge", style: { width: 1.4, "line-color": "data(color)", "target-arrow-color": "data(color)", "target-arrow-shape": "triangle", "arrow-scale": 0.7, "curve-style": "bezier", label: "data(label)", "font-size": 9, color: "#94a3b8", "text-rotation": "autorotate", "text-background-color": "#0e1726", "text-background-opacity": 0.9, "text-background-padding": "3px" } },
        { selector: "edge[inheritance]", style: { "line-style": "dashed" } },
        { selector: ".selected, :selected", style: { "border-color": "#fbbf24", "border-width": 4, "line-color": "#fbbf24", "target-arrow-color": "#fbbf24" } },
        { selector: ".muted", style: { opacity: 0.12 } },
        { selector: ".match", style: { "border-color": "#fbbf24", "border-width": 4 } },
      ],
    });
    cy.current = graph;
    graph.on("tap", "node, edge", event => select.current({ kind: event.target.data("kind"), id: event.target.data("ref") }));
    const resize = new ResizeObserver(() => {
      graph.resize();
      if (host.current?.clientWidth && host.current?.clientHeight) graph.fit(undefined, 35);
    });
    resize.observe(host.current);
    return () => { resize.disconnect(); graph.destroy(); cy.current = null; topology.current = ""; };
  }, []);
  useEffect(() => {
    const graph = cy.current; if (!graph) return;
    graph.json({ elements });
    const key = elements.map(e => `${e.data.id}:${e.data.source || ""}:${e.data.target || ""}`).join("|");
    if (topology.current !== key) {
      topology.current = key;
      graph.layout({ name: "cose", animate: false, randomize: true, nodeRepulsion: () => 90000, idealEdgeLength: () => 130, componentSpacing: 100, nodeOverlap: 24, nodeDimensionsIncludeLabels: true, padding: 45 }).run();
    }
  }, [elements]);
  useEffect(() => {
    const graph = cy.current; if (!graph) return;
    graph.elements().removeClass("selected muted match");
    if (selection) graph.elements().filter(e => e.data("kind") === selection.kind && e.data("ref") === selection.id).addClass("selected");
    if (query.trim()) {
      const q = query.toLowerCase();
      const matches = graph.nodes().filter(n => `${n.data("label")} ${n.data("description")} ${n.data("ref")}`.toLowerCase().includes(q));
      graph.elements().addClass("muted"); matches.closedNeighborhood().removeClass("muted"); matches.addClass("match");
    }
  }, [query, selection, elements]);
  useEffect(() => { if (active) requestAnimationFrame(() => { cy.current?.resize(); cy.current?.fit(undefined, 45); }); }, [active]);
  return <div className="relative min-h-[300px] min-w-0 flex-1 overflow-hidden rounded-xl border border-border bg-[#0e1726]">
    {/* Cytoscape injects an unlayered position:relative rule; inline positioning keeps a nonzero canvas height. */}
    <div ref={host} role="img" aria-label="平台实体、关系与工具图谱" className="inset-0" style={{ position: "absolute" }} />
    <div className="absolute bottom-4 left-4 flex gap-1 rounded-lg border border-slate-700 bg-[#111e30] p-1 text-slate-200">
      <button title="放大图谱" aria-label="放大图谱" className="rounded p-2 hover:bg-slate-700" onClick={() => cy.current?.zoom((cy.current?.zoom() || 1) * 1.2)}><ZoomIn className="size-4" /></button>
      <button title="缩小图谱" aria-label="缩小图谱" className="rounded p-2 hover:bg-slate-700" onClick={() => cy.current?.zoom((cy.current?.zoom() || 1) / 1.2)}><ZoomOut className="size-4" /></button>
      <button title="适应画布" aria-label="适应画布" className="rounded p-2 hover:bg-slate-700" onClick={() => cy.current?.fit(undefined, 45)}><Scan className="size-4" /></button>
    </div>
    <span className="pointer-events-none absolute bottom-5 right-4 hidden text-[11px] text-slate-400 sm:block">拖动节点 · 滚轮缩放 · 点击查看定义</span>
  </div>;
}
