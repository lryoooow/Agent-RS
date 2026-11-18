"""Compile the bounded JSON Schema subset accepted for external MCP tools."""
from __future__ import annotations

import json
import sys
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, create_model

RESERVED = {"user_id", "workspace_id", "auth_token", "conversation_id", "session_id"}
CONFIG = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
FIELD_NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,63}\Z")
KEYWORDS = {"type", "title", "description", "default", "enum", "const", "properties", "required",
            "additionalProperties", "items", "minLength", "maxLength", "minItems", "maxItems",
            "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "pattern", "anyOf",
            "$defs", "$ref", "$schema", "examples"}


def compile_jsonschema_to_pydantic(tool_name: str, json_schema: dict) -> type[BaseModel]:
    try:
        size = len(json.dumps(json_schema, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid tool schema") from exc
    if not isinstance(json_schema, dict) or size > 65536:
        raise ValueError("invalid or oversized tool schema")
    defs = json_schema.get("$defs", {})
    if not isinstance(defs, dict):
        raise ValueError("invalid schema definitions")
    nodes = 0

    def compile_type(schema, name, depth):
        nonlocal nodes
        nodes += 1
        if depth > 5 or nodes > 256 or not isinstance(schema, dict) or schema.keys() - KEYWORDS:
            raise ValueError("unsupported or excessively nested tool schema")
        if "$ref" in schema:
            ref = schema["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref[8:] not in defs or len(schema) != 1:
                raise ValueError("only local schema definitions are supported")
            return compile_type(defs[ref[8:]], name, depth + 1)
        if "anyOf" in schema:
            variants = schema["anyOf"]
            if not isinstance(variants, list) or not 1 <= len(variants) <= 8 or schema.keys() - {"anyOf", "title", "description", "default"}:
                raise ValueError("invalid schema alternatives")
            return Union[tuple(compile_type(v, name, depth + 1) for v in variants)]
        kind = schema.get("type")
        if isinstance(kind, list):
            if not 1 <= len(kind) <= 6:
                raise ValueError("invalid type union")
            return Union[tuple(compile_type({**schema, "type": k}, name, depth + 1) for k in kind)]
        if not isinstance(kind, str):
            raise ValueError("explicit tool parameter type required")
        common = {"type", "title", "description", "default", "examples", "$schema", "$defs"}
        by_kind = {
            "object": {"properties", "required", "additionalProperties"},
            "array": {"items", "minItems", "maxItems"},
            "string": {"minLength", "maxLength", "pattern", "const", "enum"},
            "integer": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "const", "enum"},
            "number": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "const", "enum"},
            "boolean": {"const", "enum"}, "null": {"const", "enum"},
        }
        if kind not in by_kind or schema.keys() - common - by_kind[kind] or ("enum" in schema and "const" in schema):
            raise ValueError("unsupported or ambiguous constraint for parameter type")
        if kind == "object":
            props, required = schema.get("properties", {}), schema.get("required", [])
            if (not isinstance(props, dict) or len(props) > 64 or not isinstance(required, list) or not all(isinstance(k, str) for k in required)
                    or len(set(required)) != len(required) or not set(required) <= props.keys()):
                raise ValueError("invalid object properties")
            if not isinstance(schema.get("additionalProperties", False), bool):
                raise ValueError("unbounded map parameters are unsupported")
            fields = {}
            for key, sub in props.items():
                if (not isinstance(key, str) or not FIELD_NAME.fullmatch(key) or key in RESERVED or hasattr(BaseModel, key) or key.startswith("model_")
                        or (depth > 0 and key in {"imagery_id", "document_id"})):
                    raise ValueError(f"reserved or invalid parameter: {key}")
                annotation = compile_type(sub, f"{name}_{key}", depth + 1)
                default = ... if key in required else None
                if key not in required and "default" in sub:
                    default = TypeAdapter(annotation).validate_python(sub["default"], strict=True)
                fields[key] = (annotation, Field(default=default, description=str(sub.get("description", ""))[:1000]))
            return create_model(name, __config__=CONFIG, **fields)
        if kind == "array":
            minimum, maximum = lengths(schema, "minItems", "maxItems", 100)
            item = compile_type(schema.get("items"), name + "_item", depth + 1)
            return Annotated[list[item], Field(min_length=minimum, max_length=maximum)]
        if kind == "string":
            minimum, maximum = lengths(schema, "minLength", "maxLength", 4096)
            annotation = Annotated[str, Field(min_length=minimum, max_length=maximum, pattern=schema.get("pattern"))]
        elif kind in ("number", "integer"):
            bounds = {}
            for key, target in (("minimum", "ge"), ("maximum", "le"), ("exclusiveMinimum", "gt"), ("exclusiveMaximum", "lt")):
                if key in schema:
                    value = schema[key]
                    if type(value) not in (int, float) or not -sys.float_info.max <= value <= sys.float_info.max:
                        raise ValueError("invalid numeric bounds")
                    bounds[target] = value
            if kind == "integer":
                bounds["ge"] = max(-(2**63), bounds.get("ge", -(2**63)))
                bounds["le"] = min(2**63 - 1, bounds.get("le", 2**63 - 1))
            annotation = Annotated[int if kind == "integer" else float, Field(allow_inf_nan=False, **bounds)]
        elif kind == "boolean":
            annotation = bool
        elif kind == "null":
            annotation = type(None)
        else:
            raise ValueError("explicit scalar, array, or object type required")
        if "enum" in schema or "const" in schema:
            values = schema.get("enum", [schema.get("const")])
            if not isinstance(values, list) or not 1 <= len(values) <= 100:
                raise ValueError("invalid enum")
            validator = TypeAdapter(annotation)
            for value in values:
                validator.validate_python(value, strict=True)
            # Literal alone can equate True with 1. Validate the declared JSON type first.
            return Annotated[Literal[tuple(values)], BeforeValidator(lambda v: validator.validate_python(v, strict=True))]
        return annotation

    if json_schema.get("type") != "object":
        raise ValueError("MCP tool input must be an object")
    return compile_type(json_schema, tool_name, 0)


def lengths(schema, lower, upper, cap):
    minimum, maximum = schema.get(lower, 0), schema.get(upper, cap)
    if type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= min(maximum, cap):
        raise ValueError("invalid length limits")
    return minimum, min(maximum, cap)
