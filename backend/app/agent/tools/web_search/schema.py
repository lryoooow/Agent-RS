from app.agent.search.schema import WebSearchArguments

WEB_SEARCH_TOOL_NAME = "web_search"
WEB_SEARCH_TOOL_DESCRIPTION = (
    "检索公开网页，获取实时、最新或需要外部来源的信息（天气、价格、政策、官网、"
    "最新数据集等）。仅在对话上下文不足以回答时调用。"
    "检索词要聚焦：复合问题可给每个意图各写一条；没查到有用信息就换关键词再查一次，"
    "结果自相矛盾时补一次交叉验证；够用就停，不要为凑数反复检索。"
)
