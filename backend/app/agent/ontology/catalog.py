"""Reconcile a checked-in semantic map with real, currently registered tools.

Source discovery uses AST only. Finding a function never imports or executes it.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from .models import ActionBinding, EntityType, OntologySchema, Property, Relationship

SCHEMA_PATH = Path(__file__).with_name("ontology_schema.json")
TOOLS_ROOT = Path(__file__).parents[1] / "tools"
SCHEMAS_ROOT = Path(__file__).parents[2] / "schemas"


def load_schema(path: Path = SCHEMA_PATH) -> OntologySchema:
    return OntologySchema.model_validate_json(path.read_text(encoding="utf-8-sig"))


def _property(name: str, value: dict) -> Property:
    variants = [v for v in value.get("anyOf", []) if v.get("type") != "null"]
    shape = variants[0] if len(variants) == 1 else value
    kind = shape.get("type", "object" if "$ref" in shape else "string")
    if shape.get("format") == "date-time":
        kind = "datetime"
    if kind == "number":
        kind = "double"
    if kind not in {"string", "integer", "double", "boolean", "datetime", "object", "array"}:
        kind = "string"
    return Property(name=name, type=kind, description=str(value.get("description", ""))[:1000])


def source_candidates(root: Path = TOOLS_ROOT) -> list[dict]:
    candidates = []
    for path in sorted(root.glob("*/schema.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            if any(isinstance(t, ast.Name) and t.id.endswith("_TOOL_NAME") for t in node.targets):
                name = node.value.value
                if name.isidentifier() and len(name) <= 120:
                    candidates.append({"name": name, "source": f"tools/{path.parent.name}/schema.py"})
    return candidates


def discover_schemas(root: Path = SCHEMAS_ROOT) -> list[EntityType]:
    """New Pydantic/TypedDict declarations are visible without importing modules."""
    found = []
    for path in sorted(root.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not any(ast.unparse(b).split(".")[-1] in {"BaseModel", "TypedDict"} for b in node.bases):
                continue
            # Operational secrets/configuration are not business entities.
            if any(token in node.name.lower() for token in ("config", "secret", "credential", "error", "usage")):
                continue
            props = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id != "model_config":
                    annotation = ast.unparse(item.annotation)
                    kind = "array" if "list[" in annotation or "tuple[" in annotation else "object" if "dict[" in annotation else "boolean" if annotation == "bool" else "integer" if annotation == "int" else "double" if annotation == "float" else "string"
                    props.append(Property(name=item.target.id, type=kind))
            found.append(EntityType(id=f"schema.{path.stem}.{node.name}", name=node.name,
                description=f"代码定义：schemas/{path.name}:{node.lineno}", origin="discovered", properties=props, color="#64748b"))
    return found


def build_catalog(registry=None, *, discover: bool = True) -> tuple[OntologySchema, list[dict], str]:
    if registry is None:
        from app.agent.tool_registry import TOOLS
        registry = TOOLS
    schema = load_schema()
    by_tool = {a.tool_name: a for a in schema.bindings.action_bindings}
    known_entities = {e.id for e in schema.entity_types}
    tools = []
    for name, tool in registry.items():
        args = tool.argument_model.model_json_schema()
        # Arguments are generated from code and deliberately have no duplicated defaults.
        eid = f"arguments.{name}"
        schema.entity_types.append(EntityType(id=eid, name=f"{name} 参数", origin="discovered",
            description="自动读取当前工具的参数模型", color="#64748b",
            properties=[_property(k, v) for k, v in args.get("properties", {}).items()]))
        if name not in by_tool:
            source = {"imagery": "imagery", "document": "document", "conversation": "conversation"}.get(tool.resource_kind, "request")
            rid = f"rel_{name}"
            schema.relationships.append(Relationship(id=rid, name=name, source_entity=source, target_entity="tool_execution", origin="discovered",
                description="从工具注册表发现；输出语义可在图谱中补充。"))
            schema.bindings.action_bindings.append(ActionBinding(id=f"action_{name}", name=name, tool_name=name,
                relationship_id=rid, output_entities=["tool_execution"], origin="discovered"))
        schema.relationships.append(Relationship(id=f"args_{name}", name="配置参数", source_entity=eid,
            target_entity=next(r.source_entity for r in schema.relationships if r.id == next(a.relationship_id for a in schema.bindings.action_bindings if a.tool_name == name)), origin="discovered"))
        tools.append({"name": name, "registered": True, "enabled": tool.is_enabled(), "resource_kind": tool.resource_kind,
            "agent_name": tool.agent_name, "scope": tool.scope, "arguments": args,
            "description": tool.definition.get("function", {}).get("description", ""),
            "source": f"{tool.runner.__module__}.{tool.runner.__name__}"})
    if discover:
        for item in source_candidates():
            if item["name"] not in registry:
                tools.append({**item, "registered": False, "enabled": False, "description": "源码已发现，尚未注册到当前进程；注册并重新加载后可执行。"})
        for entity in discover_schemas():
            if entity.id not in known_entities:
                schema.entity_types.append(entity)
        # Read declarative presets without importing the agent framework or running code.
        path = Path(__file__).parents[1] / "engine" / "flows.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            presets = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "PRESET_FLOWS")
            labels = {"inspect_index_report": "质检 → 指数 → 报告", "mask_segment_report": "云掩膜 → 地物分类 → 报告", "detect_report": "目标检测 → 报告"}
            for name, agents in presets.items():
                eid = f"workflow.{name}"
                schema.entity_types.append(EntityType(id=eid, name=labels.get(name, name), origin="discovered", color="#f59e0b",
                    description="固定作业流程；仅用户明确要求全部步骤时选择。节点顺序：" + " → ".join(agents),
                    properties=[Property(name="flow_name", description=name, is_identifier=True), Property(name="agents", type="array", description=" → ".join(agents))]))
                schema.relationships.append(Relationship(id=f"workflow_{name}", name="规划作业", source_entity="request", target_entity=eid, origin="discovered"))
                schema.relationships.append(Relationship(id=f"workflow_runs_{name}", name="顺序执行", source_entity=eid, target_entity="tool_execution", origin="discovered"))
        except (OSError, SyntaxError, ValueError, StopIteration):
            pass
    schema = OntologySchema.model_validate(schema.model_dump())
    revision = hashlib.sha256(json.dumps({"schema": schema.model_dump(), "tools": tools}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    return schema, tools, revision


def merge_custom(base: OntologySchema, overlay: dict) -> OntologySchema:
    data = base.model_dump()
    for section in ("entity_types", "relationships"):
        indexed = {x["id"]: x for x in data[section]}
        for key, value in overlay.get(section, {}).items():
            if value is not None:
                indexed[key] = value
        data[section] = list(indexed.values())
    indexed = {a["id"]: a for a in data["bindings"]["action_bindings"]}
    for key, value in overlay.get("action_bindings", {}).items():
        if value is not None:
            indexed[key] = value
    data["bindings"]["action_bindings"] = list(indexed.values())
    for key in ("name", "description"):
        if key in overlay:
            data[key] = overlay[key]
    # A deleted code declaration may still be referenced by a personal definition.
    # Saved dependencies are retained as custom rather than silently losing the edit.
    existing = {e["id"] for e in data["entity_types"]}
    for e in overlay.get("dependencies", []):
        if e["id"] not in existing:
            data["entity_types"].append({**e, "origin": "custom"})
    existing_relations = {r["id"] for r in data["relationships"]}
    required_relations = {a["relationship_id"] for a in data["bindings"]["action_bindings"]}
    for r in overlay.get("relationship_dependencies", []):
        if r["id"] not in existing_relations and r["id"] in required_relations:
            data["relationships"].append({**r, "origin": "custom"})
    return OntologySchema.model_validate(data)


def make_overlay(base: OntologySchema, edited: OntologySchema) -> dict:
    original, new = base.model_dump(), edited.model_dump()
    if original["bindings"]["data_bindings"] != new["bindings"]["data_bindings"]:
        raise ValueError("代码数据来源由平台管理；请在实体属性、关系和动作中编辑个人语义定义。")
    overlay = {"name": new["name"], "description": new["description"]}
    for section in ("entity_types", "relationships", "action_bindings"):
        before = original["bindings"][section] if section == "action_bindings" else original[section]
        after = new["bindings"][section] if section == "action_bindings" else new[section]
        old = {x["id"]: x for x in before}
        current = {x["id"]: x for x in after}
        if not old.keys() <= current.keys():
            raise ValueError("代码同步的基础定义不能删除；可以编辑说明或删除自己新增的定义。")
        overlay[section] = {k: {**v, "origin": old[k]["origin"] if k in old else "custom"} for k, v in current.items() if v != old.get(k)}
    overlay["dependencies"] = new["entity_types"]
    overlay["relationship_dependencies"] = new["relationships"]
    return overlay


def to_playground(schema: OntologySchema) -> dict:
    actions = schema.bindings.action_bindings
    return {"name": schema.name, "description": schema.description,
        "entityTypes": [{"id": e.id, "name": e.name, "description": e.description, "color": e.color, "icon": "◈",
            "properties": [{"name": p.name, "type": "string" if p.type in {"object", "array"} else p.type,
                "isIdentifier": p.is_identifier, "description": p.description + (f"（原类型：{p.type}，展示为 JSON 文本）" if p.type in {"object", "array"} else "")} for p in e.properties]} for e in schema.entity_types],
        "relationships": [{"id": r.id, "name": r.name, "from": r.source_entity, "to": r.target_entity,
            "cardinality": r.cardinality, "description": r.description + "\n" + "\n".join(
                f"工具：{a.tool_name}；前置条件：" + "；".join(c.message for c in a.preconditions) for a in actions if a.relationship_id == r.id)} for r in schema.relationships]}
