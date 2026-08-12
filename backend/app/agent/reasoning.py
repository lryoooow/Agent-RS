import re
from typing import Literal

ReasoningPart = tuple[Literal["content", "reasoning"], str]

THINK_START = "<think>"
THINK_END = "</think>"

# AutoGen 当前把 reasoning_content 包成 <think>，但输出安全边界不能依赖某一个
# SDK 版本的实现细节。兼容常见的明确推理标签，匹配大小写不敏感。
REASONING_TAGS: tuple[tuple[str, str], ...] = (
    ("<think>", "</think>"),
    ("<thinking>", "</thinking>"),
    ("<analysis>", "</analysis>"),
    ("<reasoning>", "</reasoning>"),
)


def split_think_blocks(text: str) -> tuple[str | None, str]:
    parser = ThinkTagParser()
    parts = parser.feed(text)
    parts.extend(parser.flush())
    content = "".join(value for channel, value in parts if channel == "content")
    narrated = NarratedReasoningFilter()
    content = narrated.feed(content) + narrated.flush()
    # 原始 reasoning 不应被调用方取得或继续传播。保留二元返回形状只为兼容旧调用方。
    return None, content


def longest_tag_prefix_suffix(text: str, tag: str) -> int:
    limit = min(len(text), len(tag) - 1)
    for size in range(limit, 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0


class ThinkTagParser:
    def __init__(self) -> None:
        self.in_reasoning = False
        self.buffer = ""
        self._closing_tag: str | None = None

    def feed(self, text: str | None) -> list[ReasoningPart]:
        if not text:
            return []

        data = self.buffer + text
        self.buffer = ""
        parts: list[ReasoningPart] = []
        cursor = 0

        while cursor < len(data):
            tags = (
                (self._closing_tag or THINK_END,)
                if self.in_reasoning
                else tuple(start for start, _end in REASONING_TAGS)
            )
            match = _first_tag(data, cursor, tags)

            if match is not None:
                tag_index, tag = match
                self._append(parts, data[cursor:tag_index])
                if self.in_reasoning:
                    self.in_reasoning = False
                    self._closing_tag = None
                else:
                    self.in_reasoning = True
                    self._closing_tag = dict(REASONING_TAGS)[tag]
                cursor = tag_index + len(tag)
                continue

            remaining = data[cursor:]
            lowered = remaining.lower()
            keep = max(longest_tag_prefix_suffix(lowered, tag) for tag in tags)
            emit = remaining[:-keep] if keep else remaining
            self._append(parts, emit)
            self.buffer = remaining[-keep:] if keep else ""
            break

        return parts

    def flush(self) -> list[ReasoningPart]:
        if not self.buffer:
            return []
        value = self.buffer
        self.buffer = ""
        return [(self._channel(), value)]

    def _append(self, parts: list[ReasoningPart], value: str) -> None:
        if value:
            parts.append((self._channel(), value))

    def _channel(self) -> Literal["content", "reasoning"]:
        return "reasoning" if self.in_reasoning else "content"


def _first_tag(data: str, cursor: int, tags: tuple[str, ...]) -> tuple[int, str] | None:
    """返回最早出现的标签；使用小写副本匹配但保留原文本索引。"""
    lowered = data.lower()
    found = [(index, tag) for tag in tags if (index := lowered.find(tag, cursor)) >= 0]
    return min(found, default=None, key=lambda item: item[0])


_NARRATED_HEADINGS = ("思考过程", "内部推理", "分析过程", "reasoning", "analysis")
_NARRATED_START = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:思考过程|内部推理|分析过程|reasoning|analysis)"
    r"\s*(?::|：|\r?\n)",
    re.IGNORECASE,
)
_NARRATED_END = re.compile(
    r"(?:思考过程结束|内部推理结束|分析过程结束)\s*[：:。.\-]*\s*"
    r"|(?:^|\r?\n)\s*(?:#{1,6}\s*)?(?:最终回答|正式回答|回答正文)\s*[:：]\s*",
    re.IGNORECASE,
)


class NarratedReasoningFilter:
    """丢弃模型误写进正文通道的显式推理旁白。

    只在回答开头出现明确标题时进入抑制态，避免误伤用户正常讨论“思考过程”这个词。
    抑制态只保留一小段尾巴用于识别跨 token 的结束标志，内存不会随推理长度增长。
    """

    _TAIL_LIMIT = 96

    def __init__(self) -> None:
        self._state: Literal["detecting", "suppressing", "resuming", "content"] = "detecting"
        self._buffer = ""

    def feed(self, text: str | None) -> str:
        if not text:
            return ""
        if self._state == "content":
            return text
        if self._state == "resuming":
            return self._resume(text)

        self._buffer += text
        if self._state == "detecting":
            if match := _NARRATED_START.match(self._buffer):
                self._state = "suppressing"
                self._buffer = self._buffer[match.end():]
            elif self._could_still_be_heading():
                return ""
            else:
                self._state = "content"
                visible, self._buffer = self._buffer, ""
                return visible

        return self._drain_suppressed()

    def flush(self) -> str:
        if self._state == "detecting":
            visible, self._buffer = self._buffer, ""
            self._state = "content"
            return visible
        # 明确进入推理旁白却没有安全结束标志时，整段 fail-closed 丢弃。
        self._buffer = ""
        return ""

    def _could_still_be_heading(self) -> bool:
        candidate = self._buffer.lstrip()
        if candidate.startswith("#"):
            candidate = candidate.lstrip("#").lstrip()
        folded = candidate.casefold()
        if len(folded) > 64 or "\n" in folded or "\r" in folded:
            return False
        for heading in _NARRATED_HEADINGS:
            expected = heading.casefold()
            if expected.startswith(folded):
                return True
            if folded.startswith(expected):
                suffix = folded[len(expected):]
                return not suffix or suffix.isspace() or suffix in (":", "：")
        return False

    def _drain_suppressed(self) -> str:
        if match := _NARRATED_END.search(self._buffer):
            visible = self._buffer[match.end():]
            self._buffer = ""
            self._state = "resuming"
            return self._resume(visible)
        if len(self._buffer) > self._TAIL_LIMIT:
            self._buffer = self._buffer[-self._TAIL_LIMIT:]
        return ""

    def _resume(self, text: str) -> str:
        visible = text.lstrip()
        if not visible:
            return ""
        self._state = "content"
        return visible
