"""顶层 AutoGen 编排：自动 GraphFlow 路由与 SelectorGroupChat 兜底。

Selector 选领域，领域 Agent 自己运行多步工具循环，需要跨领域时再选择下一位；
完整命中标准作业的请求则走固定 GraphFlow。直到 Agent 以 [DONE] 收尾或达到轮次上限。

## 终止

`[DONE]` 标记 + 轮次上限双保险。标记法在多领域链路里必要——
只用 TextMessageTermination 会在第一个领域答完就停，链路走不下去。

## 编排脚手架不能进用户正文

`[DONE]` 与「进度自检」都是写给终止判据和 selector 看的，不是答复的一部分。
两条路径都必须剥干净：

- 非流式 / 落库：`_to_result` 走 `strip_scaffolding`
- 流式 SSE：`AnswerStreamSanitizer` 边流边滤（delta 是逐片到达的，
  标记会被切成两半，不能简单地对单片做 replace）

**正文取全链路而不是最后一条。** 跨领域链路里每位专家各产出一段结论，
只取最后一条会把前面几步的真实结果（"NDVI 均值 0.42"）从落库正文里丢掉，
用户刷新页面就看不到了——而流式过程中他明明看到过。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, AsyncIterator, Sequence

from autogen_agentchat.base import TaskResult, Team
from autogen_agentchat.conditions import (
    ExternalTermination,
    FunctionalTermination,
    MaxMessageTermination,
)
from autogen_agentchat.messages import BaseChatMessage, TextMessage
from autogen_agentchat.teams import SelectorGroupChat
from autogen_core import CancellationToken
from autogen_core.memory import Memory
from autogen_core.models import ChatCompletionClient

from app.agent.engine.agents import build_domain_agents, domain_specs
from app.agent.engine.flows import build_flow
from app.agent.engine.input import TurnInput
from app.agent.engine.memory import PgVectorMemory, RagMemory
from app.agent.engine.model_client import build_model_client
from app.agent.engine.router import RouteResult, choose_route
from app.agent.engine.turn_context import TurnToolState, turn_scope
from app.agent.config import ResolvedAIConfig, resolve_ai_config
from app.agent.reasoning import (
    NarratedReasoningFilter,
    ReasoningPart,
    ThinkTagParser,
    split_think_blocks,
)
from app.auth import user_scope

logger = logging.getLogger(__name__)

DONE_MARKER = "[DONE]"
_DONE_PATTERN = re.compile(r"\s*\[DONE\]\s*$")
HANDOFF_PREFIX = "[HANDOFF:"
_HANDOFF_PATTERN = re.compile(
    r"\[HANDOFF:\s*(?P<target>[A-Za-z][A-Za-z0-9_]*)\]\s*$",
    re.IGNORECASE,
)

# 旧版协议曾要求输出「进度自检」。新协议已删除，但净化器继续兼容历史模型输出，
# 防止滚动升级或提示缓存把旧脚手架泄露给用户。
SELF_CHECK_HEADER = "进度自检"

# 出现即表示「后面都是脚手架」的标记。顺序无关，取最早出现的那个。
_SCAFFOLD_SENTINELS: tuple[str, ...] = (
    SELF_CHECK_HEADER,
    DONE_MARKER,
    HANDOFF_PREFIX,
)

# SelectorGroupChat 是自由请求的兜底，不是无限自治循环。标准的长作业已经走 GraphFlow；
# 兜底团队最多保留四位专家接力，避免供应商漏控制行时把一次请求拖成十余轮。
_SELECTOR_MAX_TURNS = 4

_SELECTOR_PROMPT = """你是 Agent-RS 的调度器，负责决定下一步由哪个专家来做。

可选专家：
{roles}

对话记录：
{history}

从 {participants} 中选出下一个发言者，只返回角色名。

判别要点：
- 用户问概念、原理、翻译、代码、数学、写作等一般性问题：选 general_agent。
- 涉及影像计算：按任务类型选对应领域专家。
- 联网检索、地图定位、报告生成是**所有专家共有的共享工具**，需要时当前专家
  自己就会调用，不需要为它们换人。

**跨领域接力（最容易出错的地方，务必读完）：**
- 用户一句话要求多个步骤时（例如"重投影 → 算 NDVI → 出报告"），
  这些步骤分属不同专家，必须**一棒一棒接力**完成，不能只做第一步就收工。
- 上一位专家以 `[HANDOFF: XXX_agent]` 收尾时，下一位必须是它明确点名的专家。
- 判断还有没有剩余步骤，看的是**用户最初的请求**，不是上一条消息。
  只要用户要求里还有没做的步骤，就继续选人。
- 只有当用户最初请求的**全部**步骤都完成时，才停止选人。
- 不要为了"多做一点"而选额外的专家；用户没要求的事不要做。
"""


@dataclass
class OrchestrationResult:
    """一次 AutoGen 编排的产出。"""

    content: str
    messages: list[BaseChatMessage] = field(default_factory=list)
    turn_state: TurnToolState | None = None
    stop_reason: str | None = None
    usage: dict | None = None
    map_target: dict | None = None
    framework: str = "autogen"
    strategy: str = "selector"
    flow_name: str | None = None
    route_reason: str = ""

    @property
    def geospatial_result(self):
        return self.turn_state.latest_geospatial_result() if self.turn_state else None

    @property
    def tool_result(self):
        return self.turn_state.latest_tool_result() if self.turn_state else None

    @property
    def retrieved_chunks(self) -> int:
        return self.turn_state.retrieved_chunks if self.turn_state else 0

    @property
    def rag_trace(self) -> dict | None:
        return self.turn_state.rag_trace if self.turn_state else None

    @property
    def used_tool(self) -> bool:
        return bool(self.turn_state and self.turn_state.invocations)


def _all_steps_done(messages: Sequence[Any]) -> bool:
    """严格 DONE 判据：最新一条对话消息**以** [DONE] 结尾。

    为什么不用 `TextMentionTermination(DONE_MARKER)`：它检查消息里**任意位置**是否出现该串，
    而 `[DONE]` 这个串本身就写在 Agent 的 system prompt 里。实测中 Agent 复述规则
    （"...才在最后单独一行写 [DONE]"）就会误触发终止，导致三步链路在第二步被截断，
    尽管那条消息的进度自检明明写着"未完成"。

    改成「必须出现在末尾」后，复述规则不再误杀，只有真正收尾才终止。
    """
    for message in reversed(messages):
        text = _message_text(message)
        if text is None:
            continue
        return text.rstrip().endswith(DONE_MARKER)
    return False


def _explicit_handoff(
    messages: Sequence[Any], participant_names: Sequence[str]
) -> str | None:
    """读取最新专家消息末尾的严格交接控制行。

    只接受已注册专家，并拒绝把任务交回给当前发言者。自然语言里偶然提到
    ``report_agent`` 不算交接，避免 selector 因正文中的名册或示例继续空转。
    """
    latest: TextMessage | None = None
    for message in reversed(messages):
        if isinstance(message, TextMessage) and message.source != "user":
            latest = message
            break
    if latest is None:
        return None

    match = _HANDOFF_PATTERN.search(latest.to_model_text())
    if match is None:
        return None
    registered = {name.lower(): name for name in participant_names}
    target = registered.get(match.group("target").lower())
    if target is None or target == latest.source:
        return None
    return target


def _selector_turn_complete(
    messages: Sequence[Any], participant_names: Sequence[str]
) -> bool:
    """专家已经给出文本且没有合法交接时立即结束当前回合。

    ``[DONE]`` 仍是正常协议，但不再是唯一逃生口。供应商偶尔漏写控制行时，
    一条完整答复应当被视为最终答复，而不是触发下一次选人和重复生成。
    """
    if _all_steps_done(messages):
        return True
    has_agent_text = any(_message_text(message) is not None for message in messages)
    if not has_agent_text:
        return False
    return _explicit_handoff(messages, participant_names) is None


def _message_text(message: Any) -> str | None:
    """取一条对话消息的纯文本；不是对话消息（如工具事件）返回 None。

    只看 TextMessage 且**排除用户消息**：工具调用事件、流式分片都不该参与终止判断；
    用户消息也不该——AutoGen 把 task 字符串转成 TextMessage(source="user") 放进消息列表，
    如果用户输入恰好以 [DONE] 结尾，不排除就会在首轮误判为「全部步骤完成」，
    导致编排零轮终止、用户得不到任何回复。
    """
    if isinstance(message, TextMessage) and message.source != "user":
        return message.to_model_text()
    return None


def strip_done_marker(text: str) -> str:
    """剥掉终止标记，用户不该看到它。

    标记可能出现在末尾或独占一行，两种都处理；剥完再 strip 一次避免留下空行。
    """
    cleaned = _DONE_PATTERN.sub("", text)
    cleaned = cleaned.replace(f"\n{DONE_MARKER}\n", "\n").replace(DONE_MARKER, "")
    return cleaned.strip()


def strip_scaffolding(text: str) -> str:
    """把一条 Agent 回答剥成纯粹给用户看的正文。

    去掉三样东西：模型的思考块、终止标记，以及「进度自检」清单及其之后的内容。
    自检清单按约定写在回答末尾，所以从它开始截断即可。

    思考块**必须先剥**：模型在 `<think>` 里复述规则时会写出「进度自检」「[DONE]」
    这些字样（`_all_steps_done` 的注释记的就是同一类误触发），先截断就会把后面
    真正的正文一起丢掉。
    """
    _, text = split_think_blocks(text)
    cut = text.find(SELF_CHECK_HEADER)
    if cut != -1:
        text = _drop_trailing_rule(text[:cut])
    text = _HANDOFF_PATTERN.sub("", text)
    return strip_done_marker(text)


_TRAILING_RULE = re.compile(r"(?:\s*\n)?[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*\s*$")
# 末尾**正在长成**的分隔线：`-` 是一个个到达的，凑够三个才算数。
# 所以只要末行全是 -/*/_ 就先扣住：后面跟正文立刻放行，跟脚手架就一并截掉。
_PENDING_RULE = re.compile(r"(?:\s*\n)?[ \t]*[-*_]+[ \t]*$")


def _drop_trailing_rule(text: str) -> str:
    """去掉正文末尾那条孤零零的 markdown 分隔线。

    模型习惯在「进度自检」前面加一条 `---` 当分隔。截断点在自检标记上，
    分隔线就留在了用户正文末尾——它本来是脚手架的一部分，不是答复的一部分。
    只在紧邻截断点时去，正文中间的分隔线不动。
    """
    return _TRAILING_RULE.sub("", text).rstrip()


def _first_sentinel(buffer: str) -> int | None:
    """缓冲区里最早出现的脚手架标记位置；没有则 None。"""
    hits = [pos for pos in (buffer.find(s) for s in _SCAFFOLD_SENTINELS) if pos != -1]
    return min(hits) if hits else None


def _held_back(buffer: str) -> int:
    """末尾有多少个字符必须先扣住不发。

    两种情况要扣：

    1. 可能是某个标记被切断的前半截（完整出现的标记已由 `_first_sentinel` 处理，
       所以这里只需考虑长度 1..len(标记)-1 的真前缀）；
    2. 前半截**之前**的空白——标记按约定前面隔着空行（`…结论。\\n\\n进度自检：`），
       而分片切在 `…结论。\\n\\n进度自` 这种位置是常态。这时空白既不在缓冲区末尾、
       也不属于标记，若不一并扣住就会先发出去，等标记补齐再截断已经晚了，
       用户正文末尾会留下多余空行。
    """
    hold = len(buffer) - len(buffer.rstrip())
    body = buffer[: len(buffer) - hold] if hold else buffer

    if (rule := _PENDING_RULE.search(body)) is not None:
        hold = max(hold, len(buffer) - rule.start())
        body = body[: rule.start()]

    for sentinel in _SCAFFOLD_SENTINELS:
        for size in range(min(len(sentinel) - 1, len(body)), 0, -1):
            if body.endswith(sentinel[:size]):
                head = body[:-size]
                # 连分隔线一起扣住：它跟空白一样，先发出去就再也收不回来了
                hold = max(hold, len(buffer) - len(_drop_trailing_rule(head)))
                break
    return hold


def _visible(parts: list[ReasoningPart]) -> str:
    """只取 ThinkTagParser 的正文通道，内部推理永久丢弃。"""
    return "".join(value for channel, value in parts if channel == "content")


class AnswerStreamSanitizer:
    """流式正文净化器：边流边滤掉编排脚手架。

    为什么不能对每个 delta 分片单独做 `strip_scaffolding`：分片是按 token 切的，
    `进度自检` 完全可能被切成 `进度自` + `检：`，任何单片替换都匹配不上，
    标记照样漏进用户正文（实测 `[DONE]` 就是这么漏出去的）。

    所以做成有状态的：
    - 缓冲区里出现完整标记 → 发出标记之前的部分，其余整条消息全部丢弃；
    - 缓冲区末尾**可能**是标记的前半截 → 扣住那几个字符，等下一片再判断；
    - 一条消息结束（`flush`）→ 把扣住的尾巴补发，并重置状态迎接下一位专家。
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._suppressed = False
        self._think = ThinkTagParser()
        self._narrated = NarratedReasoningFilter()

    def feed(self, chunk: str) -> str:
        """喂进一个分片，返回可以安全发给用户的部分（可能是空串）。"""
        if self._suppressed:
            return ""
        # 思考块先剥，理由同 strip_scaffolding：<think> 里复述规则写出的
        # 「进度自检」会误触发下面的截断。ThinkTagParser 同样是有状态的
        # （`<think>` 也会被切成 `<th` + `ink>`），与标记缓冲逻辑正交。
        # reasoning 通道绝不能缓存、返回或记录。此前这里把它累积后经 thinking SSE
        # 原样发给浏览器，既泄漏内部推理，也造成无上限前端状态增长。
        self._buffer += self._narrated.feed(_visible(self._think.feed(chunk)))
        if not self._buffer:
            return ""

        cut = _first_sentinel(self._buffer)
        if cut is not None:
            # 标记之后整条消息都丢弃，所以这里可以放心 rstrip：
            # 不 rstrip 会把「结论。」与「进度自检」之间那个空行留给用户。
            emitted = _drop_trailing_rule(self._buffer[:cut])
            self._buffer = ""
            self._suppressed = True
            return emitted

        hold = _held_back(self._buffer)
        if hold == 0:
            emitted, self._buffer = self._buffer, ""
        else:
            emitted, self._buffer = self._buffer[:-hold], self._buffer[-hold:]
        return emitted

    def flush(self) -> str:
        """一条消息结束：吐出扣住的尾巴并重置。

        尾巴末尾的空白不发——它要么本来就该被标记吃掉，要么是消息末尾的空行，
        两种情况下用户都不需要它。段落间距由调用方在专家之间统一补。

        思考块解析器也要重置：下一位专家是全新一条消息，不能继承上一条的
        `in_reasoning` 状态，否则上一条若以未闭合的 `<think>` 结束，
        下一位专家的正文会被整段当成思考丢掉。
        """
        self._buffer += self._narrated.feed(_visible(self._think.flush()))
        self._buffer += self._narrated.flush()
        pending, self._buffer = self._buffer, ""
        self._suppressed = False
        self._think = ThinkTagParser()
        self._narrated = NarratedReasoningFilter()
        return pending.rstrip()

@dataclass
class Orchestration:
    """一次回合用的团队，外加两个必须由调用方负责的把手。

    - `stop`：外部终止开关。调用方提前退出（前端断连）时 `set()`，
      团队会在下一个消息边界干净收尾，不再启动后续步骤。
    - `model_client`：每回合新建，所以也必须每回合关闭，否则每个请求泄漏一个
      httpx 连接池。
    """

    team: Team
    stop: ExternalTermination
    model_client: ChatCompletionClient
    route: RouteResult


@dataclass(frozen=True)
class OrchestrationMetadata:
    framework: str
    strategy: str
    flow_name: str | None
    route_reason: str


async def build_orchestration(
    *,
    turn: TurnInput,
    user_id: str | None,
    use_rag: bool = True,
    use_memory: bool = True,
    config: ResolvedAIConfig | None = None,
) -> Orchestration:
    """组装一次会话用的编排团队。

    每次请求新建而不是全局单例：memory 绑定了 user_id，团队状态也按会话隔离。
    构造开销很小（不发网络请求），换来的是彻底避免跨用户串数据。

    config 透传给 build_model_client：不传时用服务端 env 默认值；
    传了客户端的 provider_config 解析结果时，编排链路（selector + 领域 Agent）
    全部使用该请求解析出的配置。
    """
    config = config or resolve_ai_config()
    route = await choose_route(turn, config)
    model_client = build_model_client(config)

    try:
        memory: list[Memory] = []
        if use_rag:
            memory.append(RagMemory(user_id=user_id))
        if use_memory and user_id:
            memory.append(PgVectorMemory(user_id=user_id))

        # `external` 平时永不触发，只有调用方主动 set() 才生效——用来在断连时喊停。
        external = ExternalTermination()
        if route.strategy == "graph" and route.flow_name:
            team: Team = build_flow(
                route.flow_name,
                model_client=model_client,
                memory=memory,
                context_factory=turn.context,
                external_termination=external,
            )
        else:
            team = _build_selector_team(
                model_client=model_client,
                memory=memory,
                context_factory=turn.context,
                external=external,
            )
    except Exception:
        await _close_quietly(model_client)
        raise
    return Orchestration(
        team=team,
        stop=external,
        model_client=model_client,
        route=route,
    )


def _build_selector_team(
    *,
    model_client: ChatCompletionClient,
    memory: list[Memory],
    context_factory,
    external: ExternalTermination,
) -> SelectorGroupChat:
    participants = build_domain_agents(
        model_client=model_client,
        memory=memory,
        context_factory=context_factory,
    )

    participant_names = [participant.name for participant in participants]
    max_turns = _SELECTOR_MAX_TURNS
    termination = (
        FunctionalTermination(
            lambda messages: _selector_turn_complete(messages, participant_names)
        )
        | MaxMessageTermination(max_turns + 1)
        | external
    )
    return SelectorGroupChat(
        participants=participants,
        model_client=model_client,
        selector_prompt=_SELECTOR_PROMPT,
        termination_condition=termination,
        max_turns=max_turns,
        allow_repeated_speaker=False,
        # 明确交接不再额外请求一次 selector 模型：既降低延迟，也杜绝调度器忽略点名。
        selector_func=lambda messages: _explicit_handoff(messages, participant_names),
        model_context=context_factory(),
    )


async def run_turn(
    turn: TurnInput,
    *,
    user_id: str | None,
    use_rag: bool = True,
    use_memory: bool = True,
    cancellation_token: CancellationToken | None = None,
    config: ResolvedAIConfig | None = None,
) -> OrchestrationResult:
    """跑完一个回合，返回最终答复与本回合产物。"""
    with user_scope(user_id):
        orchestration = await build_orchestration(
            turn=turn,
            user_id=user_id,
            use_rag=use_rag,
            use_memory=use_memory,
            config=config,
        )
        try:
            with turn_scope(trusted_tool_arguments=turn.trusted_tool_arguments) as state:
                result: TaskResult = await orchestration.team.run(
                    task=TextMessage(content=turn.query, source="user"),
                    cancellation_token=cancellation_token,
                    output_task_messages=False,
                )
            return _to_result(result, state, orchestration)
        finally:
            await _close_quietly(orchestration.model_client)


async def stream_turn(
    turn: TurnInput,
    *,
    user_id: str | None,
    use_rag: bool = True,
    use_memory: bool = True,
    cancellation_token: CancellationToken | None = None,
    config: ResolvedAIConfig | None = None,
) -> AsyncGenerator[Any, None]:
    """流式版本：逐条 yield AutoGen 消息，最后 yield 一个 OrchestrationResult。

    调用方（事件桥）负责把 AutoGen 消息翻译成现有的 SSE 事件。

    调用方没消费完就退出（前端断连）时走 `_abandon`，见那里的说明。
    """
    with user_scope(user_id):
        orchestration = await build_orchestration(
            turn=turn,
            user_id=user_id,
            use_rag=use_rag,
            use_memory=use_memory,
            config=config,
        )
        yield OrchestrationMetadata(
            framework="autogen",
            strategy=orchestration.route.strategy,
            flow_name=orchestration.route.flow_name,
            route_reason=orchestration.route.reason,
        )
        stream = orchestration.team.run_stream(
            task=TextMessage(content=turn.query, source="user"),
            cancellation_token=cancellation_token,
            output_task_messages=False,
        )
        drained = False
        try:
            with turn_scope(trusted_tool_arguments=turn.trusted_tool_arguments) as state:
                final: TaskResult | None = None
                async for item in stream:
                    if isinstance(item, TaskResult):
                        final = item
                    else:
                        yield item
                drained = True
                if final is not None:
                    yield _to_result(final, state, orchestration)
        finally:
            if drained:
                await _close_quietly(orchestration.model_client)
            else:
                _abandon(stream, orchestration)


# 后台排空的兜底上限。正常情况下在飞的那个工具跑完就结束，
# 取最慢工具（detect/segment 各 300s）再留一点余量。
_DRAIN_TIMEOUT_SECONDS = 420.0

# 持有后台排空任务的强引用：asyncio 只保存弱引用，不持有的话任务可能被 GC 掉，
# 收尾逻辑就跑不完了。
_DRAINS: set[asyncio.Task] = set()


def _abandon(stream: AsyncIterator[Any], orchestration: Orchestration) -> None:
    """调用方提前退出（前端断连）时的收尾。

    ## 为什么是「外部终止 + 后台排空」而不是「取消 token」

    直觉上应该 `cancellation_token.cancel()` 把在飞的工具也掐掉。实测不行：
    AutoGen 0.7.5 的 `ChatAgentContainer.handle_request` 用的是 `except Exception`，
    而 `CancelledError` 继承自 `BaseException`——取消异常从这个 handler 里漏出去，
    容器既不发 `GroupChatError` 也不收尾，`_process_publish` 与它的 `_on_message`
    就永远停在那儿。实测四种收尾方式：

    | 做法                    | 在飞工具 | 后续步骤 | 永久残留任务 |
    | ----------------------- | -------- | -------- | ------------ |
    | 什么都不做（改动前）    | 跑到底   | **继续** | 0            |
    | token.cancel()          | 取消     | 停       | **5**        |
    | token.cancel() + 排空   | 取消     | 停       | **2**        |
    | 外部终止 + 排空（本实现）| 跑到底   | 停       | **0**        |

    AutoGen 已进入 maintenance mode，这个上游缺陷不会有修复，所以选唯一不泄漏的那条。
    代价是**已经在跑**的那个工具会跑完——它本来就有自己的超时上限，是有界的；
    而泄漏的任务会随断连次数无限累积，无界的那个更危险。

    收益仍然是主要的：跨领域链路里断连后**不再启动后续步骤**。用户在三步链路的
    第一步就走掉时，省下的是第二、三步。

    ## 为什么排空要放到后台任务里

    排空要等在飞的工具跑完（可能几分钟）。放在 `finally` 里同步 await，
    会把生成器的关闭卡住那么久。丢到后台任务，断连立刻返回，收尾自己慢慢做。
    """
    orchestration.stop.set()

    async def drain() -> None:
        try:
            await asyncio.wait_for(_consume(stream), timeout=_DRAIN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "编排流排空超过 %.0fs 仍未结束，放弃等待", _DRAIN_TIMEOUT_SECONDS
            )
        except Exception:
            logger.debug("编排流排空时出错（调用方已断开，不影响响应）", exc_info=True)
        finally:
            await _close_quietly(orchestration.model_client)

    task = asyncio.create_task(drain())
    _DRAINS.add(task)
    task.add_done_callback(_DRAINS.discard)


async def _consume(stream: AsyncIterator[Any]) -> None:
    async for _ in stream:
        pass


async def _close_quietly(model_client: ChatCompletionClient) -> None:
    """关掉模型客户端。

    每回合新建一个 `OpenAIChatCompletionClient`，它自带一个 httpx 连接池；
    不关的话每个聊天请求泄漏一个连接池，最后耗尽文件描述符。
    """
    try:
        await model_client.close()
    except Exception:
        logger.debug("关闭模型客户端时出错", exc_info=True)


def _extract_usage(model_client: ChatCompletionClient) -> dict | None:
    """从模型客户端取本回合累计 token 用量（AutoGen 在 total_usage 里累计）。

    防御性读取：autogen 不同版本/端点的 total_usage 形态不一，任一缺失返回 None
    （上层回落到不写 usage，与旧行为一致），不再静默把 tokens_in/out 写成 NULL。
    """
    try:
        usage = model_client.total_usage
        if callable(usage):
            usage = usage()
    except Exception:
        return None
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    prompt = prompt or 0
    completion = completion or 0
    if not (prompt or completion):
        return None
    return {
        "input_tokens": prompt,
        "output_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _merge_usage(*items: dict | None) -> dict | None:
    input_tokens = sum(int(item.get("input_tokens", 0) or 0) for item in items if item)
    output_tokens = sum(int(item.get("output_tokens", 0) or 0) for item in items if item)
    if not (input_tokens or output_tokens):
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _to_result(
    result: TaskResult, state: TurnToolState, orchestration: Orchestration
) -> OrchestrationResult:
    # 取**全部**专家的正文而不是最后一条：跨领域链路里每位专家各产出一段真实结论，
    # 只留最后一条等于把前面几步的结果从落库正文里删掉——而用户在流式过程中看到过它们，
    # 刷新页面后却消失，前后不一致。
    parts: list[str] = []
    for message in result.messages:
        if not isinstance(message, TextMessage) or message.source == "user":
            continue
        cleaned = strip_scaffolding(message.to_model_text())
        if cleaned:
            parts.append(cleaned)
    content = "\n\n".join(parts)
    return OrchestrationResult(
        content=content,
        messages=list(result.messages),
        turn_state=state,
        stop_reason=result.stop_reason,
        usage=_merge_usage(
            orchestration.route.usage,
            _extract_usage(orchestration.model_client),
        ),
        map_target=(state.map_target if state else None),
        framework="autogen",
        strategy=orchestration.route.strategy,
        flow_name=orchestration.route.flow_name,
        route_reason=orchestration.route.reason,
    )


def participant_names() -> list[str]:
    return ["general_agent", *[spec.name for spec in domain_specs()]]
