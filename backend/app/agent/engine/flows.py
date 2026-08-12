"""GraphFlow：把常用遥感链路固化成有向图。

## 为什么在 SelectorGroupChat 之外还要这个

Selector 靠模型每一步现场决策"下一个该谁"，灵活但有代价：

- 每一步都要多一次模型调用来选人
- 顺序不保证——实测里出现过专家之间来回踢皮球
- 同样的请求两次可能走出不同路径，不好复现

对于**顺序固定**的标准作业（质检 → 指数 → 报告），路径是已知的，没必要每步都问模型。
`GraphFlow` 用 `DiGraphBuilder` 把顺序写死，只有节点内部的工具调用交给模型。

两者定位：
- **GraphFlow** —— 用户请求命中已知模式时走，快、稳、可复现
- **SelectorGroupChat** —— 兜底，处理没有预设图的自由请求

本模块只提供图的构造；编排层的 AutoGen 结构化路由 Agent 自动判断什么时候走图，
不完整或不确定的请求回退到 SelectorGroupChat。
"""

from __future__ import annotations

import logging

from autogen_agentchat.base import ChatAgent
from autogen_agentchat.conditions import ExternalTermination, MaxMessageTermination
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_core.memory import Memory
from autogen_core.models import ChatCompletionClient

from app.agent.engine.agents import ContextFactory, build_domain_agent, domain_specs

logger = logging.getLogger(__name__)

# 预设链路：名字 -> 领域 Agent 的执行顺序。
#
# 只收录「顺序确定且各步作用于同一影像」的链路。刻意**不**收录
# 「裁剪 → 分析」——preprocess 的领域指引明说派生栅格不注册为新影像 ID
# （见 agents.DOMAIN_GUIDANCE["preprocess_agent"]），
# 所以那条链路在产品上就不成立，固化它只会让模型撞墙。
PRESET_FLOWS: dict[str, tuple[str, ...]] = {
    # 质检 → 指数 → 报告：最常用的标准作业
    "inspect_index_report": ("spectral_agent", "report_agent"),
    # 云掩膜质量控制 → 地物分类 → 报告
    "mask_segment_report": ("preprocess_agent", "segmentation_agent", "report_agent"),
    # 检测 → 报告
    "detect_report": ("detection_agent", "report_agent"),
}


def build_flow(
    name: str,
    *,
    model_client: ChatCompletionClient,
    memory: list[Memory] | None = None,
    context_factory: ContextFactory | None = None,
    external_termination: ExternalTermination | None = None,
) -> GraphFlow:
    """按预设名构造一条固定链路。"""
    if name not in PRESET_FLOWS:
        raise KeyError(f"未知链路 {name!r}，可选：{sorted(PRESET_FLOWS)}")

    specs = {spec.name: spec for spec in domain_specs()}
    sequence = PRESET_FLOWS[name]

    agents: list[ChatAgent] = []
    for domain in sequence:
        if domain not in specs:
            raise KeyError(f"链路 {name!r} 引用了不存在的领域 {domain!r}")
        agents.append(
            build_domain_agent(
                specs[domain],
                model_client=model_client,
                memory=memory,
                context_factory=context_factory,
            )
        )

    builder = DiGraphBuilder()
    for agent in agents:
        builder.add_node(agent)
    for upstream, downstream in zip(agents, agents[1:]):
        builder.add_edge(upstream, downstream)
    builder.set_entry_point(agents[0])

    graph = builder.build()
    termination = MaxMessageTermination(len(agents) * 6)
    if external_termination is not None:
        termination = termination | external_termination
    return GraphFlow(
        participants=agents,
        graph=graph,
        # 图已经定死了顺序，这里只作为跑飞时的兜底闸。
        termination_condition=termination,
    )


def available_flows() -> list[str]:
    return sorted(PRESET_FLOWS)
