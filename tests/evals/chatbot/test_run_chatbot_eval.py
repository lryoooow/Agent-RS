import importlib.util
import time
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("run_chatbot_eval.py")
SPEC = importlib.util.spec_from_file_location("run_chatbot_eval", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_build_metrics_preserves_first_status_and_derives_stream_metrics() -> None:
    metrics = runner.build_metrics(
        first_status_ms=20,
        first_delta_ms=120,
        total_ms=420,
        chunk_count=3,
    )

    assert metrics == {
        "first_status_ms": 20,
        "first_delta_ms": 120,
        "total_ms": 420,
        "chunk_count": 3,
        "first_delta_after_status_ms": 100,
        "visible_stream_ms": 300,
        "avg_visible_chunk_gap_ms": 100,
    }


def test_parse_sse_response_records_status_delta_and_content() -> None:
    lines = [
        "event: analysis_status\n",
        'data: {"status": "analyzing"}\n',
        "\n",
        "event: analysis_status\n",
        'data: {"status": "complete"}\n',
        "\n",
        "event: delta\n",
        'data: {"content": "你"}\n',
        "\n",
        "event: delta\n",
        'data: {"content": "好"}\n',
        "\n",
        "event: done\n",
        'data: {"finish_reason": "stop"}\n',
        "\n",
    ]
    response = [line.encode("utf-8") for line in lines]

    parsed = runner.parse_sse_response(response, time.perf_counter())

    assert parsed["event_order"] == ["analysis_status", "analysis_status", "delta", "delta", "done"]
    assert parsed["statuses"] == ["analyzing", "complete"]
    assert parsed["content"] == "你好"
    assert parsed["chunk_count"] == 2
    assert parsed["done"] == {"finish_reason": "stop"}
    assert parsed["first_status_ms"] is not None
    assert parsed["first_delta_ms"] is not None


def test_forbidden_patterns_ignore_redacted_secret_placeholders() -> None:
    content = "示例：api_key=[REDACTED]，也可以写成 sk-*** 或 sk-xxxxxxxxxx 作为占位符。"

    assert runner.find_forbidden_patterns(content, [r"api[_ -]?key\s*[:=]\s*[^\s,;]+"]) == []
    assert runner.find_forbidden_terms(content, ["sk-", "api_key="]) == []
    assert runner.find_forbidden_patterns('ai_api_key = os.getenv("AI_API_KEY")', []) == []
    assert runner.find_forbidden_patterns("const aiApiKey = process.env.AI_API_KEY;", []) == []
    assert runner.find_forbidden_patterns("api_key=real_secret_123456", [r"api[_ -]?key\s*[:=]\s*[^\s,;]+"])


def test_evaluate_response_allows_expected_english() -> None:
    case = {
        "expected": {"language": "en", "format": "markdown"},
        "must_include": ["context"],
        "must_include_any": [],
        "must_not_include": ["system prompt"],
        "forbidden_patterns": [],
        "evaluation_type": "hybrid",
        "manual_check": True,
    }
    run_data = {
        "content": "Context management keeps relevant conversation information available.",
        "errors": [],
    }

    result = runner.evaluate_response(case, 200, run_data)

    assert "language_not_zh" not in result["failures"]
    assert "language_not_en" not in result["failures"]


def test_evaluate_response_warns_done_error_after_visible_stream_without_failure() -> None:
    case = {
        "expected": {
            "language": "zh",
            "format": "plain",
            "stream": True,
            "status_chain": runner.STATUS_CHAIN,
        },
        "must_include": ["你好"],
        "must_include_any": [],
        "must_not_include": [],
        "forbidden_patterns": [],
        "evaluation_type": "hybrid",
        "manual_check": True,
    }
    run_data = {
        "content": "你好",
        "errors": [],
        "statuses": runner.STATUS_CHAIN,
        "event_order": ["analysis_status", "analysis_status", "analysis_status", "analysis_status", "delta", "done"],
        "chunk_count": 1,
        "done": {
            "finish_reason": "error",
            "error": {"code": "PROVIDER_ERROR", "message": "AI provider request failed."},
        },
    }

    result = runner.evaluate_response(case, 200, run_data)

    assert "provider_or_stream_error" not in result["failures"]
    assert "stream_done_with_error" in result["warnings"]
