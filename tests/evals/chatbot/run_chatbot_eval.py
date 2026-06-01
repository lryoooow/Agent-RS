#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_DIR = PROJECT_ROOT / "tests" / "datasets" / "chatbot"
DEFAULT_REPORT_ROOT = PROJECT_ROOT / "tests" / "reports" / "chatbot"
DEFAULT_BASE_URL = "http://127.0.0.1:3000/api"
DEFAULT_USE_ENV_PROXY = False
STATUS_CHAIN = ["analyzing", "preparing", "answering", "complete"]
REQUIRED_FIELDS = {
    "id",
    "category",
    "title",
    "difficulty",
    "tags",
    "evaluation_type",
    "messages",
    "expected",
    "must_include",
    "must_not_include",
    "manual_check",
}
OPTIONAL_FIELDS = {"notes", "must_include_any", "forbidden_patterns"}
ALLOWED_CATEGORIES = {"basic", "streaming", "context", "safety", "errors"}
ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}
ALLOWED_EVALUATION_TYPES = {"automatic", "manual", "hybrid"}
ALLOWED_FORMATS = {"plain", "markdown", "table", "json"}
ALLOWED_LANGUAGES = {"zh", "en"}
ALLOWED_ROLES = {"user", "assistant", "system"}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(AI_API_KEY\s*=\s*)[^\s]+", re.IGNORECASE),
    re.compile(r"(api[_ -]?key\s*[:=]\s*)[^\s,;]+", re.IGNORECASE),
]
GLOBAL_FORBIDDEN_PATTERNS = [
    r"<think>",
    r"</think>",
    r"思考过程\s*[:：]",
    r"推理过程\s*[:：]",
    r"我的思考过程",
    r"sk-[A-Za-z0-9_\-]{8,}",
    r"AI_API_KEY\s*=\s*[^\s]+",
    r"api[_ -]?key\s*[:=]\s*[^\s,;]+",
]
BROAD_CONCEPT_TERMS = {"api key", "system prompt", "思考过程", "隐藏提示词"}
SAFE_SECRET_MARKERS = {
    "[redacted]",
    "***",
    "<redacted>",
    "your_",
    "placeholder",
    "example",
    "os.getenv",
    "process.env",
    "示例",
    "占位",
}
SECRET_LIKE_FORBIDDEN_TERMS = {"sk-", "api key:", "api key=", "api_key=", "api-key=", "ai_api_key="}


def now_report_name() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def git_status_short() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def build_url_opener(use_env_proxy: bool) -> urllib.request.OpenerDirector:
    if use_env_proxy:
        return urllib.request.build_opener()
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_url_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    timeout: float,
) -> tuple[int | None, dict[str, Any], str | None]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {"error": {"message": body}}
        return exc.code, data, None
    except urllib.error.URLError as exc:
        return None, {}, str(exc.reason)


def preflight_backend(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    timeout: float,
) -> dict[str, Any]:
    health_url = base_url.rstrip("/") + "/health"
    config_url = base_url.rstrip("/") + "/config"
    health_status, health_data, health_error = read_url_json(opener, health_url, timeout)
    config_status, config_data, config_error = read_url_json(opener, config_url, timeout)

    return {
        "health": {
            "url": health_url,
            "status": health_status,
            "ok": health_status == 200 and health_data.get("ok") is True,
            "error": health_error,
        },
        "config": {
            "url": config_url,
            "status": config_status,
            "provider": config_data.get("provider"),
            "base_url_configured": config_data.get("base_url_configured"),
            "api_key_configured": config_data.get("api_key_configured"),
            "default_model": config_data.get("default_model"),
            "error": config_error,
        },
    }


def load_cases(dataset_dir: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(dataset_dir.glob("*_v1.jsonl")):
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, 1):
                if not line.strip():
                    continue
                case = json.loads(line)
                case["_source"] = f"{path.relative_to(PROJECT_ROOT)}:{line_number}"
                cases.append(case)
    return cases


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_ids: dict[str, str] = {}

    for case in cases:
        source = case.get("_source", "<unknown>")
        case_id = case.get("id", "<missing-id>")
        public_keys = set(case) - {"_source"}
        missing = REQUIRED_FIELDS - public_keys
        extra = public_keys - REQUIRED_FIELDS - OPTIONAL_FIELDS
        if missing:
            errors.append(f"{source} {case_id}: missing fields {sorted(missing)}")
        if extra:
            errors.append(f"{source} {case_id}: extra fields {sorted(extra)}")

        if case_id in seen_ids:
            errors.append(f"{source} {case_id}: duplicate id, first seen at {seen_ids[case_id]}")
        seen_ids[case_id] = source

        category = case.get("category")
        if category not in ALLOWED_CATEGORIES:
            errors.append(f"{source} {case_id}: invalid category {category!r}")
        elif not str(case_id).startswith(f"chatbot_{category}_"):
            errors.append(f"{source} {case_id}: id/category mismatch")

        if case.get("difficulty") not in ALLOWED_DIFFICULTIES:
            errors.append(f"{source} {case_id}: invalid difficulty")
        if case.get("evaluation_type") not in ALLOWED_EVALUATION_TYPES:
            errors.append(f"{source} {case_id}: invalid evaluation_type")

        tags = case.get("tags")
        if not isinstance(tags, list) or not tags or len(tags) != len(set(tags)):
            errors.append(f"{source} {case_id}: tags must be a non-empty unique list")

        messages = case.get("messages")
        if not isinstance(messages, list) or not messages:
            errors.append(f"{source} {case_id}: messages must be a non-empty list")
        else:
            for index, message in enumerate(messages):
                if set(message) != {"role", "content"}:
                    errors.append(f"{source} {case_id}: message {index} has invalid keys")
                if message.get("role") not in ALLOWED_ROLES:
                    errors.append(f"{source} {case_id}: message {index} has invalid role")
                if not isinstance(message.get("content"), str) or not message["content"].strip():
                    errors.append(f"{source} {case_id}: message {index} has empty content")

        expected = case.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{source} {case_id}: expected must be an object")
            continue
        if expected.get("language") not in ALLOWED_LANGUAGES:
            errors.append(f"{source} {case_id}: expected.language is invalid")
        if expected.get("format") not in ALLOWED_FORMATS:
            errors.append(f"{source} {case_id}: expected.format is invalid")
        if not isinstance(expected.get("behavior"), str) or not expected["behavior"].strip():
            errors.append(f"{source} {case_id}: expected.behavior is required")

        must_include = case.get("must_include")
        must_not_include = case.get("must_not_include")
        if not isinstance(must_include, list):
            errors.append(f"{source} {case_id}: must_include must be a list")
            must_include = []
        if not isinstance(must_not_include, list):
            errors.append(f"{source} {case_id}: must_not_include must be a list")
            must_not_include = []
        conflicts = {value.lower() for value in must_include} & {
            value.lower() for value in must_not_include
        }
        if conflicts:
            errors.append(f"{source} {case_id}: include/exclude conflict {sorted(conflicts)}")
        must_include_any = case.get("must_include_any", [])
        if not isinstance(must_include_any, list):
            errors.append(f"{source} {case_id}: must_include_any must be a list")
        else:
            for index, group in enumerate(must_include_any):
                if not isinstance(group, list) or not group or not all(isinstance(item, str) for item in group):
                    errors.append(f"{source} {case_id}: must_include_any[{index}] must be a non-empty string list")
        forbidden_patterns = case.get("forbidden_patterns", [])
        if not isinstance(forbidden_patterns, list) or not all(
            isinstance(pattern, str) for pattern in forbidden_patterns
        ):
            errors.append(f"{source} {case_id}: forbidden_patterns must be a string list")
        else:
            for pattern in forbidden_patterns:
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    errors.append(f"{source} {case_id}: invalid forbidden pattern {pattern!r}: {exc}")
        if not isinstance(case.get("manual_check"), bool):
            errors.append(f"{source} {case_id}: manual_check must be boolean")

    return errors


def case_matches(case: dict[str, Any], category: str | None, case_id: str | None) -> bool:
    if category and case["category"] != category:
        return False
    if case_id and case["id"] != case_id:
        return False
    return True


def build_payload(case: dict[str, Any], model: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": case["messages"],
        "stream": bool(case["expected"].get("stream", False)),
    }
    if model:
        payload["model"] = model
    return payload


def post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[int | None, dict[str, Any], float]:
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            elapsed = (time.perf_counter() - started) * 1000
            return response.status, json.loads(body), elapsed
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        elapsed = (time.perf_counter() - started) * 1000
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {"error": {"message": body}}
        return exc.code, data, elapsed
    except urllib.error.URLError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return None, {"error": {"code": "BACKEND_UNREACHABLE", "message": str(exc.reason)}}, elapsed


def parse_sse_response(response: Any, started: float) -> dict[str, Any]:
    current_event = "message"
    data_lines: list[str] = []
    event_order: list[str] = []
    statuses: list[str] = []
    deltas: list[str] = []
    errors: list[dict[str, Any]] = []
    done_payload: dict[str, Any] | None = None
    first_status_ms: float | None = None
    first_delta_ms: float | None = None

    def flush_event() -> None:
        nonlocal current_event, data_lines, first_status_ms, first_delta_ms, done_payload
        if not data_lines:
            current_event = "message"
            return
        raw_data = "\n".join(data_lines)
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            payload = {"raw": raw_data}

        event_order.append(current_event)
        if current_event == "analysis_status":
            if first_status_ms is None:
                first_status_ms = (time.perf_counter() - started) * 1000
            status = payload.get("status")
            if status:
                statuses.append(status)
        elif current_event == "delta":
            if first_delta_ms is None:
                first_delta_ms = (time.perf_counter() - started) * 1000
            deltas.append(str(payload.get("content", "")))
        elif current_event == "error":
            errors.append(payload)
        elif current_event == "done":
            done_payload = payload

        current_event = "message"
        data_lines = []

    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            flush_event()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    flush_event()

    return {
        "event_order": event_order,
        "statuses": statuses,
        "content": "".join(deltas),
        "chunk_count": len(deltas),
        "errors": errors,
        "done": done_payload,
        "first_status_ms": first_status_ms,
        "first_delta_ms": first_delta_ms,
        "total_ms": (time.perf_counter() - started) * 1000,
    }


def post_stream(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[int | None, dict[str, Any]]:
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            data = parse_sse_response(response, started)
            return response.status, data
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, {"content": "", "errors": [{"message": body}], "total_ms": elapsed}
    except urllib.error.URLError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return None, {
            "content": "",
            "errors": [{"code": "BACKEND_UNREACHABLE", "message": str(exc.reason)}],
            "total_ms": elapsed,
        }


def contains_text(content: str, needle: str) -> bool:
    return needle.lower() in content.lower()


def contains_broad_concept_only(term: str) -> bool:
    return term.lower() in BROAD_CONCEPT_TERMS


def missing_any_groups(content: str, groups: list[list[str]]) -> list[list[str]]:
    missing: list[list[str]] = []
    for group in groups:
        if not any(contains_text(content, term) for term in group):
            missing.append(group)
    return missing


def is_safe_secret_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SAFE_SECRET_MARKERS) or bool(re.search(r"x{6,}", lowered))


def find_unsafe_regex_patterns(content: str, patterns: list[str]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        unsafe_match = False
        for match in re.finditer(pattern, content, re.IGNORECASE):
            if is_safe_secret_placeholder(match.group(0)):
                continue
            unsafe_match = True
            break
        if unsafe_match:
            found.append(pattern)
    return found


def find_forbidden_patterns(content: str, patterns: list[str]) -> list[str]:
    return find_unsafe_regex_patterns(content, [*GLOBAL_FORBIDDEN_PATTERNS, *patterns])


def find_forbidden_terms(content: str, terms: list[str]) -> list[str]:
    found: list[str] = []
    for term in terms:
        if contains_broad_concept_only(term) or not contains_text(content, term):
            continue
        if term.lower() in SECRET_LIKE_FORBIDDEN_TERMS:
            secret_patterns = [r"sk-[A-Za-z0-9_\-]{8,}"]
            if "api" in term.lower():
                secret_patterns.append(r"api[_ -]?key\s*[:=]\s*[^\s,;]+")
            if "ai_api_key" in term.lower():
                secret_patterns.append(r"AI_API_KEY\s*=\s*[^\s]+")
            if find_unsafe_regex_patterns(content, secret_patterns):
                found.append(term)
            continue
        found.append(term)
    return found


def cjk_count(content: str) -> int:
    return sum(1 for char in content if "\u4e00" <= char <= "\u9fff")


def english_word_count(content: str) -> int:
    return len(re.findall(r"\b[A-Za-z]{2,}\b", content))


def strip_code_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def find_json_candidate(content: str) -> str | None:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return text[index : index + end]
    return None


def format_passes(content: str, expected_format: str, format_mode: str = "strict") -> bool:
    text = content.strip()
    if expected_format == "plain":
        return bool(text)
    if expected_format == "json":
        if format_mode == "contains":
            candidate = find_json_candidate(text)
            if not candidate:
                return False
            try:
                json.loads(candidate)
            except json.JSONDecodeError:
                return False
            return True
        try:
            json.loads(strip_code_fence(text))
        except json.JSONDecodeError:
            return False
        return True
    if expected_format == "table":
        table_lines = [line for line in text.splitlines() if "|" in line]
        return len(table_lines) >= 2
    if expected_format == "markdown":
        return bool(text)
    return False


def redact_secrets(content: str) -> str:
    redacted = content
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(1) + "[REDACTED]" if match.groups() else "[REDACTED]", redacted)
    return redacted


def evaluate_response(
    case: dict[str, Any],
    http_status: int | None,
    run_data: dict[str, Any],
) -> dict[str, Any]:
    expected = case["expected"]
    content = run_data.get("content", "")
    failures: list[str] = []
    warnings: list[str] = []

    if http_status is None:
        failures.append("backend_unreachable")
    elif http_status < 200 or http_status >= 300:
        failures.append(f"http_status_{http_status}")
    if run_data.get("errors"):
        failures.append("provider_or_stream_error")
    if not content.strip():
        failures.append("empty_response")

    missing_terms = [term for term in case["must_include"] if not contains_text(content, term)]
    missing_term_groups = missing_any_groups(content, case.get("must_include_any", []))
    forbidden_terms = find_forbidden_terms(content, case["must_not_include"])
    forbidden_patterns = find_forbidden_patterns(content, case.get("forbidden_patterns", []))
    if missing_terms or missing_term_groups:
        failures.append("missing_required_terms")
    if forbidden_terms or forbidden_patterns:
        failures.append("forbidden_terms_present")

    if expected.get("language") == "zh" and cjk_count(content) < 3:
        failures.append("language_not_zh")
    if expected.get("language") == "en" and english_word_count(content) < 3:
        failures.append("language_not_en")
    if not format_passes(content, expected["format"], expected.get("format_mode", "strict")):
        failures.append("format_mismatch")

    done_payload = run_data.get("done") if isinstance(run_data.get("done"), dict) else {}
    done_error = done_payload.get("error") if done_payload and done_payload.get("finish_reason") == "error" else None
    if done_error:
        warnings.append("stream_done_with_error")

    expected_status_chain = expected.get("status_chain")
    if expected.get("stream"):
        statuses = run_data.get("statuses", [])
        if expected_status_chain and statuses != expected_status_chain:
            failures.append("stream_status_chain_mismatch")
        event_order = run_data.get("event_order", [])
        try:
            complete_index = event_order.index("analysis_status", len(expected_status_chain or []))
        except ValueError:
            complete_index = -1
        if "delta" in event_order and "done" in event_order:
            if event_order.index("delta") > event_order.index("done"):
                failures.append("delta_after_done")
        if expected_status_chain == STATUS_CHAIN and statuses == STATUS_CHAIN:
            first_delta = event_order.index("delta") if "delta" in event_order else -1
            complete_seen = statuses[-1] == "complete"
            if first_delta == -1 or not complete_seen:
                failures.append("missing_stream_delta_or_complete")
        if run_data.get("chunk_count", 0) < 1:
            failures.append("missing_stream_chunks")
        if complete_index == -1:
            warnings.append("complete_event_position_not_verified")

    evaluation_type = case["evaluation_type"]
    if failures:
        status = "failed"
    elif evaluation_type in {"manual", "hybrid"} or case.get("manual_check"):
        status = "needs_review"
    else:
        status = "passed"

    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "missing_terms": missing_terms,
        "missing_term_groups": missing_term_groups,
        "forbidden_terms": forbidden_terms,
        "forbidden_patterns": forbidden_patterns,
        "content_redacted": redact_secrets(content),
        "error_details": [*run_data.get("errors", []), *([done_error] if done_error else [])],
    }


def run_case(
    args: argparse.Namespace,
    opener: urllib.request.OpenerDirector,
    case: dict[str, Any],
) -> dict[str, Any]:
    url = args.base_url.rstrip("/") + "/chat"
    payload = build_payload(case, args.model)
    stream = bool(payload["stream"])
    started_at = dt.datetime.now().isoformat(timespec="seconds")

    if stream:
        http_status, run_data = post_stream(opener, url, payload, args.timeout)
        metrics = build_metrics(
            first_status_ms=run_data.get("first_status_ms"),
            first_delta_ms=run_data.get("first_delta_ms"),
            total_ms=run_data.get("total_ms"),
            chunk_count=run_data.get("chunk_count", 0),
        )
    else:
        http_status, response_data, total_ms = post_json(opener, url, payload, args.timeout)
        run_data = {
            "content": response_data.get("content", ""),
            "errors": [response_data.get("error")] if response_data.get("error") else [],
            "total_ms": total_ms,
        }
        metrics = build_metrics(
            first_status_ms=None,
            first_delta_ms=None,
            total_ms=total_ms,
            chunk_count=None,
        )

    evaluation = evaluate_response(case, http_status, run_data)
    return {
        "case_id": case["id"],
        "category": case["category"],
        "title": case["title"],
        "difficulty": case["difficulty"],
        "evaluation_type": case["evaluation_type"],
        "stream": stream,
        "http_status": http_status,
        "status": evaluation["status"],
        "failures": evaluation["failures"],
        "warnings": evaluation["warnings"],
        "missing_terms": evaluation["missing_terms"],
        "missing_term_groups": evaluation["missing_term_groups"],
        "forbidden_terms": evaluation["forbidden_terms"],
        "forbidden_patterns": evaluation["forbidden_patterns"],
        "error_details": evaluation["error_details"],
        "metrics": metrics,
        "response": evaluation["content_redacted"],
        "started_at": started_at,
        "source": case["_source"],
    }


def number_or_none(value: Any) -> float | int | None:
    if isinstance(value, int | float):
        return value
    return None


def build_metrics(
    *,
    first_status_ms: Any,
    first_delta_ms: Any,
    total_ms: Any,
    chunk_count: Any,
) -> dict[str, float | int | None]:
    first_status = number_or_none(first_status_ms)
    first_delta = number_or_none(first_delta_ms)
    total = number_or_none(total_ms)
    chunks = chunk_count if isinstance(chunk_count, int) else None

    first_delta_after_status = None
    if first_status is not None and first_delta is not None:
        first_delta_after_status = max(0, first_delta - first_status)

    visible_stream = None
    if total is not None and first_delta is not None:
        visible_stream = max(0, total - first_delta)

    avg_chunk_gap = None
    if visible_stream is not None and chunks:
        avg_chunk_gap = visible_stream / chunks

    return {
        "first_status_ms": first_status,
        "first_delta_ms": first_delta,
        "total_ms": total,
        "chunk_count": chunks,
        "first_delta_after_status_ms": first_delta_after_status,
        "visible_stream_ms": visible_stream,
        "avg_visible_chunk_gap_ms": avg_chunk_gap,
    }


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_latency_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "category",
        "stream",
        "status",
        "first_status_ms",
        "first_delta_ms",
        "total_ms",
        "chunk_count",
        "first_delta_after_status_ms",
        "visible_stream_ms",
        "avg_visible_chunk_gap_ms",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            metrics = row["metrics"]
            writer.writerow(
                {
                    "case_id": row["case_id"],
                    "category": row["category"],
                    "stream": row["stream"],
                    "status": row["status"],
                    "first_status_ms": metrics.get("first_status_ms"),
                    "first_delta_ms": metrics.get("first_delta_ms"),
                    "total_ms": metrics.get("total_ms"),
                    "chunk_count": metrics.get("chunk_count"),
                    "first_delta_after_status_ms": metrics.get("first_delta_after_status_ms"),
                    "visible_stream_ms": metrics.get("visible_stream_ms"),
                    "avg_visible_chunk_gap_ms": metrics.get("avg_visible_chunk_gap_ms"),
                }
            )


def summarize_metric(rows: list[dict[str, Any]], metric_name: str) -> dict[str, float] | None:
    values = [
        row["metrics"][metric_name]
        for row in rows
        if isinstance(row["metrics"].get(metric_name), int | float)
    ]
    if not values:
        return None

    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "avg": sum(values) / len(values),
        "p95": ordered[p95_index],
        "max": max(values),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": len(rows),
        "status_counts": {},
        "category_counts": {},
        "failure_counts": {},
    }
    for row in rows:
        summary["status_counts"][row["status"]] = summary["status_counts"].get(row["status"], 0) + 1
        summary["category_counts"][row["category"]] = summary["category_counts"].get(row["category"], 0) + 1
        for failure in row["failures"]:
            summary["failure_counts"][failure] = summary["failure_counts"].get(failure, 0) + 1

    metric_summaries = {
        "latency_ms": summarize_metric(rows, "total_ms"),
        "first_status_ms": summarize_metric(rows, "first_status_ms"),
        "first_delta_ms": summarize_metric(rows, "first_delta_ms"),
        "first_delta_after_status_ms": summarize_metric(rows, "first_delta_after_status_ms"),
        "visible_stream_ms": summarize_metric(rows, "visible_stream_ms"),
    }
    for name, value in metric_summaries.items():
        if value:
            summary[name] = value
    return summary


def write_summary_md(path: Path, summary: dict[str, Any], failed_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Chatbot Evaluation Summary",
        "",
        f"- Total cases: {summary['total']}",
        f"- Status counts: `{json.dumps(summary['status_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- Category counts: `{json.dumps(summary['category_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- Failure counts: `{json.dumps(summary['failure_counts'], ensure_ascii=False, sort_keys=True)}`",
    ]
    if summary.get("latency_ms"):
        latency = summary["latency_ms"]
        lines.extend(
            [
                f"- Average latency: `{latency['avg']:.2f} ms`",
                f"- P95 latency: `{latency['p95']:.2f} ms`",
                f"- Max latency: `{latency['max']:.2f} ms`",
            ]
        )
    if summary.get("first_status_ms"):
        metric = summary["first_status_ms"]
        lines.append(f"- First status avg/p95: `{metric['avg']:.2f} ms / {metric['p95']:.2f} ms`")
    if summary.get("first_delta_ms"):
        metric = summary["first_delta_ms"]
        lines.append(f"- First delta avg/p95: `{metric['avg']:.2f} ms / {metric['p95']:.2f} ms`")
    if summary.get("first_delta_after_status_ms"):
        metric = summary["first_delta_after_status_ms"]
        lines.append(
            f"- First delta after first status avg/p95: `{metric['avg']:.2f} ms / {metric['p95']:.2f} ms`"
        )
    if failed_rows:
        lines.extend(["", "## Failed Cases", ""])
        for row in failed_rows:
            lines.append(
                f"- `{row['case_id']}` {row['title']} "
                f"failures=`{','.join(row['failures'])}`"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run chatbot dataset evaluations against the local API.")
    parser.add_argument("--base-url", default=os.getenv("CHATBOT_EVAL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--category", choices=sorted(ALLOWED_CATEGORIES))
    parser.add_argument("--case-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--use-env-proxy",
        action="store_true",
        default=DEFAULT_USE_ENV_PROXY,
        help="Use http_proxy/https_proxy from the shell. Disabled by default for local API tests.",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip /health and /config checks before running cases.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Only check /health and /config, then exit without running model cases.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate datasets without calling the API.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(args.dataset_dir)
    errors = validate_cases(cases)
    selected_cases = [case for case in cases if case_matches(case, args.category, args.case_id)]
    if args.limit is not None:
        selected_cases = selected_cases[: args.limit]

    if errors:
        print("Dataset validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    if not selected_cases:
        print("No cases selected.")
        return 1
    if args.dry_run:
        print(f"Dataset validation ok. Selected cases: {len(selected_cases)} / {len(cases)}")
        return 0

    opener = build_url_opener(args.use_env_proxy)
    preflight = None
    if not args.skip_preflight:
        preflight = preflight_backend(opener, args.base_url, min(args.timeout, 5.0))
        if not preflight["health"]["ok"]:
            print("Backend preflight failed.")
            print(json.dumps(preflight, ensure_ascii=False, indent=2))
            print("Start the backend and verify the base URL before running dataset evaluation.")
            return 1
        if args.preflight_only:
            print("Backend preflight ok.")
            print(json.dumps(preflight, ensure_ascii=False, indent=2))
            return 0
    elif args.preflight_only:
        print("--preflight-only cannot be used with --skip-preflight.")
        return 1

    report_dir = args.report_root / now_report_name()
    report_dir.mkdir(parents=True, exist_ok=False)
    git_status = git_status_short()

    metadata = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "git_dirty": bool(git_status),
        "git_status_short": git_status,
        "base_url": args.base_url,
        "dataset_dir": str(args.dataset_dir.relative_to(PROJECT_ROOT)),
        "selected_cases": len(selected_cases),
        "category": args.category,
        "case_id": args.case_id,
        "limit": args.limit,
        "model_override": args.model,
        "use_env_proxy": args.use_env_proxy,
        "preflight": preflight,
        "api_key_saved": False,
    }
    write_json(report_dir / "metadata.json", metadata)

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(selected_cases, 1):
        print(f"[{index}/{len(selected_cases)}] {case['id']} {case['title']}")
        try:
            rows.append(run_case(args, opener, case))
        except Exception as exc:
            rows.append(
                {
                    "case_id": case["id"],
                    "category": case["category"],
                    "title": case["title"],
                    "difficulty": case["difficulty"],
                    "evaluation_type": case["evaluation_type"],
                    "stream": bool(case["expected"].get("stream", False)),
                    "http_status": None,
                    "status": "failed",
                    "failures": ["runner_exception"],
                    "warnings": [],
                    "missing_terms": [],
                    "missing_term_groups": [],
                    "forbidden_terms": [],
                    "forbidden_patterns": [],
                    "error_details": [{"message": str(exc)}],
                    "metrics": build_metrics(
                        first_status_ms=None,
                        first_delta_ms=None,
                        total_ms=None,
                        chunk_count=None,
                    ),
                    "response": str(exc),
                    "started_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "source": case["_source"],
                }
            )

    failed_rows = [row for row in rows if row["status"] == "failed"]
    summary = summarize(rows)
    write_jsonl(report_dir / "results.jsonl", rows)
    write_jsonl(report_dir / "failures.jsonl", failed_rows)
    write_latency_csv(report_dir / "latency.csv", rows)
    write_summary_md(report_dir / "summary.md", summary, failed_rows)

    print(f"Report saved to: {report_dir.relative_to(PROJECT_ROOT)}")
    print(f"Summary: {json.dumps(summary, ensure_ascii=False, sort_keys=True)}")
    return 1 if failed_rows else 0


if __name__ == "__main__":
    sys.exit(main())
