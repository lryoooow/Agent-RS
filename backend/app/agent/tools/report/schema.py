from pydantic import BaseModel, Field


class ReportArguments(BaseModel):
    model_config = {"extra": "forbid"}

    # imagery_id 可选：用户明确指定哪张图就用哪张；不给则由 builder 取本对话最近一次被分析的影像。
    imagery_id: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{12}$",
        description="可选，要生成报告的影像 ID；省略则汇总本对话最近一次分析的影像",
    )
    reason: str = Field(default="用户请求生成分析报告", description="生成报告的原因")


REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_report",
        "description": (
            "把本对话中已经真实执行过的遥感分析结果（地物分类、目标检测、光谱指数、影像质检等）"
            "汇总成一份可下载的 Word 报告。仅在本对话此前已产出分析结果、且用户要求生成报告/导出/"
            "出文档时调用；没有任何已执行的分析结果时不要调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {
                    "type": "string",
                    "description": "可选，指定要出报告的影像 ID；省略则用本对话最近一次分析的影像",
                },
                "reason": {"type": "string", "description": "生成报告的原因说明"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}
