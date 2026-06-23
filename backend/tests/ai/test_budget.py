"""context/budget.py token 度量与截断单测（H2：明确"入参是 token 预算非字符数"语义）。

覆盖：中文/英文/混合三种文本的 token 估算与截断行为，证明同一预算下中英文容量不同、
截断保留前缀并追加标记、零/负预算与超短预算的边界。
"""
from __future__ import annotations

from app.agent.context.budget import (
    TRUNCATION_MARKER,
    estimate_tokens,
    trim_to_budget,
)


# ---------- 常规：token 估算的中英文权重差异 ----------

def test_chinese_costs_more_tokens_than_ascii_for_same_char_count() -> None:
    # 同为 10 字符：中文按 ~1.5/字 估算，ASCII 按 ~0.25/字，前者 token 显著更多。
    zh = estimate_tokens("遥感影像分析植被覆盖度")  # 11 个 CJK 字
    en = estimate_tokens("abcdefghijk")  # 11 个 ASCII 字
    assert zh > en
    assert zh >= 11  # 至少 1/字 量级
    assert en <= 4   # 0.25/字 量级


def test_empty_string_is_zero_tokens() -> None:
    assert estimate_tokens("") == 0


# ---------- 边界：同一预算下中英文容纳字符数不同（这正是 *_chars 命名的歧义来源） ----------

def test_same_budget_holds_more_ascii_chars_than_chinese() -> None:
    budget = 20
    zh = trim_to_budget("遥" * 100, budget)
    en = trim_to_budget("a" * 100, budget)
    # ASCII 每字 ~0.25 token → 同预算能装的字符数远多于中文（每字 ~1.5）。
    # 两者都被截断（含标记），但 ASCII 保留的字符更多。
    zh_chars = len(zh.replace(TRUNCATION_MARKER, ""))
    en_chars = len(en.replace(TRUNCATION_MARKER, ""))
    assert en_chars > zh_chars


# ---------- 常规：截断保留前缀并追加标记 ----------

def test_trim_keeps_prefix_and_appends_marker() -> None:
    text = "这是一段需要被截断的中文文本内容用于测试预算" * 5
    trimmed = trim_to_budget(text, 12)
    assert trimmed.startswith("这是")  # 保留了原文开头前缀
    assert trimmed.endswith(TRUNCATION_MARKER.strip()) or TRUNCATION_MARKER in trimmed
    assert estimate_tokens(trimmed) <= 12 + estimate_tokens(TRUNCATION_MARKER)


def test_content_within_budget_is_returned_untrimmed() -> None:
    text = "短文本"
    assert trim_to_budget(text, 1000) == text
    assert TRUNCATION_MARKER not in trim_to_budget(text, 1000)


# ---------- 边界/非法：None、零、负、超短预算 ----------

def test_none_budget_returns_stripped_content_unchanged() -> None:
    assert trim_to_budget("  保留原文  ", None) == "保留原文"


def test_zero_or_negative_budget_returns_empty() -> None:
    assert trim_to_budget("任何内容", 0) == ""
    assert trim_to_budget("任何内容", -5) == ""


def test_budget_smaller_than_marker_still_returns_prefix_without_crash() -> None:
    # 预算比截断标记本身还小：不应崩，返回不带标记的前缀片段。
    out = trim_to_budget("abcdefghij", 1)
    assert isinstance(out, str)
    assert TRUNCATION_MARKER not in out


# ========== tiktoken 精确计数接入（小修 B）：五维补充 ==========
# 计数核心由「CJK 启发式」切到 tiktoken cl100k_base，保留启发式作 fallback。
# 下列用例在 tiktoken 可用时校验精确性，并显式覆盖 fallback 降级路径（不引新崩溃点）。

import pytest

import app.agent.context.budget as budget_module


def _reset_encoder_cache() -> None:
    """清掉模块级 encoder 缓存，让下次调用重新走 _get_encoder（用于隔离 mock 用例）。"""
    budget_module._ENCODER = None
    budget_module._ENCODER_READY = False


@pytest.fixture(autouse=True)
def _isolate_encoder_cache():
    """每个用例前后重置 encoder 缓存，避免 mock 跨用例污染（历史重复点：进程级单例串扰）。"""
    _reset_encoder_cache()
    yield
    _reset_encoder_cache()


def _tiktoken_or_skip():
    """拿到真实 cl100k_base encoder；环境无 tiktoken/词表则 skip（不假绿也不硬红）。"""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - 仅离线环境触发
        pytest.skip("tiktoken/cl100k_base 不可用，跳过精确计数断言")


# ---------- 常规：tiktoken 在用时与官方编码直算一致 ----------

@pytest.mark.parametrize(
    "text",
    [
        "hello world this is a plain english sentence",
        "遥感影像植被覆盖度分析与变化检测",
        "NDVI 计算结果显示 farmland 区域 0.78，置信度较高。",
    ],
)
def test_estimate_tokens_matches_tiktoken_when_available(text: str) -> None:
    enc = _tiktoken_or_skip()
    assert estimate_tokens(text) == len(enc.encode(text))


# ---------- 边界：tiktoken 精确切片后 token 数真 ≤ 预算 ----------

def test_trim_result_token_count_within_budget_tiktoken() -> None:
    enc = _tiktoken_or_skip()
    text = "遥感影像分析 remote sensing analysis " * 30
    budget = 25
    trimmed = trim_to_budget(text, budget)
    # 截断结果（含标记）的真实 token 数不得超过 预算 + 标记开销。
    assert len(enc.encode(trimmed)) <= budget + estimate_tokens(TRUNCATION_MARKER)
    assert TRUNCATION_MARKER in trimmed  # 确实发生了截断


def test_trim_within_budget_returns_untrimmed_tiktoken() -> None:
    _tiktoken_or_skip()
    text = "short enough 短文本"
    assert trim_to_budget(text, 1000) == text


# ---------- 异常 + 历史重复点：tiktoken import 失败 → 降级启发式，绝不抛 ----------

def test_falls_back_to_heuristic_when_tiktoken_import_fails(monkeypatch) -> None:
    # 模拟 tiktoken 不可导入：_get_encoder 内 `import tiktoken` 抛 ImportError。
    # _get_encoder 用的是 import 语句，走 builtins.__import__，patch 它即可。
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("simulated: tiktoken missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    # 不抛异常，encoder 为 None，计数与启发式一致（功能仍可用）。
    assert budget_module._get_encoder() is None
    expected = budget_module._estimate_tokens_heuristic("遥感 analysis 测试")
    assert estimate_tokens("遥感 analysis 测试") == expected
    # 截断也不崩，正常返回带标记的前缀。
    out = trim_to_budget("遥" * 100, 10)
    assert isinstance(out, str) and out


# ---------- 异常：encoder.encode 运行期抛错 → 单次降级启发式，不崩 ----------

def test_estimate_tokens_handles_encode_runtime_error(monkeypatch) -> None:
    class _BoomEncoder:
        def encode(self, _text):
            raise RuntimeError("simulated encode failure")

        def decode(self, _tokens):  # pragma: no cover - 本用例不触达
            raise RuntimeError("simulated decode failure")

    monkeypatch.setattr(budget_module, "_ENCODER", _BoomEncoder())
    monkeypatch.setattr(budget_module, "_ENCODER_READY", True)

    text = "遥感 analysis 测试"
    # encode 抛错被吞，退回启发式，结果与启发式一致、不抛。
    assert estimate_tokens(text) == budget_module._estimate_tokens_heuristic(text)


# ---------- 历史重复点：encoder 懒加载只初始化一次（缓存生效，避免每次重建） ----------

def test_encoder_loaded_once_via_ready_flag(monkeypatch) -> None:
    # 用一个计数 encoder 占位，验证：首次 _get_encoder 加载后置 _ENCODER_READY，
    # 后续调用命中短路、不再重建（返回同一实例）。
    _reset_encoder_cache()
    sentinel = object()
    loads = {"n": 0}

    import tiktoken

    def _spy_get_encoding(_name):
        loads["n"] += 1
        return sentinel

    monkeypatch.setattr(tiktoken, "get_encoding", _spy_get_encoding)

    first = budget_module._get_encoder()
    second = budget_module._get_encoder()
    third = budget_module._get_encoder()

    assert first is sentinel
    assert first is second is third  # 同一缓存实例
    assert loads["n"] == 1  # 只真正加载了一次（其余命中 _ENCODER_READY 短路）
