from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.agent.prompting.scenarios import NDVI_EXPLANATION_TERMS
from app.agent.search.classifier import has_force_search_signal


SafetyAction = Literal["continue", "skip"]

_DIRECT_SKIP_PATTERNS = (
    re.compile(r"^(你好|hi|hello|hey|嗨|哈喽|早上好|晚上好|下午好|谢谢|感谢|好的|明白|了解|收到|ok|okay|是的|对的|没问题)[\s!！。.？?]*$", re.I),
    re.compile(r"(写一个|写个|编写|实现|代码|函数|class|def |function |import |print\(|console\.log|SELECT |INSERT |CREATE TABLE)", re.I),
    re.compile(r"(翻译|translate|帮我改|润色|重写|续写|总结一下|概括|提炼|归纳)", re.I),
    re.compile(r"(算一下|帮我算|请计算 \d|求解|证明|推导|解方程)", re.I),
)


@dataclass(frozen=True)
class SafetyDecision:
    action: SafetyAction
    reason: str


class SafetyPolicy:
    def decide(self, query: str) -> SafetyDecision:
        normalized = query.strip()
        if not normalized:
            return SafetyDecision(action="skip", reason="empty_query")
        if _is_ndvi_explanation(normalized) and has_force_search_signal(normalized):
            return SafetyDecision(action="continue", reason="freshness_requires_planner")
        if any(pattern.search(normalized) for pattern in _DIRECT_SKIP_PATTERNS):
            return SafetyDecision(action="skip", reason="direct_safety_skip")
        if _is_ndvi_explanation(normalized):
            return SafetyDecision(action="skip", reason="ndvi_explanation_no_tool")
        return SafetyDecision(action="continue", reason="planner_required")


def _is_ndvi_explanation(text: str) -> bool:
    lowered = text.lower()
    if "ndvi" not in lowered and "植被指数" not in text:
        return False
    return any(term in lowered for term in NDVI_EXPLANATION_TERMS)
