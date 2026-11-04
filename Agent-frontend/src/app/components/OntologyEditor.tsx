import { Plus, Trash2 } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import type { ActionBinding, CatalogTool, Condition, Definition, EntityProperty, EntityType, OntologySchema, Relationship } from "../lib/ontology-api";
import type { OntologySelection } from "./OntologyGraph";
import type { ReactNode } from "react";

const selectClass = "h-9 w-full min-w-0 rounded-md border border-border bg-background px-2 text-xs";
const origins = { platform: "平台定义", discovered: "代码识别", custom: "个人定义" };
const propertyTypes: EntityProperty["type"][] = ["string", "integer", "double", "boolean", "datetime", "object", "array"];
const scalar = (text: string): string | number | boolean => text === "true" ? true : text === "false" ? false : text.trim() && Number.isFinite(Number(text)) ? Number(text) : text;
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="flex min-w-0 flex-col gap-1.5 text-xs text-muted-foreground">{label}{children}</label>; }

export function OntologyEditor({ schema, tools, selection, onChange, onDelete }: {
  schema: OntologySchema; tools: CatalogTool[]; selection: OntologySelection;
  onChange: (value: EntityType | Relationship | ActionBinding) => void; onDelete: () => void;
}) {
  const item = (selection.kind === "entity" ? schema.entity_types : selection.kind === "relationship" ? schema.relationships : schema.bindings.action_bindings).find(x => x.id === selection.id);
  if (!item) return <p className="text-sm text-muted-foreground">请选择图中的实体、关系或动作。</p>;
  const update = (patch: Partial<EntityType & Relationship & ActionBinding>) => onChange({ ...item, ...patch });
  const entityOptions = schema.entity_types.map(e => <option key={e.id} value={e.id}>{e.name}</option>);
  const related = schema.relationships.filter(r => r.source_entity === item.id || r.target_entity === item.id);
  const entity = selection.kind === "entity" ? item as EntityType : null;
  const relation = selection.kind === "relationship" ? item as Relationship : null;
  const action = selection.kind === "action" ? item as ActionBinding : null;
  const tool = tools.find(t => t.name === action?.tool_name);
  const conditionUpdate = (index: number, patch: Partial<Condition>) => action && update({ preconditions: action.preconditions.map((c, i) => i === index ? { ...c, ...patch } : c) });
  return <div className="space-y-4">
    <div className="flex items-center justify-between text-xs"><span className="rounded-full bg-primary/10 px-2 py-1 text-primary">{origins[item.origin]}</span><span className="text-muted-foreground">{selection.kind === "entity" ? "实体" : selection.kind === "relationship" ? "关系" : "工具绑定"}</span></div>
    <p className="break-all font-mono text-[11px] text-muted-foreground" title="稳定标识，用于保持关系引用">{item.id}</p>
    <Field label="名称"><Input aria-label="定义名称" value={item.name} maxLength={120} onChange={e => update({ name: e.target.value })} /></Field>
    <Field label="说明"><Textarea aria-label="定义说明" value={item.description} rows={3} maxLength={2000} onChange={e => update({ description: e.target.value })} /></Field>
    {entity && <>
      <div className="grid grid-cols-[60px_1fr] gap-3"><Field label="颜色"><input type="color" aria-label="实体颜色" className="h-9 w-full rounded bg-background" value={entity.color} onChange={e => update({ color: e.target.value })} /></Field>
        <Field label="继承实体"><select aria-label="继承实体" className={selectClass} value={entity.parent || ""} onChange={e => update({ parent: e.target.value || null })}><option value="">无</option>{schema.entity_types.filter(e => e.id !== entity.id).map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field></div>
      <div className="flex items-center justify-between"><h3 className="text-sm font-medium">属性 · {entity.properties.length}</h3><Button size="sm" variant="ghost" onClick={() => update({ properties: [...entity.properties, { name: `property_${entity.properties.length + 1}`, type: "string", description: "", is_identifier: false }] })}><Plus className="size-3" />添加属性</Button></div>
      {entity.properties.map((p, i) => <div key={i} className="space-y-2 rounded-lg border border-border p-2.5">
        <div className="flex gap-2"><Input aria-label={`属性 ${i + 1} 名称`} value={p.name} className="h-8 text-xs" onChange={e => update({ properties: entity.properties.map((v, n) => n === i ? { ...v, name: e.target.value } : v) })} /><button aria-label={`删除属性 ${i + 1}`} onClick={() => update({ properties: entity.properties.filter((_, n) => n !== i) })}><Trash2 className="size-3.5 text-muted-foreground" /></button></div>
        <div className="flex items-center gap-2"><select aria-label={`属性 ${i + 1} 类型`} className={selectClass} value={p.type} onChange={e => update({ properties: entity.properties.map((v, n) => n === i ? { ...v, type: e.target.value as EntityProperty["type"] } : v) })}>{propertyTypes.map(t => <option key={t}>{t}</option>)}</select>
          <label className="flex shrink-0 items-center gap-1 text-[11px]"><input type="checkbox" checked={p.is_identifier} onChange={e => update({ properties: entity.properties.map((v, n) => n === i ? { ...v, is_identifier: e.target.checked } : v) })} />标识</label></div>
        <Input aria-label={`属性 ${i + 1} 说明`} placeholder="属性说明" className="h-8 text-xs" value={p.description} onChange={e => update({ properties: entity.properties.map((v, n) => n === i ? { ...v, description: e.target.value } : v) })} />
      </div>)}
      {schema.bindings.data_bindings.filter(b => b.entity_id === entity.id).map((b, i) => <div key={i} className="rounded-lg bg-muted/40 p-3 text-xs"><p className="mb-2 font-medium">数据来源</p><p className="break-all text-muted-foreground">{b.source}</p>{Object.entries(b.fields).map(([k, v]) => <p key={k} className="mt-1 break-all text-muted-foreground">{k} → {v}</p>)}</div>)}
      {related.length > 0 && <div className="text-xs leading-6"><h3 className="font-medium">关联关系</h3>{related.map(r => <p key={r.id} className="text-muted-foreground">{schema.entity_types.find(e => e.id === r.source_entity)?.name} → {r.name} → {schema.entity_types.find(e => e.id === r.target_entity)?.name}</p>)}</div>}
    </>}
    {relation && <>
      <Field label="上游实体"><select className={selectClass} aria-label="上游实体" value={relation.source_entity} onChange={e => update({ source_entity: e.target.value })}>{entityOptions}</select></Field>
      <Field label="下游实体"><select className={selectClass} aria-label="下游实体" value={relation.target_entity} onChange={e => update({ target_entity: e.target.value })}>{entityOptions}</select></Field>
      <Field label="关系数量"><select className={selectClass} aria-label="关系数量" value={relation.cardinality} onChange={e => update({ cardinality: e.target.value as Relationship["cardinality"] })}>{["one-to-one", "one-to-many", "many-to-one", "many-to-many"].map(t => <option key={t}>{t}</option>)}</select></Field>
      <p className="text-xs leading-6 text-muted-foreground">已绑定：{schema.bindings.action_bindings.filter(a => a.relationship_id === relation.id).map(a => a.name).join("、") || "暂无工具，可通过顶部“绑定工具”添加。"}</p>
    </>}
    {action && <>
      <Field label="绑定工具"><Input aria-label="绑定工具" list={`ontology-tools-${action.id}`} value={action.tool_name} onChange={e => update({ tool_name: e.target.value })} placeholder="选择已有工具或输入待接入名称" />
        <datalist id={`ontology-tools-${action.id}`}>{tools.map(t => <option key={t.name} value={t.name}>{!t.registered ? "待注册" : !t.enabled ? "未启用" : "已注册"}</option>)}</datalist></Field>
      <Field label="挂载关系"><select className={selectClass} aria-label="挂载关系" value={action.relationship_id} onChange={e => update({ relationship_id: e.target.value })}>{schema.relationships.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field>
      <Field label="输出实体（可多选）"><select multiple className={`${selectClass} h-24`} aria-label="输出实体" value={action.output_entities} onChange={e => update({ output_entities: Array.from(e.target.selectedOptions, o => o.value) })}>{entityOptions}</select></Field>
      <div className="rounded-lg bg-muted/40 p-3 text-xs leading-5"><p className={tool?.registered && tool.enabled ? "text-primary" : "text-amber-500"}>{tool?.registered ? tool.enabled ? "已注册 · 可供规划" : "已注册 · 当前未启用" : "待接入 · 不能执行"}</p><p className="mt-1 text-muted-foreground">{tool?.description || "工具需要在平台代码中注册后才能执行。"}</p><p className="mt-2 break-all text-muted-foreground">{tool?.source}</p></div>
      <div className="flex items-center justify-between"><h3 className="text-sm font-medium">前置条件</h3><Button variant="ghost" size="sm" onClick={() => update({ preconditions: [...action.preconditions, { field: "entity.status", op: "eq", value: "ready", when: {}, message: "实体需处于就绪状态" }] })}><Plus className="size-3" />添加条件</Button></div>
      <p className="text-[11px] leading-5 text-muted-foreground">全部条件同时满足。平台必要条件与权限检查始终保留；缺少状态证据时由原工具核验。</p>
      {action.preconditions.map((c, i) => <div key={i} className="space-y-2 rounded-lg border border-border p-3">
        <div className="flex items-center justify-between text-xs"><span>条件 {i + 1}</span><button aria-label={`删除条件 ${i + 1}`} onClick={() => update({ preconditions: action.preconditions.filter((_, n) => n !== i) })}><Trash2 className="size-3.5" /></button></div>
        <Input aria-label={`条件 ${i + 1} 字段`} placeholder="entity.status" className="h-8 text-xs" value={c.field} onChange={e => conditionUpdate(i, { field: e.target.value })} />
        <select aria-label={`条件 ${i + 1} 操作`} className={selectClass} value={c.op} onChange={e => { const op = e.target.value as Condition["op"]; conditionUpdate(i, { op, value: op === "in" || op === "contains_all" ? [] : "" }); }}>
          <option value="exists">存在</option><option value="eq">等于</option><option value="in">属于列表</option><option value="contains_all">包含全部</option><option value="gte">大于等于</option></select>
        {c.op !== "exists" && <Input aria-label={`条件 ${i + 1} 值`} className="h-8 text-xs" placeholder={c.op === "in" || c.op === "contains_all" ? "逗号分隔，如 red,nir" : "true / 数字 / 文本"} value={Array.isArray(c.value) ? c.value.join(",") : String(c.value ?? "")} onChange={e => conditionUpdate(i, { value: c.op === "in" || c.op === "contains_all" ? e.target.value.split(",").map(x => scalar(x.trim())) : scalar(e.target.value) })} />}
        <Input aria-label={`条件 ${i + 1} 提示`} className="h-8 text-xs" placeholder="条件不满足时的说明" value={c.message} onChange={e => conditionUpdate(i, { message: e.target.value })} />
        <Field label="仅在以下参数取值时检查（可留空）"><div className="flex gap-2"><Input aria-label={`条件 ${i + 1} 适用参数`} className="h-8 text-xs" placeholder="index_type" value={Object.keys(c.when)[0] || ""} onChange={e => conditionUpdate(i, { when: e.target.value ? { [e.target.value]: Object.values(c.when)[0] ?? "" } : {} })} /><Input aria-label={`条件 ${i + 1} 适用值`} className="h-8 text-xs" placeholder="NDVI" value={String(Object.values(c.when)[0] ?? "")} disabled={!Object.keys(c.when).length} onChange={e => conditionUpdate(i, { when: { [Object.keys(c.when)[0]]: scalar(e.target.value) } })} /></div></Field>
      </div>)}
      <div className="text-xs leading-6"><h3 className="font-medium">参数来源</h3>{Object.entries(action.parameter_bindings).map(([k, v]) => <p key={k} className="break-all text-muted-foreground">{k} ← {v}</p>)}<p className="mt-1 text-muted-foreground">实际调用遵循代码中的参数模型，编辑图谱不会创建可执行函数。</p></div>
      {tool?.arguments && <details className="text-xs"><summary className="cursor-pointer text-primary">查看代码参数</summary><div className="mt-2 space-y-2">{Object.entries(tool.arguments.properties || {}).map(([k, v]) => <p key={k} className="break-words leading-5"><span className="font-mono">{k}{tool.arguments?.required?.includes(k) ? " *" : ""}</span><br /><span className="text-muted-foreground">{v.description || v.type || "见工具定义"}</span></p>)}</div></details>}
    </>}
    {item.origin === "custom" && <Button variant="outline" className="w-full text-destructive" onClick={onDelete}><Trash2 className="size-4" />删除个人定义及其个人关联</Button>}
  </div>;
}
