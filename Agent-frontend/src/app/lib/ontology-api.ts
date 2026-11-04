import { apiJson } from "./http";

export type Origin = "platform" | "discovered" | "custom";
export interface Definition { id: string; name: string; description: string; origin: Origin }
export interface EntityProperty { name: string; type: "string" | "integer" | "double" | "boolean" | "datetime" | "object" | "array"; description: string; is_identifier: boolean }
export interface EntityType extends Definition { properties: EntityProperty[]; color: string; parent: string | null }
export interface Relationship extends Definition { source_entity: string; target_entity: string; cardinality: "one-to-one" | "one-to-many" | "many-to-one" | "many-to-many" }
export interface Condition { field: string; op: "exists" | "eq" | "in" | "contains_all" | "gte"; value: unknown; when: Record<string, string | number | boolean>; message: string }
export interface ActionBinding extends Definition { tool_name: string; relationship_id: string; preconditions: Condition[]; parameter_bindings: Record<string, string>; output_entities: string[] }
export interface OntologySchema {
  schema_version: 1; name: string; description: string;
  entity_types: EntityType[]; relationships: Relationship[];
  bindings: { data_bindings: { entity_id: string; source: string; fields: Record<string, string> }[]; action_bindings: ActionBinding[] };
}
export interface CatalogTool { name: string; registered: boolean; enabled: boolean; description: string; source: string; arguments?: { properties?: Record<string, { type?: string; description?: string }>; required?: string[] } }
export interface OntologyDocument { schema: OntologySchema; tools: CatalogTool[]; version: number; catalog_revision: string; writable: boolean }
export const getOntology = (signal?: AbortSignal) => apiJson<OntologyDocument>("/ontology", { signal });
export const saveOntology = (schema: OntologySchema, document: OntologyDocument) => apiJson<{ version: number; catalog_revision: string }>("/ontology", {
  method: "POST", json: { schema, version: document.version, catalog_revision: document.catalog_revision },
});
export const exportOntology = () => apiJson<Record<string, unknown>>("/ontology/export");

const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Three-way reconciliation: keep local edits and newly discovered code, never silently overwrite a conflict. */
export function mergeOntology(latest: OntologySchema, base: OntologySchema, draft: OntologySchema): OntologySchema {
  function merge<T extends Definition>(remote: T[], old: T[], local: T[]): T[] {
    const result = new Map(remote.map(x => [x.id, x]));
    const before = new Map(old.map(x => [x.id, x]));
    const after = new Map(local.map(x => [x.id, x]));
    for (const id of new Set([...before.keys(), ...after.keys()])) {
      const previous = before.get(id), change = after.get(id), current = result.get(id);
      if (equal(change, previous)) continue;
      if (!equal(current, previous) && !equal(current, change)) throw new Error(`“${change?.name ?? previous?.name}”在其他页面或代码中也有修改。请先导出当前草稿，再撤销草稿并同步。`);
      if (change) result.set(id, change); else result.delete(id);
    }
    return [...result.values()];
  }
  return { ...latest,
    name: draft.name !== base.name ? draft.name : latest.name,
    description: draft.description !== base.description ? draft.description : latest.description,
    entity_types: merge(latest.entity_types, base.entity_types, draft.entity_types),
    relationships: merge(latest.relationships, base.relationships, draft.relationships),
    bindings: { ...latest.bindings, action_bindings: merge(latest.bindings.action_bindings, base.bindings.action_bindings, draft.bindings.action_bindings) },
  };
}

export function removeCustomDefinition(schema: OntologySchema, kind: "entity" | "relationship" | "action", id: string): OntologySchema {
  const collection = kind === "entity" ? schema.entity_types : kind === "relationship" ? schema.relationships : schema.bindings.action_bindings;
  if (collection.find(x => x.id === id)?.origin !== "custom") throw new Error("代码定义不能删除。");
  const relations = schema.relationships.filter(r => kind === "relationship" ? r.id === id : kind === "entity" && (r.source_entity === id || r.target_entity === id));
  const removedRelations = new Set(relations.map(r => r.id));
  const actions = schema.bindings.action_bindings.filter(a => (kind === "action" && a.id === id) || removedRelations.has(a.relationship_id) || (kind === "entity" && a.output_entities.includes(id)));
  if (relations.some(r => r.origin !== "custom") || actions.some(a => a.origin !== "custom") || (kind === "entity" && schema.entity_types.some(e => e.parent === id))) {
    throw new Error("该定义仍被基础关系、动作或子实体引用，请先解除引用。");
  }
  return { ...schema,
    entity_types: schema.entity_types.filter(e => !(kind === "entity" && e.id === id)),
    relationships: schema.relationships.filter(r => !removedRelations.has(r.id)),
    bindings: { data_bindings: schema.bindings.data_bindings.filter(b => !(kind === "entity" && b.entity_id === id)),
      action_bindings: schema.bindings.action_bindings.filter(a => !actions.includes(a)) },
  };
}

export function downloadOntology(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = filename;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
