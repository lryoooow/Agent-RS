"""从 Pydantic 参数模型生成 OpenAI function 定义（单一事实源）。

每个工具的参数契约只写在 Pydantic 模型里（Field 的 default/ge/pattern/description），
本模块负责把它翻译成发给模型的 `{"type": "function", ...}` 字典。
此前每个工具手写两份定义（Pydantic 模型 + function dict），字段一多必然漂移——
约束只在一边改了、另一边没跟，模型看到的与运行时校验的就不再是同一份契约。

## 归一化规则（Pydantic v2 JSON Schema → function calling 惯用形状）

1. **剥 `title`**：Pydantic 给每个字段生成的 `Imagery Id` 这类标题对模型没有信息量，
   只占 token。
2. **展开可空 `anyOf`**：`str | None` 生成 `anyOf: [{type: string}, {type: null}]`。
   收敛成 `{type: string}`——与旧手写 dict 的行为一致（可空性由描述文字表达，
   OpenAI function 参数的 null 语义各家实现不一，宁可不给）。
3. **定长元组转 draft-07 数组**：`tuple[float, float, float, float]` 生成
   `prefixItems`（JSON Schema 2020-12），不少兼容端点不认识；
   统一降级成 `items: {type: number} + minItems/maxItems`。
4. **不支持 `$ref`/`$defs`**：当前 13 个参数模型都是平铺字段，一旦将来有人
   引入嵌套模型，这里直接抛错提醒先扩展归一化器——静默把 `$ref` 发给
   兼容端点会得到模型看不懂的参数表。
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

_Arguments = TypeVar("_Arguments", bound=BaseModel)


def build_function_definition(
    name: str, description: str, argument_model: type[_Arguments]
) -> dict[str, Any]:
    """把 Pydantic 参数模型包装成 OpenAI function 定义。

    Args:
        name: 工具唯一名（与注册表 key 一致）。
        description: 给模型看的能力描述（何时调用、边界）。
        argument_model: 参数的 Pydantic 模型，约束与描述的唯一来源。
    """
    schema = argument_model.model_json_schema()
    if "$defs" in schema or "$ref" in schema:
        raise ValueError(
            f"{argument_model.__name__} 的 JSON Schema 含 $ref/$defs（嵌套模型），"
            "请在 schema_gen._normalize 里先扩展归一化逻辑再使用。"
        )
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": _normalize(schema),
        },
    }


def _normalize(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_normalize(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema or "$defs" in schema:
        raise ValueError("JSON Schema 含 $ref/$defs，未支持的嵌套结构")

    normalized = {key: _normalize(value) for key, value in schema.items() if key != "title"}

    normalized = _unwrap_nullable_anyof(normalized)
    normalized = _collapse_fixed_tuple(normalized)
    return normalized


def _unwrap_nullable_anyof(schema: dict[str, Any]) -> dict[str, Any]:
    """`anyOf: [T, {type: null}]` → `T`，保留 default/description 等兄弟键。"""
    variants = schema.get("anyOf")
    if not isinstance(variants, list) or len(variants) != 2:
        return schema
    null_variants = [v for v in variants if isinstance(v, dict) and v.get("type") == "null"]
    if len(null_variants) != 1:
        return schema
    concrete = next(v for v in variants if v is not null_variants[0])
    if not isinstance(concrete, dict):
        return schema
    merged = {k: v for k, v in schema.items() if k != "anyOf"}
    merged.update(concrete)
    return merged


def _collapse_fixed_tuple(schema: dict[str, Any]) -> dict[str, Any]:
    """定长 `prefixItems` → `items`（draft-07 形状），兼容不识 2020-12 的端点。

    仅当所有 prefixItems 子模式完全一致时才收敛（当前 tuple[float×4] 满足）；
    异构元组保持原样，宁可多占几个 token 也不改变语义。
    """
    prefix = schema.get("prefixItems")
    if not isinstance(prefix, list) or not prefix:
        return schema
    first = prefix[0]
    if any(item != first for item in prefix[1:]):
        return schema
    merged = {k: v for k, v in schema.items() if k != "prefixItems"}
    merged.setdefault("items", first)
    return merged
