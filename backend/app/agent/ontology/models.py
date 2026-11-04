from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = str


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.:-]{0,119}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    origin: Literal["platform", "discovered", "custom"] = "custom"


class Property(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    type: Literal["string", "integer", "double", "boolean", "datetime", "object", "array"] = "string"
    description: str = Field(default="", max_length=1000)
    is_identifier: bool = False


class EntityType(Definition):
    properties: list[Property] = Field(default_factory=list, max_length=100)
    color: str = Field(default="#14b8a6", pattern=r"^#[0-9a-fA-F]{6}$")
    parent: str | None = None


class Relationship(Definition):
    source_entity: str
    target_entity: str
    cardinality: Literal["one-to-one", "one-to-many", "many-to-one", "many-to-many"] = "one-to-many"


class Condition(BaseModel):
    """A bounded, declarative conjunction; never eval/import user supplied code."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    field: str = Field(pattern=r"^(entity|request|arguments)\.[a-zA-Z0-9_.]{1,100}$")
    op: Literal["exists", "eq", "in", "contains_all", "gte"] = "exists"
    value: Any = None
    when: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=8)
    message: str = Field(default="前置条件尚未满足", max_length=200)

    @model_validator(mode="after")
    def bounded_value(self):
        import math
        def simple(value):
            return value is None or isinstance(value, (bool, int)) or (isinstance(value, float) and math.isfinite(value)) or (isinstance(value, str) and len(value) <= 500)
        if self.op in {"in", "contains_all"}:
            if not isinstance(self.value, list) or len(self.value) > 30 or not all(simple(x) for x in self.value):
                raise ValueError("in / contains_all 的值必须是最多 30 项的简单列表")
        elif not simple(self.value):
            raise ValueError("该条件只接受简单值")
        if self.op == "gte" and (not isinstance(self.value, (int, float)) or isinstance(self.value, bool)):
            raise ValueError("大于等于条件需要数值")
        if any(not k.isidentifier() or len(k) > 100 or not simple(v) for k, v in self.when.items()):
            raise ValueError("条件参数名称或值无效")
        return self


class ActionBinding(Definition):
    tool_name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,119}$")
    relationship_id: str
    preconditions: list[Condition] = Field(default_factory=list, max_length=30)
    parameter_bindings: dict[str, str] = Field(default_factory=dict, max_length=40)
    output_entities: list[str] = Field(default_factory=list, max_length=12)
    # Descriptions/argument contracts are read from the live registry, not trusted from edits.


class DataBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    source: str = Field(max_length=200)
    fields: dict[str, str] = Field(default_factory=dict, max_length=100)


class Bindings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_bindings: list[DataBinding] = Field(default_factory=list, max_length=300)
    action_bindings: list[ActionBinding] = Field(default_factory=list, max_length=300)


class OntologySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str = Field(default="Agent-RS 功能图谱", min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    entity_types: list[EntityType] = Field(max_length=300)
    relationships: list[Relationship] = Field(max_length=600)
    bindings: Bindings

    @model_validator(mode="after")
    def references(self):
        def unique(items, label):
            keys = [x.id for x in items]
            if len(keys) != len(set(keys)):
                raise ValueError(f"{label} ID 重复")
            return set(keys)
        entities = unique(self.entity_types, "实体")
        relations = unique(self.relationships, "关系")
        unique(self.bindings.action_bindings, "动作")
        parents = {e.id: e.parent for e in self.entity_types}
        for e in self.entity_types:
            if len({p.name for p in e.properties}) != len(e.properties):
                raise ValueError(f"实体 {e.id} 的属性重复")
            seen = {e.id}
            parent = e.parent
            while parent:
                if parent not in entities or parent in seen:
                    raise ValueError("实体继承引用无效或存在循环")
                seen.add(parent)
                parent = parents[parent]
        for r in self.relationships:
            if r.source_entity not in entities or r.target_entity not in entities:
                raise ValueError(f"关系 {r.id} 引用了不存在的实体")
        for a in self.bindings.action_bindings:
            if a.relationship_id not in relations or any(e not in entities for e in a.output_entities):
                raise ValueError(f"动作 {a.id} 的关系或输出实体不存在")
        if any(b.entity_id not in entities for b in self.bindings.data_bindings):
            raise ValueError("数据绑定引用了不存在的实体")
        return self
