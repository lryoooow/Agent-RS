"""engine/orchestrator.py：终止判据与结果抽取。

这里的每条断言都对应一个实测踩到的坑，不是假想的边界情况。
"""
from __future__ import annotations

import pytest
from autogen_agentchat.messages import TextMessage, ToolCallRequestEvent
from autogen_core import FunctionCall

from app.agent.engine.orchestrator import (
    AnswerStreamSanitizer,
    DONE_MARKER,
    _all_steps_done,
    build_team,
    participant_names,
    strip_done_marker,
    strip_scaffolding,
)


def _text(content: str, source: str = "spectral_agent") -> TextMessage:
    return TextMessage(content=content, source=source)


# --------------------------------------------------------------- 终止判据


def test_marker_at_end_terminates() -> None:
    assert _all_steps_done([_text(f"全部完成。\n\n{DONE_MARKER}")])


def test_marker_quoted_mid_text_does_not_terminate() -> None:
    """实测踩到的坑：[DONE] 这个串写在 Agent 的 system prompt 里，
    Agent 复述规则时 TextMentionTermination 会误触发，导致三步链路在第二步被截断——
    尽管那条消息的进度自检明明写着"未完成"。

    换成「必须以标记结尾」后，复述不再误杀。
    """
    message = _text(
        "进度自检：\n"
        "- 质检：已完成\n"
        "- NDVI：已完成\n"
        "- 生成报告：未完成（需 report_agent 来做）\n"
        "（规则提醒：全部完成后才写 [DONE]）"
    )
    assert not _all_steps_done([message]), "复述规则不该被当成完成信号"


def test_incomplete_selfcheck_does_not_terminate() -> None:
    message = _text(
        "已完成 NDVI。\n\n进度自检：\n- NDVI：已完成\n- 报告：未完成（需 report_agent）"
    )
    assert not _all_steps_done([message])


def test_only_text_messages_participate_in_termination() -> None:
    """工具调用事件不该参与终止判断——它们不是"回答"。"""
    tool_event = ToolCallRequestEvent(
        content=[FunctionCall(id="c1", name="calculate_ndvi", arguments="{}")],
        source="spectral_agent",
    )
    # 最新的是工具事件，往前找到的文本才算数
    assert _all_steps_done([_text(f"完成\n{DONE_MARKER}"), tool_event])
    assert not _all_steps_done([_text("还没完成"), tool_event])


def test_no_messages_does_not_terminate() -> None:
    assert not _all_steps_done([])


# --------------------------------------------------------------- 标记剥离


@pytest.mark.parametrize(
    "raw,expected",
    [
        (f"答案内容\n\n{DONE_MARKER}", "答案内容"),
        (f"答案内容{DONE_MARKER}", "答案内容"),
        (f"答案内容\n{DONE_MARKER}\n", "答案内容"),
        ("没有标记的答案", "没有标记的答案"),
        (f"{DONE_MARKER}", ""),
    ],
)
def test_strip_done_marker(raw: str, expected: str) -> None:
    """用户永远不该看到内部终止标记。"""
    assert strip_done_marker(raw) == expected


# --------------------------------------------------------------- 团队组装


def test_team_has_one_agent_per_domain() -> None:
    from app.agent.engine.agents import domain_specs

    team = build_team(user_id="00000000-0000-4000-8000-000000000001")
    names = {p.name for p in team._participants}  # noqa: SLF001
    assert names == {spec.name for spec in domain_specs()} | (
        set() if "search_agent" not in participant_names() else {"search_agent"}
    )


def test_team_allows_repeated_speaker() -> None:
    """同一专家要能连续发言：它在自己的多步工具循环里不该被强行换人。"""
    team = build_team(user_id="u1")
    assert team._allow_repeated_speaker is True  # noqa: SLF001


def test_search_agent_absent_without_tavily_key(monkeypatch) -> None:
    from app.core.settings import get_settings

    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    try:
        team = build_team(user_id="u1")
        assert "search_agent" not in {p.name for p in team._participants}  # noqa: SLF001
    finally:
        get_settings.cache_clear()


# ------------------------------------------------- 编排脚手架不能进用户正文


def test_strip_scaffolding_removes_self_check_block() -> None:
    """「进度自检」是给 selector 看的完成度清单，不是答复的一部分。"""
    raw = (
        "已完成 NDVI 计算，均值 0.42。\n\n"
        "进度自检：\n- 计算 NDVI：已完成\n- 生成报告：已完成\n\n"
        f"{DONE_MARKER}"
    )
    assert strip_scaffolding(raw) == "已完成 NDVI 计算，均值 0.42。"


def test_strip_scaffolding_drops_separator_before_self_check() -> None:
    """模型习惯在「进度自检」前加一条 `---` 分隔线，截断后它会孤零零留在正文末尾。"""
    raw = f"有什么需要我帮忙的吗？\n\n---\n进度自检：\n- 无需工具步骤：已完成\n\n{DONE_MARKER}"
    assert strip_scaffolding(raw) == "有什么需要我帮忙的吗？"


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 8, 13, 200])
def test_sanitizer_drops_separator_at_any_chunk_boundary(chunk_size: int) -> None:
    """分隔线跟空白一样，先发出去就收不回来，必须一并扣住。"""
    raw = f"有什么需要我帮忙的吗？\n\n---\n进度自检：\n- 无需工具步骤：已完成\n\n{DONE_MARKER}"
    assert _run_sanitizer(raw, chunk_size) == "有什么需要我帮忙的吗？"


def test_sanitizer_keeps_separator_inside_body() -> None:
    """正文中间的分隔线是内容的一部分，不能顺手删掉。"""
    raw = "第一段。\n\n---\n\n第二段。"
    assert _run_sanitizer(raw, 4) == raw


def _run_sanitizer(text: str, chunk_size: int) -> str:
    """按给定分片大小把文本喂给净化器，返回用户实际看到的正文。"""
    sanitizer = AnswerStreamSanitizer()
    out = [sanitizer.feed(text[i : i + chunk_size]) for i in range(0, len(text), chunk_size)]
    out.append(sanitizer.flush())
    return "".join(out)


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 8, 13, 200])
def test_sanitizer_never_leaks_marker_at_any_chunk_boundary(chunk_size: int) -> None:
    """实测踩到的坑：`[DONE]` 会漏进流式正文。

    根因是 delta 按 token 切，标记可能被切成 `进度自` + `检：`，
    对单个分片做替换根本匹配不上。所以这里穷举各种切分粒度。
    """
    raw = (
        "已完成 NDVI 计算，均值 0.42。\n\n"
        "进度自检：\n- 计算 NDVI：已完成\n\n"
        f"{DONE_MARKER}"
    )
    assert _run_sanitizer(raw, chunk_size) == "已完成 NDVI 计算，均值 0.42。"


@pytest.mark.parametrize("chunk_size", [1, 4, 8, 64])
def test_sanitizer_keeps_plain_answer_intact(chunk_size: int) -> None:
    """没有脚手架的普通回答必须一字不改地流出去。"""
    raw = "NDVI 全称是归一化植被指数，取值范围 -1 到 1。"
    assert _run_sanitizer(raw, chunk_size) == raw


def test_sanitizer_flush_resets_for_next_speaker() -> None:
    """跨领域链路里每位专家一条消息，上一条被抑制不能影响下一条。"""
    sanitizer = AnswerStreamSanitizer()
    sanitizer.feed(f"第一步完成。\n\n进度自检：\n- 第一步：已完成")
    sanitizer.flush()
    assert sanitizer.feed("第二步完成。") == "第二步完成。"


# ------------------------------------------------- 模型思考块不能进用户正文


def test_strip_scaffolding_removes_think_block() -> None:
    """实测漏出：整段 `<think>` 推理直接显示给了用户。

    legacy 链路一直有 ThinkTagParser，迁到 AutoGen 时这一环没接上。
    """
    raw = (
        "<think>用户只是打了个招呼，没有提出任何遥感任务需求。"
        "根据铁律第 4 条，直接回答即可，不需要调用工具。</think>"
        "你好！有什么可以帮你的吗？"
    )
    assert strip_scaffolding(raw) == "你好！有什么可以帮你的吗？"


def test_strip_scaffolding_ignores_scaffold_words_inside_think() -> None:
    """思考块必须先剥：模型在里面复述规则会写出「进度自检」「[DONE]」。

    先按标记截断的话，标记之后**真正的正文**会被一起丢掉，用户收到空回答。
    """
    raw = (
        f"<think>我要在最后单独一行写 {DONE_MARKER}，并附上进度自检清单。</think>"
        "NDVI 均值 0.42。"
    )
    assert strip_scaffolding(raw) == "NDVI 均值 0.42。"


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 8, 13, 200])
def test_sanitizer_never_leaks_think_at_any_chunk_boundary(chunk_size: int) -> None:
    """`<think>` 与脚手架标记一样会被切成 `<th` + `ink>`，必须逐粒度穷举。"""
    raw = (
        "<think>用户想做目标检测，但没给影像 ID，我需要问他要。</think>"
        "好的！请把影像 ID 发给我。"
    )
    assert _run_sanitizer(raw, chunk_size) == "好的！请把影像 ID 发给我。"


def test_sanitizer_think_state_does_not_leak_across_speakers() -> None:
    """上一位专家以未闭合的 `<think>` 结束，不能把下一位的正文整段吃掉。"""
    sanitizer = AnswerStreamSanitizer()
    sanitizer.feed("<think>这条被截断了")
    sanitizer.flush()
    assert sanitizer.feed("第二步完成。") == "第二步完成。"


# --------------------------------------------------- 正文要保住全链路的结论


def test_result_content_keeps_every_expert_step() -> None:
    """跨领域链路里每位专家各产出一段真实结论。

    只取最后一条会把前面几步的结果（"NDVI 均值 0.42"）从落库正文里删掉——
    而用户在流式过程中看到过它们，刷新页面却消失，前后不一致。
    """
    from autogen_agentchat.base import TaskResult

    from app.agent.engine.orchestrator import _to_result
    from app.agent.engine.turn_context import TurnToolState

    result = TaskResult(
        messages=[
            _text("先算 NDVI，再出报告", source="user"),
            _text("已完成 NDVI 计算，均值 0.42。\n\n进度自检：\n- 报告：未完成"),
            _text(f"报告已生成。\n\n进度自检：\n- 报告：已完成\n\n{DONE_MARKER}", "report_agent"),
        ],
        stop_reason="done",
    )
    content = _to_result(result, TurnToolState()).content
    assert "均值 0.42" in content, "第一步的真实结论不能丢"
    assert "报告已生成" in content
    assert DONE_MARKER not in content
    assert "进度自检" not in content
    assert content == "已完成 NDVI 计算，均值 0.42。\n\n报告已生成。"
