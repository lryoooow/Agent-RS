"""6 个领域 Agent + 1 个搜索 Agent，全部是**真** AssistantAgent。

## 与 legacy 的 DomainToolAgent 有什么不同

`app/agent/domain_agents.py` 里的 `DomainToolAgent` 不是 Agent：它没有 LLM、没有
自己的上下文、不做任何推理。它只干两件事——往 trace 里打一个 domain 标签，
往 `tool_context` 尾部拼一段固定的 `DOMAIN_GUIDANCE` 文本。

所以 README 说的「顶层统一规划 → 领域子 Agent 执行」，实际是
「一个规划器 → 一个工具执行器 + 一个字符串」。它不能：

- 看到工具返回值后判断结果是否可信（比如波段配错导致检测数异常）
- 失败后换参数重试
- 一个领域内连续做几步（先质检再算指数）

这里把 `DOMAIN_GUIDANCE` 从「拼在结果后面的话」变成 Agent 的 `system_message`，
把 `TOOL_DOMAIN` 从「trace 标签」变成 Agent 真正持有的工具集，
再给上 `max_tool_iterations`，领域 Agent 才第一次具备上述能力。

## 领域划分沿用 legacy

`TOOL_DOMAIN` / `DOMAIN_LABELS` / `DOMAIN_GUIDANCE` 三张表原样复用，
不在迁移里顺手改领域归属——那是独立的产品决策，混在一起会让回归定位困难。
"""

from __future__ import annotations

from dataclasses import dataclass

from autogen_agentchat.agents import AssistantAgent
from autogen_core.memory import Memory
from autogen_core.models import ChatCompletionClient

from app.agent.domain_agents import DOMAIN_GUIDANCE, DOMAIN_LABELS, TOOL_DOMAIN
from app.agent.engine.context import BudgetedChatCompletionContext
from app.agent.engine.tools import RemoteSensingTool, build_tools
from app.core.settings import get_settings

# 所有领域 Agent 共享的行为底线。领域各自的专业指引来自 DOMAIN_GUIDANCE。
#
# 这几条都是从 legacy 的踩坑里搬过来的：多步链路会放大「编造结果」的风险，
# 因为模型看到前几步成功后，容易把没做的那步也一并"总结"出来。
_SHARED_RULES = """
你是 Agent-RS 的领域专家，负责用你手上的工具完成用户的遥感任务。

铁律：
1. 只陈述工具真实返回的数值与结论，绝不编造未返回的统计、类别或面积。
2. 工具返回失败或被拒绝时，如实说明这一步没有成功及原因，不要假装做过。
3. 需要多步时按顺序调用工具，每步都用上一步的真实结果，不要跳步臆测。

关于是否该调用工具（这些规则来自真实踩坑，必须严格遵守）：
4. 用户只问概念、原理、含义时直接回答，不要调用工具。**即使上下文里有影像清单也不调**。
5. 用户明确说"不要调用工具/不要计算/先别处理/只讲原理"时，一律不调。
6. 工具与任务明显不匹配时不要硬凑最接近的那个。例如：用 NDVI 检测船只、用重投影识别车辆、
   用 OCR 判断植被覆盖率——这些都应当拒绝并说明原因。

关于资源 ID：
7. 绝不凭空编造 imagery_id / document_id，只能用影像/文档清单里列出的完整 ID。
8. 用户给的 ID 残缺或写错时：能在清单里**唯一**匹配到一张就用那张的完整 ID；
   匹配到多张、或匹配不到任何一张，就停下来请用户指明，**不要在候选里随便猜**。
9. 清单只有一张自有影像时，用户说"这张图/刚才那张"可以用那张。
10. 用户明确说"没有提供影像 ID / 没有可用影像"时以用户为准，显式否定优先于系统清单。

关于交棒与收尾（**极其重要，写错会让用户的请求半途而废**）：

11. 你只有自己领域的工具。用户的请求里若有步骤需要别的领域的工具，你做完自己那部分后，
    必须**明确点名**下一步该由哪个专家接手。

12. 回答的最后必须做一次**完成度自检**，格式固定：

        进度自检：
        - <用户要求的第 1 步>：已完成 / 未完成（谁来做）
        - <用户要求的第 2 步>：已完成 / 未完成（谁来做）
        ...

    「用户要求的步骤」以**用户最初那句话**为准拆解，不是以你自己做了什么为准。

13. 自检之后**必须**在最后单独一行给出结论标记，二选一，不允许两个都不写：

    - 还有步骤要**别的专家**接着做 → 不写 [DONE]，并点名下一位。
    - 其余一切情况 → 在最后单独一行写 [DONE]。

    [DONE] 的含义是「这一轮不需要再有专家发言了」，**不是**「任务成功了」。
    所以下面这些情况全都要写 [DONE]：

    - 用户只是打招呼、闲聊、道谢；
    - 用户问概念、原理、翻译、写代码、算数学——你已经答完了；
    - 你按第 6 条拒绝了不匹配的任务；
    - 你按第 8 / 10 条停下来向用户要影像 ID 或澄清——**等用户回话不等于还有步骤**，
      换谁来都问同一句话。

    这四类里没有"用户要求的步骤"，自检表就写一行「无需工具步骤：已完成」，
    照样把 [DONE] 写上。

    漏写 [DONE] **不会**被别人补救：没有它，调度器只能一个接一个地继续点专家，
    用户会收到七八条内容雷同的回答。这是目前最常见的故障，比早写 [DONE] 更严重。

同事名册（需要交棒时点名字）：
{roster}
""".strip()


@dataclass(frozen=True)
class DomainAgentSpec:
    name: str
    label: str
    tools: tuple[str, ...]
    guidance: str

    @property
    def description(self) -> str:
        """给顶层编排器看的「这个 Agent 能干什么」。

        SelectorGroupChat 就是靠这段话选人的，所以要写得可判别，
        而不是笼统的"处理遥感任务"。
        """
        tool_list = "、".join(self.tools)
        return f"{self.label}领域专家，负责：{tool_list}。"

    @property
    def system_message(self) -> str:
        return f"{_SHARED_RULES.format(roster=_roster_text())}\n\n{self.guidance}"


def _roster_text() -> str:
    """所有领域专家的名册，注入每个 Agent 的 system_message。

    没有名册时 Agent 只能说「这需要植被指数领域的工具」这种模糊话，
    selector 未必接得住；有了名册它能直接点名 `spectral_agent`，交棒可靠得多。
    实测：加名册前跨领域链路在第一棒就断了。
    """
    lines = []
    for domain, tools in sorted(_tools_by_domain().items()):
        label = DOMAIN_LABELS.get(domain, domain)
        lines.append(f"- {domain}（{label}）：{'、'.join(sorted(tools))}")
    return "\n".join(lines)


def _tools_by_domain() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for tool_name, domain in TOOL_DOMAIN.items():
        grouped.setdefault(domain, []).append(tool_name)
    return grouped


def domain_specs() -> list[DomainAgentSpec]:
    """从 legacy 的三张表推导领域清单，保证两条链路的领域划分不会漂移。"""
    grouped = _tools_by_domain()
    return [
        DomainAgentSpec(
            name=domain,
            label=DOMAIN_LABELS.get(domain, domain),
            tools=tuple(sorted(tools)),
            guidance=DOMAIN_GUIDANCE.get(domain, ""),
        )
        for domain, tools in sorted(grouped.items())
    ]


def build_domain_agent(
    spec: DomainAgentSpec,
    *,
    model_client: ChatCompletionClient,
    memory: list[Memory] | None = None,
) -> AssistantAgent:
    settings = get_settings()
    tools: list[RemoteSensingTool] = build_tools(spec.tools)
    return AssistantAgent(
        name=spec.name,
        description=spec.description,
        model_client=model_client,
        tools=tools,
        system_message=spec.system_message,
        model_context=BudgetedChatCompletionContext(),
        memory=memory or None,
        # 这一行就是「一轮只能跑一个工具」的解药：legacy 硬编码 max_tool_calls=1
        # （routing.py:38），这里让模型可以连续要工具直到收敛或到上限。
        max_tool_iterations=max(1, settings.agent_max_tool_iterations),
        # 工具跑完后让模型再组织一次语言，而不是把工具原文直接当回答。
        # 领域指引里那些「引用真实统计、说明模型边界」的要求要在这一步生效。
        reflect_on_tool_use=True,
        model_client_stream=True,
    )


def build_domain_agents(
    *,
    model_client: ChatCompletionClient,
    memory: list[Memory] | None = None,
) -> list[AssistantAgent]:
    return [
        build_domain_agent(spec, model_client=model_client, memory=memory)
        for spec in domain_specs()
    ]
