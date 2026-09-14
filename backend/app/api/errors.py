"""统一 API 错误契约（P1 制度化）。

全平台只允许一种错误信封：

    {"error": {"code": "<机器可读大写下划线码>", "message": "<给用户看的中文>"}}

三个来源都归一到它：
- 路由抛 ``api_error(...)``（detail 本就是 {code, message}）→ 处理器包一层 error 键；
- 路由抛裸字符串 detail 的 HTTPException → 处理器补 ``HTTP_<status>`` 码后包裹
  （存量 32 处逐步迁移，迁移完成前也不再有第二种形状）；
- 全局 AIError / RequestValidationError / 中间件（413/503）已是该形状。

状态码规则（文档化，评审以此为准）：
- 422：请求体/参数的结构化校验失败（Pydantic 层）；
- 400：语义或格式错误（非法 ID、非法 bbox、不支持的类型）；
- 401/403：未登录 / 权限不足；404：资源不存在（含越权伪装成不存在）；
- 409：冲突（ID 重复等）；413：体积超限；429：限流；
- 502：上游依赖返回失败（模型/STAC/对象存储）——message 用固定文案，
  异常细节只进日志，**不得**把 ``str(exc)`` 放进响应；
- 503：本地依赖不可用（数据库未起、功能开关关闭）；
- 500：服务端缺陷——同样不泄内部信息。
"""

from __future__ import annotations

from fastapi import HTTPException

__all__ = ["api_error", "ERROR_MESSAGES"]


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    """抛出统一形状的 HTTPException。

    ``code`` 用大写下划线机器码（如 ``SCENE_EXPIRED``）；``message`` 是
    可以直接展示给用户的中文文案。需要附加 headers（如 429 的 Retry-After）
    时用返回值的 ``.headers`` 语义——直接 ``raise api_error(...) from exc``，
    异常链供日志追踪。
    """
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# 常用错误码 → 文案。路由直接引用，避免同一语义在不同文件措辞漂移。
ERROR_MESSAGES: dict[str, tuple[int, str]] = {
    "INVALID_ID": (400, "请求的 ID 格式不合法。"),
    "INVALID_REQUEST": (400, "请求参数不合法。"),
    "RESOURCE_NOT_FOUND": (404, "资源不存在。"),
    "SCENE_NOT_FOUND": (404, "场景已过期或不存在，请重新搜索。"),
    "UPSTREAM_FAILED": (502, "上游服务暂时不可用，请稍后重试。"),
    "SERVICE_UNAVAILABLE": (503, "服务暂时不可用，请稍后重试。"),
}


def coded_error(code: str, message_override: str | None = None) -> HTTPException:
    """按错误码目录抛错；message 可覆写（如带具体 ID）。"""
    status, default_message = ERROR_MESSAGES.get(code, (400, "请求无效。"))
    return api_error(status, code, message_override or default_message)
