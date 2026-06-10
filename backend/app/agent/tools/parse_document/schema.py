from __future__ import annotations

import re

from pydantic import BaseModel, Field

# 文档 ID 是数据库 UUID（documents.id::uuid），与影像的 12 位十六进制 ID 不同。
DOCUMENT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class ParseDocumentArguments(BaseModel):
    model_config = {"extra": "forbid"}

    document_id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        description="已上传文档的ID（UUID）",
    )
    max_chars: int = Field(
        default=0,
        ge=0,
        le=200000,
        description="返回全文的最大字符数；0 表示用系统默认上限。超出部分会被截断并标注。",
    )
    reason: str = Field(default="用户请求读取文档全文", description="读取原因")


PARSE_DOCUMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_document",
        "description": (
            "按文档ID取出已上传文档的整体全文与元信息（标题、类型、页数、字数）。"
            "当用户要求总结/概括整篇文档、抽取贯穿全文的信息（如所有日期、指标、条款），"
            "或需要分块检索之外的完整上下文时调用此工具。文档在上传时已解析入库，"
            "本工具直接读取，不重新解析原始文件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "已上传文档的ID（UUID）",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "返回全文的最大字符数；0 表示用系统默认上限",
                },
                "reason": {
                    "type": "string",
                    "description": "读取原因说明",
                },
            },
            "required": ["document_id"],
            "additionalProperties": False,
        },
    },
}
