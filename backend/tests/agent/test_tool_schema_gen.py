"""schema_gen：Pydantic 参数模型 → OpenAI function 定义的契约测试。

守住三条线：
1. 注册表里每个工具的 definition 由参数模型派生，name 与注册 key 一致；
2. 生成形状符合 function calling 惯例（object/additionalProperties/required）；
3. 归一化规则（剥 title、展开可空 anyOf、定长元组降级）不回退。
"""

from __future__ import annotations

import pytest

from app.agent.tool_registry import TOOLS
from app.agent.tools.schema_gen import build_function_definition


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_registry_definitions_derived_from_argument_models():
    """每个注册工具的 definition.name 必须等于注册 key，且与参数模型同源。"""
    for key, tool in TOOLS.items():
        assert tool.definition["type"] == "function"
        assert tool.definition["function"]["name"] == key
        # 同一模型再生成一次必须完全一致（纯函数，无隐藏状态）。
        regenerated = build_function_definition(
            key, tool.definition["function"]["description"], tool.argument_model
        )
        assert regenerated == tool.definition


def test_definitions_have_function_calling_shape():
    for key, tool in TOOLS.items():
        params = tool.definition["function"]["parameters"]
        assert params["type"] == "object", key
        assert params["additionalProperties"] is False, key
        described = set(tool.argument_model.model_fields)
        assert set(params["properties"]) == described, key
        # Pydantic 只把无默认值的字段列进 required——这与手写时代的语义一致。
        optional = {
            name
            for name, field in tool.argument_model.model_fields.items()
            if field.is_required()
        }
        assert set(params.get("required", [])) == optional, key
        assert tool.definition["function"]["description"].strip(), key


def test_normalization_rules_apply():
    """剥 title、展开可空 anyOf、定长元组转 items。"""
    for tool in TOOLS.values():
        for node in _walk(tool.definition):
            assert "title" not in node
            assert "$ref" not in node
            assert "$defs" not in node

    segment = TOOLS["segment_landcover"].definition["function"]["parameters"]["properties"]
    for box in ("bbox", "pixel_bbox"):
        schema = segment[box]
        assert schema["type"] == "array", box
        assert schema["items"] == {"type": "number"}, box
        assert schema["minItems"] == 4 and schema["maxItems"] == 4, box

    clip = TOOLS["clip_reproject_raster"].definition["function"]["parameters"]["properties"]
    assert clip["dst_crs"]["type"] == "string"
    assert "anyOf" not in clip["dst_crs"]


@pytest.mark.parametrize(
    ("tool_name", "field", "expected"),
    [
        ("calculate_ndvi", "red_band", {"default": 3, "minimum": 1}),
        ("calculate_ndvi", "imagery_id", {"pattern": "^[a-f0-9]{12}$"}),
        ("look_at_location", "zoom", {"minimum": 0, "maximum": 20}),
        ("detect_objects", "score_threshold", {"default": 0.5, "minimum": 0.0, "maximum": 1.0}),
    ],
)
def test_field_constraints_survive_generation(tool_name, field, expected):
    schema = TOOLS[tool_name].definition["function"]["parameters"]["properties"][field]
    for key, value in expected.items():
        assert schema.get(key) == value, (tool_name, field, key)


def test_literal_enum_preserved():
    props = TOOLS["calculate_spectral_index"].definition["function"]["parameters"]["properties"]
    assert props["index_type"]["enum"] == [
        "ndwi", "mndwi", "ndbi", "evi", "savi", "gndvi", "ndmi", "nbr", "msavi", "bsi",
    ]
    composite = TOOLS["render_band_composite"].definition["function"]["parameters"]["properties"]
    assert composite["mode"]["enum"] == ["true_color", "false_color", "custom"]


def test_report_tool_has_no_required_fields():
    params = TOOLS["generate_report"].definition["function"]["parameters"]
    assert params.get("required", []) == []
