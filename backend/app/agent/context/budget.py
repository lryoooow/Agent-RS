"""上下文预算度量与截断。

重要语义说明：本模块所有 `max_*` 入参都是 **token 预算**，**不是字符数**。settings 里诸如
`ai_context_max_rag_chars` / `ai_prompt_max_core_chars` 等以 `_chars` 结尾的配置项
名称属历史保留——它们最终都作为 token 预算传入 `trim_to_budget`。调参时请按 token 而非字符理解。

计数实现：优先用 tiktoken 的 `cl100k_base` 编码精确计 token；tiktoken 未安装或词表
加载失败（如离线环境无法下载）时，自动降级到 CJK 感知的启发式（中文/CJK 约 1.5、
ASCII 约 0.25），保证上下文装配在任何环境都不因计数而崩。

诚实标注：`cl100k_base` 对 GPT 系模型精确，对 Claude/通义千问等其它模型仍是**近似**
（各家分词器不同），但显著优于纯启发式，且为行业通行做法。
"""

import logging
import unicodedata

logger = logging.getLogger(__name__)

TRUNCATION_MARKER = "\n...[context truncated]"

# 模块级缓存：encoder 实例（懒加载）；_ENCODER_READY 标记是否已尝试过加载，
# 避免每次调用都重试 import/加载词表（失败时也只告警一次）。
_ENCODER = None
_ENCODER_READY = False


def _get_encoder():
    """懒加载并缓存 tiktoken cl100k_base 编码器；不可用时返回 None（触发启发式降级）。"""
    global _ENCODER, _ENCODER_READY
    if _ENCODER_READY:
        return _ENCODER
    _ENCODER_READY = True
    try:
        import tiktoken

        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        # tiktoken 未安装 / 离线无法加载词表 / 其它异常：降级启发式，仅告警一次。
        logger.warning(
            "tiktoken 不可用，token 计数降级为启发式估算（不影响功能，仅精度略降）。",
            exc_info=True,
        )
        _ENCODER = None
    return _ENCODER


def estimate_tokens(content: str) -> int:
    """计算文本的 token 数。

    优先 tiktoken 精确计数；不可用时降级为 CJK 感知启发式。空串返回 0。
    """
    if not content:
        return 0
    encoder = _get_encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(content))
        except Exception:
            # 极端输入导致编码异常时，不让计数环节崩——退回启发式。
            logger.debug("tiktoken 编码失败，本次降级启发式。", exc_info=True)
    return _estimate_tokens_heuristic(content)


def _estimate_tokens_heuristic(content: str) -> int:
    """CJK 感知的轻量 token 估算（tiktoken 不可用时的兜底）。"""
    total = 0.0
    for char in content:
        if char.isspace():
            total += 0.1
        elif _is_cjk(char):
            total += 1.5
        elif char.isascii():
            total += 0.25
        else:
            total += 1.0
    return max(1, int(total + 0.999)) if content else 0


def trim_to_budget(content: str, max_tokens: int | None) -> str:
    text = content.strip()
    if max_tokens is None or estimate_tokens(text) <= max_tokens:
        return text
    if max_tokens <= 0:
        return ""

    marker_tokens = estimate_tokens(TRUNCATION_MARKER)
    if max_tokens <= marker_tokens:
        return _trim_text_to_tokens(text, max_tokens).rstrip()

    return f"{_trim_text_to_tokens(text, max_tokens - marker_tokens).rstrip()}{TRUNCATION_MARKER}"


def _trim_text_to_tokens(text: str, max_tokens: int) -> str:
    """把文本截断到至多 max_tokens 个 token。

    有 tiktoken 时走 encode→切片→decode（精确，且整串一次编码，不逐字符）；
    否则退回逐字符启发式累加（与 _estimate_tokens_heuristic 同口径）。
    """
    if max_tokens <= 0:
        return ""
    encoder = _get_encoder()
    if encoder is not None:
        try:
            tokens = encoder.encode(text)
            if len(tokens) <= max_tokens:
                return text
            return encoder.decode(tokens[:max_tokens])
        except Exception:
            logger.debug("tiktoken 截断失败，本次降级逐字符启发式。", exc_info=True)
    return _trim_text_to_tokens_heuristic(text, max_tokens)


def _trim_text_to_tokens_heuristic(text: str, max_tokens: int) -> str:
    """逐字符按启发式 token 累加截断（tiktoken 不可用时兜底）。"""
    if max_tokens <= 0:
        return ""
    used = 0
    output: list[str] = []
    for char in text:
        char_tokens = _estimate_tokens_heuristic(char)
        if output and used + char_tokens > max_tokens:
            break
        output.append(char)
        used += char_tokens
    return "".join(output)


def _is_cjk(char: str) -> bool:
    name = unicodedata.name(char, "")
    return (
        "CJK UNIFIED" in name
        or "HIRAGANA" in name
        or "KATAKANA" in name
        or "HANGUL" in name
    )
