from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.report.builder import ReportError, build_conversation_report
from app.auth import get_current_user_id

router = APIRouter(tags=["reports"])

# ReportError.code → HTTP 状态码。结果卡片"生成报告"按钮走此端点，
# 服务端以持久化结果为准（前端不传分析数据，防伪造/陈旧）。
_ERROR_STATUS = {
    "no_user": 401,
    "no_conversation": 400,
    "storage_inactive": 503,
    "conversation_forbidden": 404,
    "no_analysis": 409,
    "render_failed": 500,
}


class ReportCreateRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    imagery_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{12}$")


class ReportCreateResponse(BaseModel):
    imagery_id: str
    filename: str
    download_url: str


@router.post("/reports", response_model=ReportCreateResponse)
async def create_report(request: ReportCreateRequest) -> ReportCreateResponse:
    user_id = get_current_user_id()
    try:
        artifact = await build_conversation_report(
            conversation_id=request.conversation_id,
            user_id=user_id,
            imagery_id=request.imagery_id,
        )
    except ReportError as exc:
        raise HTTPException(status_code=_ERROR_STATUS.get(exc.code, 400), detail=exc.message) from exc
    return ReportCreateResponse(
        imagery_id=artifact.imagery_id,
        filename=artifact.filename,
        download_url=artifact.download_url,
    )
