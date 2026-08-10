"""AutoGen 上下文：复用项目已有的 token 预算，而不是换一套截断策略。

## 为什么不直接用 AutoGen 的 TokenLimitedChatCompletionContext

AutoGen 那个按「模型客户端报的 token 数」裁剪，策略是简单地从头丢消息。
本项目的 `app/agent/context/budget.py` 做了两件它没做的事：

1. **中文友好的 token 估算**——有 tiktoken 就用，没有就走 CJK 加权启发式
   （`_estimate_tokens_heuristic`），避免中文场景下按字符数估算严重偏低。
2. **按块分配预算**——不同来源（近期对话/摘要/记忆/RAG/工具结果）各有上限，
   见 settings 里那一串 `ai_context_max_*_chars`。丢弃时优先丢低价值块，
   而不是无脑丢最早的消息。

多步工具链路会让上下文比 legacy 长得多（每一步的工具结果都留在里面），
所以预算控制反而更重要。这里保留项目自己的策略，只把它套进 AutoGen 的协议。

## 与 legacy 的关系

legacy 在 `request_builder` 里一次性组装完整 prompt；这里是**逐轮生效**的裁剪，
两者不冲突：system prompt 仍由 prompting/ 渲染，本类只管对话消息的预算。

## 检索块单独存放，不进消息列表

RAG 与长期记忆的结果由 Memory 实现经 `update_context()` 注入，而 AutoGen 会在
**每次 Agent 发言前**都调一次 `update_context()`（`_assistant_agent.py:940`）。
如果照 `ListMemory` 的做法直接 append 成 SystemMessage，一个专家在一次编排里
发言 4 次就会留下 4 份**内容完全相同**的检索块，而且它们全是 SystemMessage——
正好撞上「SystemMessage 永不丢」这条规则，预算管不住它们。

实测：预算 2000 tokens，4 轮之后实际发出去 6058 tokens（3 倍超支），
其中同一份 RAG 块重复了 4 次。多步链路越长越严重，而多步正是这次迁移的卖点。

所以检索块按 **key 覆盖式**存在 `_blocks` 里，不进 `_messages`：
同一来源再次注入就替换掉旧的，天然去重；取消息时再拼到末尾，并**先扣掉**
它们占的预算，剩下的才分给对话历史。

注：AutoGen 的 Agent system prompt 不在 model_context 里
（`_call_llm` 是 `system_messages + await model_context.get_messages()`），
所以 `_messages` 里出现的 SystemMessage 只可能是外部注入的，不是身份提示词。
"""

from __future__ import annotations

import logging
from typing import Any, List, Mapping, Sequence

from autogen_core.model_context import ChatCompletionContext
from autogen_core.models import (
    AssistantMessage,
    FunctionExecutionResultMessage,
    LLMMessage,
    SystemMessage,
    UserMessage,
)

from app.agent.context.budget import estimate_tokens
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# settings 全部缺省时的兜底预算。宁可保守也不要变成"无上限"——
# 多步链路下无上限意味着上下文可以一路涨到 provider 报错。
_FALLBACK_BUDGET = 24_000


class BudgetedChatCompletionContext(ChatCompletionContext):
    """按项目自有 token 预算裁剪的上下文。

    裁剪规则（从"最该留"到"最先丢"）：

    1. **SystemMessage 永不丢**——里面是身份、工具策略、安全边界与刚注入的检索结果。
    2. **最后一条 UserMessage 永不丢**——丢了模型就不知道在回答什么。
    3. 其余消息从**最早**开始丢，直到进预算。
    4. `FunctionExecutionResultMessage` 与它对应的 `AssistantMessage`(tool_calls)
       **成对丢弃**——只留一半会让 provider 报 "tool_call without response"。

    第 4 条是多步工具链路特有的坑：legacy 一轮只有一个工具调用，不会遇到。
    """

    def __init__(
        self,
        initial_messages: List[LLMMessage] | None = None,
        *,
        max_tokens: int | None = None,
    ) -> None:
        super().__init__(initial_messages)
        self._max_tokens = max_tokens
        # 来源 key -> 检索块正文。见模块文档「检索块单独存放」。
        self._blocks: dict[str, str] = {}

    @property
    def token_budget(self) -> int:
        if self._max_tokens is not None:
            return self._max_tokens
        # 注意用解析后的 context_max_total_chars 而不是原始的 ai_context_max_total_chars：
        # 后者类型是 int | None，env 没配时是 None，直接拿来比较会 TypeError。
        # settings 上的 context_* 属性才是带默认值的解析结果。
        return get_settings().context_max_total_chars or _FALLBACK_BUDGET

    def upsert_block(self, key: str, block: str) -> None:
        """按来源覆盖式写入检索块。

        同一来源（知识库 / 长期记忆）每轮都会重新检索，后来的那份才是对当前问题
        最相关的，旧的直接替换掉——既去重，也保证上下文里始终是最新检索结果。
        空块表示这轮没检索到，把旧的一并清掉，免得把上一轮的资料当成这轮的。
        """
        if block:
            self._blocks[key] = block
        else:
            self._blocks.pop(key, None)

    async def get_messages(self) -> List[LLMMessage]:
        blocks = [SystemMessage(content=text) for text in self._blocks.values()]
        # 检索块先占预算：它们是本轮最相关的资料，比更早的对话轮次更该留。
        remaining = self.token_budget - sum(_message_tokens(m) for m in blocks)
        return _fit_to_budget(self._messages, max(0, remaining)) + blocks

    async def save_state(self) -> Mapping[str, Any]:
        state = dict(await super().save_state())
        state["max_tokens"] = self._max_tokens
        state["blocks"] = dict(self._blocks)
        return state

    async def load_state(self, state: Mapping[str, Any]) -> None:
        await super().load_state(state)
        self._max_tokens = state.get("max_tokens", self._max_tokens)
        self._blocks = dict(state.get("blocks") or {})


def _message_tokens(message: LLMMessage) -> int:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return estimate_tokens(content)
    # 多模态 / 工具结果列表：只算得出文本的部分，图片等按固定开销粗估
    total = 0
    for part in content if isinstance(content, Sequence) else []:
        if isinstance(part, str):
            total += estimate_tokens(part)
        else:
            total += estimate_tokens(str(getattr(part, "content", "") or ""))
    return total


def _fit_to_budget(messages: List[LLMMessage], budget: int) -> List[LLMMessage]:
    if not messages:
        return []

    keep_flags = [False] * len(messages)
    for index, message in enumerate(messages):
        if isinstance(message, SystemMessage):
            keep_flags[index] = True

    # 最后一条用户消息必须留
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], UserMessage):
            keep_flags[index] = True
            break

    total = sum(_message_tokens(m) for m in messages)
    if total <= budget:
        return list(messages)

    # 从最早开始丢可丢的；工具调用与其结果成对丢弃。
    droppable = [i for i, keep in enumerate(keep_flags) if not keep]
    dropped: set[int] = set()
    for index in droppable:
        if total <= budget:
            break
        if index in dropped:
            continue
        pair = _tool_pair_indices(messages, index)
        for member in pair:
            if member not in dropped:
                dropped.add(member)
                total -= _message_tokens(messages[member])

    if dropped:
        logger.debug("上下文超预算，丢弃 %d 条历史消息（预算 %d tokens）", len(dropped), budget)
    return [m for i, m in enumerate(messages) if i not in dropped]


def _tool_pair_indices(messages: List[LLMMessage], index: int) -> list[int]:
    """返回必须与 `index` 一起丢弃的消息下标集合。

    AssistantMessage 带 tool_calls 时，紧随其后的 FunctionExecutionResultMessage
    必须一起丢；反之亦然。只丢一半会让 provider 报 tool_call 与响应不配对。
    """
    message = messages[index]
    pair = [index]

    if isinstance(message, AssistantMessage) and not isinstance(message.content, str):
        following = index + 1
        if following < len(messages) and isinstance(
            messages[following], FunctionExecutionResultMessage
        ):
            pair.append(following)
    elif isinstance(message, FunctionExecutionResultMessage):
        preceding = index - 1
        if preceding >= 0 and isinstance(messages[preceding], AssistantMessage):
            if not isinstance(messages[preceding].content, str):
                pair.insert(0, preceding)
    return pair
