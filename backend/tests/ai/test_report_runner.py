from __future__ import annotations

import pytest

from app.agent.report.builder import ReportArtifact, ReportError
from app.agent.tools.report import runner as report_runner
from app.agent.tools.report.runner import run_report
from app.agent.tools.report.schema import ReportArguments
from app.auth import reset_current_conversation_id, set_current_conversation_id


@pytest.mark.asyncio
async def test_run_report_success_returns_report_geospatial(monkeypatch):
    # 常规：runner 从 contextvar 取 conversation_id，调 builder 成功 → report 类型结果 + 下载链接。
    captured = {}

    async def fake_build(*, conversation_id, user_id, imagery_id):
        captured["conversation_id"] = conversation_id
        captured["imagery_id"] = imagery_id
        return ReportArtifact(
            imagery_id="d722c20e1234",
            filename="report_x.docx",
            download_url="/api/imagery/d722c20e1234/results/report_x.docx",
        )

    monkeypatch.setattr(report_runner, "build_conversation_report", fake_build)
    monkeypatch.setattr(report_runner, "get_current_user_id", lambda: "u1")
    token = set_current_conversation_id("conv-123")
    try:
        result = await run_report(ReportArguments(reason="导出报告"))
    finally:
        reset_current_conversation_id(token)

    assert captured["conversation_id"] == "conv-123"
    assert result.error is None
    assert result.geospatial_result["type"] == "report"
    assert result.geospatial_result["download_url"].endswith("report_x.docx")
    assert "下载" in result.tool_context
    assert "不要编造" in result.tool_context


@pytest.mark.asyncio
async def test_run_report_passes_explicit_imagery_id(monkeypatch):
    # 常规：用户显式指定 imagery_id 时，runner 原样下传给 builder。
    captured = {}

    async def fake_build(*, conversation_id, user_id, imagery_id):
        captured["imagery_id"] = imagery_id
        return ReportArtifact(
            imagery_id=imagery_id or "auto",
            filename="r.docx",
            download_url=f"/api/imagery/{imagery_id}/results/r.docx",
        )

    monkeypatch.setattr(report_runner, "build_conversation_report", fake_build)
    monkeypatch.setattr(report_runner, "get_current_user_id", lambda: "u1")
    result = await run_report(ReportArguments(imagery_id="abcdef012345", reason="指定影像"))
    assert captured["imagery_id"] == "abcdef012345"
    assert result.error is None


@pytest.mark.asyncio
async def test_run_report_no_analysis_returns_safe_error(monkeypatch):
    # 异常分支：builder 抛 ReportError（无分析结果）→ 中文安全文案 + error_code，不泄漏内部细节。
    async def fake_build(*, conversation_id, user_id, imagery_id):
        raise ReportError("本对话还没有可用于报告的真实分析结果，请先执行分析。", code="no_analysis")

    monkeypatch.setattr(report_runner, "build_conversation_report", fake_build)
    monkeypatch.setattr(report_runner, "get_current_user_id", lambda: "u1")
    result = await run_report(ReportArguments(reason="导出"))

    assert result.error == "no_analysis"
    assert "真实分析结果" in result.tool_context
    assert result.geospatial_result is None
    # 不得把内部异常细节暴露给模型
    assert "Traceback" not in result.tool_context


@pytest.mark.asyncio
async def test_run_report_unexpected_error_is_sanitized(monkeypatch):
    # 异常分支：builder 抛非 ReportError 异常 → 稳定中文兜底文案，不漏原始异常串。
    async def fake_build(*, conversation_id, user_id, imagery_id):
        raise RuntimeError("C:/secret/path docker stderr boom")

    monkeypatch.setattr(report_runner, "build_conversation_report", fake_build)
    monkeypatch.setattr(report_runner, "get_current_user_id", lambda: "u1")
    result = await run_report(ReportArguments(reason="导出"))

    assert result.error == "report_unexpected_error"
    assert "secret" not in result.tool_context
    assert "docker" not in result.tool_context
    assert "报告生成失败" in result.tool_context


def test_report_arguments_rejects_invalid_imagery_id():
    # 非法输入：imagery_id 格式非法（非 12 位 hex）被 pydantic pattern 拦下。
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ReportArguments(imagery_id="not-hex")
    # 边界：完全不传 imagery_id 合法（由 builder 取最近影像）。
    assert ReportArguments().imagery_id is None
