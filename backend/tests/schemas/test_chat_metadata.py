import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest


def test_chat_request_accepts_bounded_map_annotations() -> None:
    request = ChatRequest(
        messages=[{"role": "user", "content": "分析地图"}],
        metadata={"map_context": {"annotations": [{}] * 100}},
    )

    assert len(request.metadata["map_context"]["annotations"]) == 100


def test_chat_request_truncates_too_many_map_annotations() -> None:
    request = ChatRequest(
        messages=[{"role": "user", "content": "分析地图"}],
        metadata={"map_context": {"annotations": [{"index": index} for index in range(101)]}},
    )

    annotations = request.metadata["map_context"]["annotations"]
    assert len(annotations) == 100
    assert annotations[-1] == {"index": 99}


def test_chat_request_rejects_oversized_metadata() -> None:
    with pytest.raises(ValidationError, match="100KB"):
        ChatRequest(
            messages=[{"role": "user", "content": "分析地图"}],
            metadata={"payload": "x" * 100_001},
        )
