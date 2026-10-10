from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.report.builder import ReportError, build_conversation_report
from app.agent.persistence import PersistenceContext, save_assistant_response
from app.api.errors import require_uuid
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
    "imagery_forbidden": 404,
    "storage_unavailable": 503,
    "report_publish_failed": 502,
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
        # G8：非法 conversation_id 与"对话不存在"同形（404），不再把坏字符串
        # 打到 DB 引发 DataError→500。
        conversation_id = require_uuid(
            request.conversation_id,
            code="conversation_forbidden",
            message="未找到该对话或无权访问，无法生成报告。",
        )
        artifact = await build_conversation_report(
            conversation_id=conversation_id,
            user_id=user_id,
            imagery_id=request.imagery_id,
        )
    except ReportError as exc:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(exc.code, 400),
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    response = ReportCreateResponse(
        imagery_id=artifact.imagery_id,
        filename=artifact.filename,
        download_url=artifact.download_url,
    )
    # The button bypasses the chat engine, so persist its download card here.
    # This lets reopening the conversation restore the same report artifact.
    await save_assistant_response(
        PersistenceContext(user_id=user_id, conversation_id=request.conversation_id),
        content="分析报告已生成",
        # This endpoint renders existing results locally, without a model call.
        usage={"input_tokens": 0, "output_tokens": 0},
        finish_reason="stop",
        geospatial_result={"type": "report", **response.model_dump()},
    )
    return response
