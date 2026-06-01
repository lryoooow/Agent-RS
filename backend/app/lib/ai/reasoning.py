from typing import Literal

ReasoningPart = tuple[Literal["content", "reasoning"], str]

THINK_START = "<think>"
THINK_END = "</think>"


def split_think_blocks(text: str) -> tuple[str | None, str]:
    parser = ThinkTagParser()
    parts = parser.feed(text)
    parts.extend(parser.flush())

    reasoning = "".join(value for channel, value in parts if channel == "reasoning").strip()
    content = "".join(value for channel, value in parts if channel == "content")
    return reasoning or None, content


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

    def feed(self, text: str | None) -> list[ReasoningPart]:
        if not text:
            return []

        data = self.buffer + text
        self.buffer = ""
        parts: list[ReasoningPart] = []
        cursor = 0

        while cursor < len(data):
            tag = THINK_END if self.in_reasoning else THINK_START
            tag_index = data.find(tag, cursor)

            if tag_index >= 0:
                self._append(parts, data[cursor:tag_index])
                self.in_reasoning = not self.in_reasoning
                cursor = tag_index + len(tag)
                continue

            remaining = data[cursor:]
            keep = longest_tag_prefix_suffix(remaining, tag)
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
