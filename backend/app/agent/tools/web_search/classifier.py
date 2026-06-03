import re
from enum import Enum


class SearchIntent(Enum):
    SKIP = "skip"
    FORCE = "force"
    UNCERTAIN = "uncertain"


_FORCE_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(最新|最近|今天|今日|昨天|本周|这周|上周|本月|今年|"
        r"实时|当前价格|现在.*多少|目前.*情况|"
        r"新闻|热搜|热点|头条|breaking|latest|trending|"
        r"发布了|上线了|更新了|宣布了|"
        r"股价|汇率|天气|比分|赛果|"
        r"刚刚|刚才)"
    ),
    re.compile(r"(202[4-9]|2030)年"),
    re.compile(r"search|搜索一下|帮我查|查一下|查询一下|搜一下"),
]

_SKIP_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"^(你好|hi|hello|hey|嗨|哈喽|早上好|晚上好|下午好|谢谢|感谢|"
        r"好的|明白|了解|收到|ok|okay|是的|对的|没问题)[\s!！。.？?]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"(写一个|写个|编写|实现|代码|函数|class|def |function |import |"
        r"print\(|console\.log|SELECT |INSERT |CREATE TABLE|"
        r"算一下|帮我算|请计算|求解|证明|推导|解方程)",
    ),
    re.compile(
        r"(翻译|translate|解释一下这段|什么意思|帮我改|润色|重写|续写|"
        r"总结一下|概括|提炼|归纳)",
    ),
]

_FOLLOWUP_PATTERNS: list[re.Pattern] = [
    re.compile(r"(那我|那么|所以|那.*呢|可是|但是|不过|还有|另外|接着)"),
    re.compile(r"(应该|需要|要不要|是不是|能不能|可以吗|怎么办)"),
]

_SEARCH_RESULT_SIGNALS = (
    "[S1]", "[S2]", "Sources:", "搜索结果", "根据搜索",
    "根据查询", "查询结果显示", "据报道", "据了解",
)


def classify_search_intent(
    query: str,
    conversation_messages: list | None = None,
) -> SearchIntent:
    text = query.strip()
    if not text or len(text) < 2:
        return SearchIntent.SKIP

    for pattern in _SKIP_PATTERNS:
        if pattern.search(text):
            return SearchIntent.SKIP

    if _is_followup_with_existing_results(text, conversation_messages):
        return SearchIntent.SKIP

    for pattern in _FORCE_PATTERNS:
        if pattern.search(text):
            return SearchIntent.FORCE

    return SearchIntent.UNCERTAIN


def _is_followup_with_existing_results(
    query: str,
    messages: list | None,
) -> bool:
    if not messages or len(messages) < 2:
        return False
    is_followup = any(p.search(query) for p in _FOLLOWUP_PATTERNS)
    if not is_followup:
        return False
    for msg in reversed(messages[-4:]):
        content = ""
        if isinstance(msg, dict):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
        elif hasattr(msg, "role") and msg.role == "assistant":
            content = msg.content
        if not content:
            continue
        if any(signal in content for signal in _SEARCH_RESULT_SIGNALS):
            return True
    return False
