import re
from enum import Enum

from app.schemas.chat import ChatRequest


class RequestRoute(Enum):
    DIRECT_CHAT = "direct_chat"
    FULL_PIPELINE = "full_pipeline"


_DIRECT_PATTERNS = [
    re.compile(r"^(你好|hi|hello|hey|嗨|哈喽|早上好|晚上好|谢谢|感谢|好的|明白|了解|收到|ok|是的|对)[\s!！。.？?]*$", re.I),
    re.compile(r"(写一个|写个|编写|实现|代码|函数|class|def |function |import |print\(|console\.log|SELECT |INSERT |CREATE TABLE)", re.I),
    re.compile(r"(翻译|translate|帮我改|润色|重写|续写|总结一下|概括)", re.I),
    re.compile(r"(算一下|帮我算|请计算|求解|证明|推导|解方程)", re.I),
]

_SEARCH_KEYWORDS = re.compile(
    r"(最新|最近|今天|昨日|昨天|明天|现在|当前|实时|新闻|联网|搜索|查一下|查询|资料|出处|来源|引用|价格|汇率|天气|"
    r"政策|法规|版本|发布|更新|官网|文档|论文|数据|202[0-9]|19[0-9]{2})",
    re.I,
)

_RAG_KEYWORDS = re.compile(r"(文档|知识库|资料库|上传|附件|根据.*资料|从.*文档|这份|这篇|上面的内容|前面的内容)", re.I)


def classify_request_route(query: str, request: ChatRequest) -> RequestRoute:
    """Route cheap conversational work away from retrieval-heavy context building."""
    normalized = query.strip()
    if not normalized:
        return RequestRoute.DIRECT_CHAT

    if _has_search_keywords(normalized) or _has_rag_keywords(normalized):
        return RequestRoute.FULL_PIPELINE

    if len(normalized) < 5:
        return RequestRoute.DIRECT_CHAT

    if any(pattern.search(normalized) for pattern in _DIRECT_PATTERNS):
        return RequestRoute.DIRECT_CHAT

    if _is_follow_up_without_fact_signal(normalized, request):
        return RequestRoute.DIRECT_CHAT

    if request.use_rag or request.use_memory:
        return RequestRoute.FULL_PIPELINE

    return RequestRoute.DIRECT_CHAT


def _has_search_keywords(query: str) -> bool:
    return bool(_SEARCH_KEYWORDS.search(query))


def _has_rag_keywords(query: str) -> bool:
    return bool(_RAG_KEYWORDS.search(query))


def _is_follow_up_without_fact_signal(query: str, request: ChatRequest) -> bool:
    if len(request.messages) < 2:
        return False
    previous_assistant = any(message.role == "assistant" for message in request.messages[:-1])
    if not previous_assistant:
        return False
    return bool(re.search(r"(继续|展开|详细|换个|再说|解释|为什么|怎么做|上面|刚才|这个|它)", query, re.I))
