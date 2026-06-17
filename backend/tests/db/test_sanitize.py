from app.db.sanitize import parse_jsonb, sanitize_json, sanitize_text


def test_sanitize_text_removes_nul_and_control_characters() -> None:
    assert sanitize_text("a\x00b\x01\nc\t") == "ab\nc\t"


def test_sanitize_json_recursively_cleans_strings() -> None:
    assert sanitize_json(
        {
            "title": "doc\x00name",
            "items": ["a\x02", {"nested": "b\x00"}],
        }
    ) == {
        "title": "docname",
        "items": ["a", {"nested": "b"}],
    }


def test_parse_jsonb_decodes_json_string_to_dict() -> None:
    # 回归：asyncpg 读回 jsonb 为字符串，旧代码直接喂给 pydantic dict 字段导致 500。
    assert parse_jsonb('{"tags": ["项目背景"], "source_message_id": "abc"}') == {
        "tags": ["项目背景"],
        "source_message_id": "abc",
    }


def test_parse_jsonb_passes_through_dict() -> None:
    value = {"finish_reason": "stop"}
    assert parse_jsonb(value) == value


def test_parse_jsonb_normalizes_empty_and_non_dict_to_none() -> None:
    assert parse_jsonb(None) is None
    assert parse_jsonb("[1, 2, 3]") is None  # 合法 JSON 但非对象
    assert parse_jsonb("42") is None
    assert parse_jsonb("not json") is None  # 解析失败兜底
    assert parse_jsonb(b'{"k": 1}') == {"k": 1}  # bytes 也支持

