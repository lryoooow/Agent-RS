from app.agent.router import RequestRoute, classify_request_route
from app.schemas.chat import ChatRequest


def _request(content: str, *, use_memory: bool = True, use_rag: bool = False) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": content}],
        use_memory=use_memory,
        use_rag=use_rag,
    )


def test_router_sends_greeting_to_direct_chat() -> None:
    request = _request("你好")

    assert classify_request_route("你好", request) == RequestRoute.DIRECT_CHAT


def test_router_sends_programming_task_to_direct_chat() -> None:
    request = _request("帮我写一个快速排序算法")

    assert classify_request_route("帮我写一个快速排序算法", request) == RequestRoute.DIRECT_CHAT


def test_router_sends_knowledge_question_to_full_pipeline_when_context_enabled() -> None:
    request = _request("Transformer 的注意力机制是怎么工作的")

    assert classify_request_route("Transformer 的注意力机制是怎么工作的", request) == RequestRoute.FULL_PIPELINE


def test_router_sends_recent_news_to_full_pipeline() -> None:
    request = _request("最近有什么新闻", use_memory=False, use_rag=False)

    assert classify_request_route("最近有什么新闻", request) == RequestRoute.FULL_PIPELINE


def test_router_sends_short_ack_to_direct_chat_even_when_memory_enabled() -> None:
    request = _request("好的")

    assert classify_request_route("好的", request) == RequestRoute.DIRECT_CHAT
