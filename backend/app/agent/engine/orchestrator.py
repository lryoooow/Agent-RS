"""顶层 AutoGen 编排：主 Agent 直跑 + GraphFlow 固定流水线。

Phase 4 之后只有两条路径：

- **main**：自由请求由单个主 Agent（持有全部工具）直接完成。多步任务在
  Agent 自己的工具循环里接力，不存在专家间的交棒。
- **graph**：完整命中标准作业的请求走固定 GraphFlow，顺序写死。

此前在这两者之上的 SelectorGroupChat（8 位平级专家 + selector 模型逐步选人
+ `[DONE]`/`[HANDOFF: xxx]`/「进度自检」交棒协议 + 约 300 行流式净化器）
已整体移除。那套机制的存在理由是"专家之间只能靠自然语言散文传递控制流"，
而控制流混进正文又必须靠正则再剥出来——标记被 token 切断、模型在 <think>
里复述规则、用户输入恰好以 [DONE] 结尾，每一类都真实咬过人。单主 Agent
的生命周期由自身工具循环（max_tool_iterations）自然界定，控制行没有
存在的前提。

流式正文仍然要过一道净化：`<think>` 推理块与叙述式推理旁白在任何架构下
都不能给用户看，且标签可能被切成 `<th` + `ink>`，所以解析器保持有状态、
跨分片（见 `AnswerStreamSanitizer`）。

**正文取全部消息而不是最后一条。** GraphFlow 路径里每位节点各产出一段结论，
只取最后一条会把前面几步的真实结果（"NDVI 均值 0.42"）从落库正文里丢掉，
用户刷新页面就看不到了——而流式过程中他明明看到过。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, AsyncIterator, Union

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import TaskResult, Team
from autogen_agentchat.conditions import ExternalTermination
from autogen_agentchat.messages import BaseChatMessage, TextMessage
from autogen_core import CancellationToken
from autogen_core.memory import Memory
from autogen_core.models import ChatCompletionClient

from app.agent.engine.agents import build_main_agent
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


def _visible(parts: list[ReasoningPart]) -> str:
    """只取 ThinkTagParser 的正文通道，内部推理永久丢弃。"""
    return "".join(value for channel, value in parts if channel == "content")


def _clean_final_text(text: str) -> str:
    """整条消息的净化：剥 <think> 块与叙述式推理旁白。

    单 Agent / 流内节点不再输出控制行，所以这就是全部的清理——
    此前的 strip_scaffolding（进度自检截断、[DONE]/[HANDOFF] 剥离、尾部分隔线
    处理）随交棒协议一起删除了。
    """
    _, visible = split_think_blocks(text)
    narrated = NarratedReasoningFilter()
    cleaned = narrated.feed(visible)
    cleaned += narrated.flush()
    return cleaned.strip()


class AnswerStreamSanitizer:
    """流式正文净化器：跨分片剥掉 `<think>` 推理块与叙述式推理旁白。

    为什么不能对每个 delta 分片单独做替换：分片是按 token 切的，
    `<think>` 完全可能被切成 `<th` + `ink>`，任何无状态的单片处理都会
    把半截推理漏进用户正文。ThinkTagParser 与 NarratedReasoningFilter
    都是有状态的，可以跨分片拼出完整标签再整体丢弃。

    一条消息结束（`flush`）时解析器重置：下一条消息是全新开始，
    不能继承上一条未闭合的 `<think>` 状态，否则下一位的正文会被
    整段当成思考丢掉。
    """

    def __init__(self) -> None:
        self._think = ThinkTagParser()
        self._narrated = NarratedReasoningFilter()

    def feed(self, chunk: str) -> str:
        """喂进一个分片，返回可以安全发给用户的部分（可能是空串）。"""
        # reasoning 通道绝不能缓存、返回或记录。此前它被累积后经 thinking SSE
        # 原样发给浏览器，既泄漏内部推理，也造成无上限前端状态增长。
        return self._narrated.feed(_visible(self._think.feed(chunk)))

    def flush(self) -> str:
        """一条消息结束：吐出解析器里扣住的尾巴并重置。

        尾巴末尾的空白不发——消息末尾的空行用户不需要，段落间距由调用方
        在消息之间统一补。
        """
        pending = self._narrated.feed(_visible(self._think.flush()))
        pending += self._narrated.flush()
        self._think = ThinkTagParser()
        self._narrated = NarratedReasoningFilter()
        return pending.rstrip()


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
    strategy: str = "main"
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


@dataclass
class Orchestration:
    """一次回合用的执行单元，外加调用方必须负责的把手。

    - `team`：GraphFlow（Team）或主 Agent（AssistantAgent）。两者的
      run/run_stream 事件形状同构，调用方无需区分。
    - `stop`：仅 GraphFlow 有——外部终止开关，前端断连时 set() 让团队停在
      下一个消息边界。主 Agent 没有后续步骤可停，断连后只需后台排空在飞
      调用并关闭客户端。
    - `model_client`：每回合新建，所以也必须每回合关闭，否则每个请求泄漏一个
      httpx 连接池。
    """

    team: Union[Team, AssistantAgent]
    stop: ExternalTermination | None
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
    """组装一次会话用的执行单元。

    每次请求新建而不是全局单例：memory 绑定了 user_id，团队状态也按会话隔离。
    构造开销很小（不发网络请求），换来的是彻底避免跨用户串数据。

    config 透传给 build_model_client：不传时用服务端 env 默认值；
    传了客户端的 provider_config 解析结果时，主 Agent / 流内节点 / 路由
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

        if route.strategy == "graph" and route.flow_name:
            external = ExternalTermination()
            team: Union[Team, AssistantAgent] = build_flow(
                route.flow_name,
                model_client=model_client,
                memory=memory,
                context_factory=turn.context,
                external_termination=external,
            )
            stop: ExternalTermination | None = external
        else:
            team = build_main_agent(
                model_client=model_client,
                memory=memory,
                context_factory=turn.context,
            )
            stop = None
    except Exception:
        await _close_quietly(model_client)
        raise
    return Orchestration(
        team=team,
        stop=stop,
        model_client=model_client,
        route=route,
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

    GraphFlow 路径用 `ExternalTermination` 喊停后续节点；主 Agent 路径没有
    "后续步骤"，断连后只需让在飞的工具跑完（它们有自己的超时上限）再关客户端。

    ## 为什么排空要放到后台任务里

    排空要等在飞的工具跑完（可能几分钟）。放在 `finally` 里同步 await，
    会把生成器的关闭卡住那么久。丢到后台任务，断连立刻返回，收尾自己慢慢做。
    """
    if orchestration.stop is not None:
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
    # 取**全部**节点的正文而不是最后一条：GraphFlow 路径里每个节点各产出一段
    # 真实结论，只留最后一条等于把前面几步的结果从落库正文里删掉——
    # 而用户在流式过程中看到过它们，刷新页面后却消失，前后不一致。
    parts: list[str] = []
    for message in result.messages:
        if not isinstance(message, TextMessage) or message.source == "user":
            continue
        cleaned = _clean_final_text(message.to_model_text())
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
