from __future__ import annotations

from app.agent.report.builder import ReportArtifact


def format_report_context(artifact: ReportArtifact) -> str:
    """报告生成成功后注入答复模型的上下文：告知已出报告 + 下载链接 + 引用边界。"""
    return (
        "分析报告已生成（Word/.docx），可供用户下载。\n"
        f"- 影像 ID: {artifact.imagery_id}\n"
        f"- 文件名: {artifact.filename}\n"
        f"- 下载链接: {artifact.download_url}\n"
        "报告内容基于本对话此前真实执行的分析结果，请据实向用户说明报告已生成并提示下载，"
        "可简要概括包含的分析项，但不要编造报告里没有的数值或结论。"
    )
