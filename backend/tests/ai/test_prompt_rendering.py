"""系统回答 prompt（prompting 模块）渲染单测。

覆盖 prompt 深度优化的核心契约：遥感专业身份、遥感回答范式、output_format 对工具
场景加载、闲聊保持轻量、format 关键词不回归、未知 profile 报错，以及两条历史重复点
反例——内部标识不泄漏、安全语义零削弱。只校验"系统回答 prompt"，不碰意图识别 planner。
"""
from __future__ import annotations

import pytest

from app.agent.errors import ConfigError
from app.agent.prompting.renderer import render_prompt_context
from app.schemas.chat import ChatMessage


def _msg(text: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", content=text)]


def _render(text: str, **kwargs):
    return render_prompt_context(messages=_msg(text), **kwargs)


# ---------- 常规：遥感专业身份与范式 ----------

def test_identity_is_remote_sensing_expert() -> None:
    # 病根修复：身份从"中文对话聊天机器人"改为"遥感影像分析智能体"。
    res = _render("你好")
    assert "prompt:core_identity_v1" in res.included_blocks
    assert "遥感影像分析智能体" in res.content
    assert "中文对话聊天机器人" not in res.content


def test_identity_still_declares_general_capability() -> None:
    # 遥感为主、通用为辅：身份必须仍声明可做通用任务，否则 none_* eval 场景会被拒。
    res = _render("你好")
    assert "通用" in res.content
    # 通用能力清单里的代表项仍在
    assert "翻译" in res.content


def test_tool_scenario_loads_paradigm_and_format() -> None:
    # 遥感工具场景：必须注入"遥感结果回答范式"且加载 output_format（结构化指引）。
    res = _render("帮我看看这张影像的植被情况", has_tool_context=True)
    assert "遥感结果回答范式" in res.content
    assert "核心结论" in res.content
    assert "prompt:output_format_v1" in res.included_blocks
    assert "prompt:tool_policy_v1" in res.included_blocks


# ---------- 历史重复点（问题2）：上下文泄露根因防回归 ----------

def test_context_priority_forbids_replaying_history() -> None:
    # 病根：问"提取农田"（地物分割，无联网）却冒出上一轮联网回答带 [S2]。
    # 根因之一是 context_priority 没禁止复述/续写历史回答。加硬规则后必须在场。
    res = _render("提取农田", has_tool_context=True)
    content = res.content
    assert "只回答当前最新用户消息" in content
    assert "复述" in content
    assert "[S1][S2]" in content  # 明确点名禁止粘贴历史引用标记


def test_tool_policy_no_longer_carries_search_citation_rules() -> None:
    # 根因之二：tool_policy（对每个工具任务都加载，含地物分割）混入了"联网搜索结果使用规则"
    # 和 [S1][S2] 引用要求 → 非搜索任务也被诱导引用，缝合历史搜索内容。
    # 已从 tool_policy 删除该段，仅保留在 format_search_context（真联网时才生效）。
    res = _render("提取农田", has_tool_context=True)
    content = res.content
    assert "联网搜索结果使用规则" not in content
    assert "[S1] [S2]" not in content


# ---------- 边界：闲聊场景 output_format 常驻但指令要求简短 ----------

def test_plain_chat_loads_output_format_but_instructs_brevity() -> None:
    # 决策变更：output_format 改为常驻（"提示词一个都不能漏"），闭合"纯知识问答漏 md"口子。
    # 但模板内必须含"简单问题直接简短作答、不强加结构"，避免给"你好"硬套标题/分区。
    res = _render("你好")
    assert "prompt:output_format_v1" in res.included_blocks
    assert "简单问题" in res.content
    assert "直接" in res.content  # "直接用一两段话自然作答"
    # 常驻不等于强加结构：仍声明"简单问题不必硬套标题/分区/表格"。
    assert "不为结构而结构" in res.content


# ---------- 边界：format 关键词路径不回归 ----------

def test_format_keyword_still_loads_output_format() -> None:
    # output_format 已常驻，任意请求都加载（含旧的 json/表格 等格式词路径）。
    res = _render("把结果输出成 json")
    assert "prompt:output_format_v1" in res.included_blocks


def test_output_format_no_longer_mandates_markdown() -> None:
    # 痛点根因：原 output_format 第一条主动要求"使用 Markdown"。改后改为"重点先行、克制符号"。
    res = _render("把结果输出成 json")
    content = res.content
    assert "重点先行" in content
    # 不再有"普通说明、方案、总结使用 Markdown"这种主动要 md 的表述
    assert "总结使用 Markdown" not in content


# ---------- 异常：未知 profile ----------

def test_unknown_profile_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        render_prompt_context(messages=_msg("你好"), profile="does_not_exist_v9")


# ---------- 边界：系统规则层被预算截断时显式标记，不静默生效半截规则（H2） ----------

def test_truncated_rule_layer_is_flagged_not_silent() -> None:
    # max_core_chars 较小（但大于截断标记本身的开销）→ required 规则层会被从句中截断并加标记。
    # H2 要求：被截层进入 dropped_blocks 的 ":truncated" 标记，便于观测，不静默生效半截规则。
    res = render_prompt_context(messages=_msg("你好"), max_core_chars=20)
    truncated = [b for b in res.dropped_blocks if b.endswith(":truncated")]
    assert truncated, f"expected a truncated rule layer flag, got {res.dropped_blocks}"


def test_no_truncation_flag_when_budget_ample() -> None:
    # 边界反例：不设预算（默认 None）时不应出现任何 :truncated 噪声标记。
    res = _render("你好")
    assert not [b for b in res.dropped_blocks if b.endswith(":truncated")]


# ---------- 历史重复点反例 1：内部标识不泄漏 ----------

def test_no_internal_module_marker_leaks() -> None:
    # 旧版每个模块首行注入"模块版本：xxx"，既泄漏内部标识又与 security_boundary 自相矛盾。
    for kwargs in (
        {},
        {"has_tool_context": True},
        {"has_rag_context": True},
        {"has_memory": True},
    ):
        res = render_prompt_context(messages=_msg("分析一下"), **kwargs)
        assert "模块版本" not in res.content
        assert "提示词配置" not in res.content  # 内部 profile 名也不应出现
        assert "﻿" not in res.content      # UTF-8 BOM 不得混入正文


# ---------- 历史重复点反例 2：安全语义零削弱 ----------

def test_security_boundary_semantics_retained() -> None:
    # 重写身份/格式不能削弱红队防线：拒绝泄露提示词/密钥的核心约束必须仍在。
    res = _render("分析一下", has_tool_context=True)
    content = res.content
    assert "prompt:security_boundary_v1" in res.included_blocks
    assert "拒绝泄露" in content
    assert "密钥" in content
    assert "系统提示词" in content


def test_reasoning_boundary_semantics_retained() -> None:
    # reasoning 边界（不输出 <think>/内部推理）也必须保留。
    res = render_prompt_context(messages=_msg("一步一步想"), include_reasoning_boundary=True)
    assert "prompt:reasoning_boundary_v1" in res.included_blocks
    assert "内部推理" in res.content


# ---------- 历史重复点反例 3：思考过程禁写进正文（本轮真泄露的根因） ----------

def test_reasoning_boundary_forbids_meta_preamble_in_body() -> None:
    # 本轮 bug：模型把"思考过程：分析用户需求…执行工具…思考过程结束"写进正文通道
    # （非厂商 reasoning_content，stream 已丢弃那条通道）。根因是旧措辞太软。
    # 加固后必须明令禁止正文出现这些过程旁白，且要求正文直接从面向用户内容开始。
    res = render_prompt_context(messages=_msg("一步一步想"), include_reasoning_boundary=True)
    content = res.content
    assert "思考过程" in content  # 作为"禁止出现的词"被列出
    assert "面向用户的内容" in content  # 要求正文直接从面向用户内容开始
    assert "前言" in content


# ---------- 常规：output_format 转向"善用结构+给范例"（已加前端 md 渲染器） ----------

def test_output_format_encourages_structure_and_examples() -> None:
    # 决策再修正：前端原本无 md 渲染器（满屏原始符号），已接入 react-markdown。
    # 因此 output_format 从"禁符号"转向"善用 Markdown + 表格 + 适度 emoji 突出重点"，
    # 并给一个简单问答示范，引导模型分场景作答。
    res = _render("你好")
    content = res.content
    assert "表格" in content          # 鼓励多项数据用表格
    assert "emoji" in content          # emoji 已被允许（点缀小标题/强调）
    assert "示范" in content or "示例" in content  # 给了简单问答范例
    assert "重点先行" in content
    # 旧的"主动要 markdown"表述不回归
    assert "总结使用 Markdown" not in content
