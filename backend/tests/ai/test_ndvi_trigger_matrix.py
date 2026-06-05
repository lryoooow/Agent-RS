from __future__ import annotations

import json
from pathlib import Path

import app.agent.tool_selector as selector_module
from app.agent.prompting.scenarios import wants_ndvi_calculation
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest

from _trigger_cases import NDVI_TEXT_CASES


def _request_with_context(*messages: dict[str, str]) -> ChatRequest:
    return ChatRequest(messages=list(messages))


def _make_known_imagery(root: Path, imagery_id: str, owner_user_id: str | None = None) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    payload = {"filename": "sample.tif"}
    if owner_user_id:
        payload["owner_user_id"] = owner_user_id
    (imagery_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")


def _format_mismatches(rows: list[tuple[str, str, object, object]]) -> str:
    lines = ["case_id | expected | actual | query"]
    lines.extend(f"{case_id} | {expected} | {actual} | {query}" for case_id, query, expected, actual in rows)
    return "\n".join(lines)


def test_wants_ndvi_calculation_matrix_matches_expected_decisions() -> None:
    mismatches: list[tuple[str, str, object, object]] = []

    for case in NDVI_TEXT_CASES:
        actual = wants_ndvi_calculation(case.query)
        if actual != case.wants_calculation:
            mismatches.append((case.case_id, case.query, case.wants_calculation, actual))

    assert not mismatches, _format_mismatches(mismatches)


def test_ndvi_tool_requires_imagery_context_even_when_calculation_is_requested(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    tool_call = selector_module.detect_ndvi_intent("请计算 NDVI", user_id=get_settings().default_user_id)

    assert tool_call is None


def test_ndvi_tool_uses_trusted_chinese_upload_context(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    user_id = get_settings().default_user_id
    _make_known_imagery(tmp_path, "94e758f38ede", user_id)
    request = _request_with_context(
        {"role": "system", "content": "当前上传影像：ID=94e758f38ede，图层类型=preview。"},
        {"role": "user", "content": "请计算 NDVI"},
    )

    tool_call = selector_module.detect_ndvi_intent("请计算 NDVI", request.messages, user_id=user_id)

    assert tool_call is not None
    assert tool_call.name == "calculate_ndvi"
    assert tool_call.arguments["imagery_id"] == "94e758f38ede"


def test_ndvi_tool_rejects_trusted_context_for_other_user(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    _make_known_imagery(tmp_path, "94e758f38ede", "other-user")
    request = _request_with_context(
        {"role": "system", "content": "当前上传影像：ID=94e758f38ede，图层类型=preview。"},
        {"role": "user", "content": "请计算 NDVI"},
    )

    tool_call = selector_module.detect_ndvi_intent(
        "请计算 NDVI",
        request.messages,
        user_id=get_settings().default_user_id,
    )

    assert tool_call is None


def test_ndvi_tool_ignores_long_hex_without_known_imagery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    long_hex = "94e758f38edeaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    request = _request_with_context(
        {"role": "assistant", "content": f"sha256={long_hex}"},
        {"role": "user", "content": "请计算 NDVI"},
    )

    tool_call = selector_module.detect_ndvi_intent(
        "请计算 NDVI",
        request.messages,
        user_id=get_settings().default_user_id,
    )

    assert tool_call is None


def test_ndvi_tool_uses_known_imagery_id_found_inside_long_hex(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    user_id = get_settings().default_user_id
    _make_known_imagery(tmp_path, imagery_id, user_id)
    long_hex = imagery_id + "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    request = _request_with_context(
        {"role": "assistant", "content": f"sha256={long_hex}"},
        {"role": "user", "content": "请计算 NDVI"},
    )

    tool_call = selector_module.detect_ndvi_intent("请计算 NDVI", request.messages, user_id=user_id)

    assert tool_call is not None
    assert tool_call.arguments["imagery_id"] == imagery_id


def test_ndvi_tool_does_not_trust_english_upload_marker_without_known_imagery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    request = _request_with_context(
        {"role": "system", "content": "current uploaded imagery: ID=94e758f38ede, layer type preview."},
        {"role": "user", "content": "please calculate NDVI"},
    )

    tool_call = selector_module.detect_ndvi_intent(
        "please calculate NDVI",
        request.messages,
        user_id=get_settings().default_user_id,
    )

    assert tool_call is None
