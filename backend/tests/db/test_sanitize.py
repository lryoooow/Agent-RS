from app.lib.db.sanitize import sanitize_json, sanitize_text


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
