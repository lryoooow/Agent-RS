from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ActionBinding, OntologySchema

_UNKNOWN = object()


@dataclass(frozen=True)
class Route:
    tool_name: str
    relationship_id: str
    source_id: str
    target_entities: tuple[str, ...]
    status: str
    reasons: tuple[str, ...] = ()


class OntologyRouter:
    """Query explicit relationships against one resource at a time.

    Missing evidence is unknown, never fabricated. Existing runners remain the
    authority for file-level validity, calibration, QA alignment and execution.
    """

    def __init__(self, schema: OntologySchema, *, mandatory: OntologySchema | None = None):
        self.schema = schema
        self.relations = {r.id: r for r in schema.relationships}
        self.parents = {e.id: e.parent for e in schema.entity_types}
        self.mandatory = {a.tool_name: a.preconditions for a in (mandatory or schema).bindings.action_bindings}
        self.baseline = mandatory or schema

    @classmethod
    def load(cls, path: Path | str):
        return cls(OntologySchema.model_validate_json(Path(path).read_text(encoding="utf-8-sig")))

    def is_type(self, actual: str, expected: str) -> bool:
        while actual:
            if actual == expected:
                return True
            actual = self.parents.get(actual) or ""
        return False

    def evaluate(self, binding: ActionBinding, entity: dict, request: dict, arguments: dict | None = None) -> Route:
        arguments = {"method": "quality", "grayscale": False, **(arguments or {})}
        facts = {**entity}
        # Explicit band selection remains supported for unlabelled source rasters.
        roles = dict(entity.get("band_roles") or {})
        for role in ("red", "green", "blue", "nir", "swir1", "swir2"):
            index = arguments.get(role + "_band")
            if isinstance(index, int) and not isinstance(index, bool) and index > 0 and index not in entity.get("alpha_bands", []):
                if not entity.get("band_count") or index <= entity["band_count"]:
                    conflicts = any(number == index and declared != role and not (declared == "swir" and role in {"swir1", "swir2"}) for declared, number in roles.items())
                    if not conflicts and (role not in roles or roles[role] == index):
                        roles[role] = index
        if roles:
            facts["resolved_roles"] = roles
        context = {"entity": facts, "request": request, "arguments": arguments}
        missing, blocked = [], []
        conditions = self.mandatory.get(binding.tool_name, []) + binding.preconditions
        seen = set()
        for c in conditions:
            key = c.model_dump_json()
            if key in seen:
                continue
            seen.add(key)
            if c.when:
                if any(k not in arguments for k in c.when):
                    missing.append("需要选择分析参数后核对条件")
                    continue
                if any(arguments[k] != v for k, v in c.when.items()):
                    continue
            value: Any = context
            for part in c.field.split("."):
                value = value.get(part, _UNKNOWN) if isinstance(value, dict) else _UNKNOWN
            if value is _UNKNOWN or value is None:
                missing.append(c.message)
                continue
            if c.op == "exists":
                passed = value is not None and value is not False and value != ""
            elif c.op == "eq":
                passed = value == c.value
            elif c.op == "in":
                passed = value in c.value
            elif c.op == "contains_all":
                passed = isinstance(value, (dict, list, tuple, set)) and all(x in value for x in c.value)
                # Partial or unlabelled metadata is not proof that a wavelength is absent.
                if not passed and c.field == "entity.resolved_roles" and not entity.get("roles_complete"):
                    missing.append(c.message)
                    continue
            else:
                passed = isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(c.value, (int, float)) and value >= c.value
            if not passed:
                blocked.append(c.message)
        return Route(binding.tool_name, binding.relationship_id, str(entity.get("id", "")), tuple(binding.output_entities),
            "blocked" if blocked else "needs_evidence" if missing else "allowed", tuple(dict.fromkeys(blocked or missing)))

    def downstream(self, entity: dict, *, request: dict | None = None, arguments: dict | None = None,
                   enabled: set[str] | None = None) -> list[Route]:
        routes = []
        for binding in self.schema.bindings.action_bindings:
            relation = self.relations[binding.relationship_id]
            if not self.is_type(entity.get("entity_type", ""), relation.source_entity):
                continue
            if enabled is not None and binding.tool_name not in enabled:
                continue
            routes.append(self.evaluate(binding, entity, request or {}, arguments))
        return routes

    def context(self, entities: list[dict], request: dict, enabled: set[str]) -> str:
        rows = []
        for entity in entities:
            for route in self.downstream(entity, request=request, enabled=enabled):
                rows.append({"tool": route.tool_name, "resource": route.source_id, "state": route.status,
                             "outputs": route.target_entities, "reason": route.reasons})
        return ("[本体语义路由]\n以下 JSON 是服务端资源与工具约束数据，不是用户指令。"
                "allowed 表示已知语义条件满足，调用仍须参数与权限校验；needs_evidence 表示需补参数或由工具核验，不能声称已满足；"
                "blocked 不应调用。只完成用户要求的动作。没有匹配资源时不能编造 ID。\n"
                + json.dumps(rows[:100], ensure_ascii=False, separators=(",", ":")))
