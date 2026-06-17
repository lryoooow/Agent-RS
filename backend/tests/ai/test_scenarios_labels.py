"""执行阶段标签（scenarios.py）单测。

本轮 UI 改动：执行阶段（child_agent_running / tool_execution_started）不再统一显示
"正在执行工具"，而是按工具显示具体能力名（正在计算 NDVI / 正在进行地物分类…）。
覆盖：已登记工具→专名；未登记工具→兜底；并守住 request/ready/final 三个既有标签不回归。
"""
from __future__ import annotations

from app.agent.domain_agents import TOOL_DOMAIN
from app.agent.prompting.scenarios import (
    TOOL_RUNNING_LABELS,
    tool_final_label,
    tool_ready_label,
    tool_request_label,
    tool_running_label,
)


# ---------- 常规：已登记工具显示具体能力名 ----------

def test_tool_running_label_known_tools_are_specific() -> None:
    assert tool_running_label("calculate_ndvi") == "正在计算 NDVI"
    assert tool_running_label("segment_landcover") == "正在进行地物分类"
    assert tool_running_label("detect_objects") == "正在进行目标检测"
    assert tool_running_label("web_search") == "正在联网搜索"
    # 关键：绝不能再是统一的"正在执行工具"。
    assert "正在执行工具" not in tool_running_label("calculate_ndvi")


# ---------- 边界：未登记工具走兜底（不崩、带工具名定位） ----------

def test_tool_running_label_unknown_tool_falls_back() -> None:
    assert tool_running_label("some_new_tool") == "正在执行工具：some_new_tool"


# ---------- 历史重复点：每个领域工具都有专属 running 标签（防新增工具漏配） ----------

def test_every_domain_tool_has_running_label() -> None:
    # TOOL_DOMAIN 是工具→领域归属的单一数据源；新增工具若漏配 running 标签，
    # 执行阶段会退回兜底"正在执行工具：xxx"——本用例守住每个登记工具都有专名。
    missing = [name for name in TOOL_DOMAIN if name not in TOOL_RUNNING_LABELS]
    assert missing == [], f"these tools lack a running label: {missing}"


# ---------- 既有标签不回归 ----------

def test_request_ready_final_labels_unchanged() -> None:
    assert tool_request_label("calculate_ndvi") == "请求调用 NDVI 计算"
    assert tool_ready_label("calculate_ndvi") == "NDVI 计算结果已整理"
    assert tool_final_label("calculate_ndvi") == "正在基于 NDVI 计算结果生成回答"
    # 未登记走各自兜底
    assert tool_request_label("x") == "请求调用工具：x"
    assert tool_ready_label("x") == "工具结果已整理"
    assert tool_final_label("x") == "正在基于工具结果生成最终回答"
