"""回合级工具状态：产物收集 + GPU 配额。

## 要解决的两个问题

**1. 产物怎么回到前端。**
AutoGen 工具的返回值是给模型看的文本。但本项目的工具还会产出 `geospatial_result`
（地图图层）和 `tool_result`（执行详情），这些要经 SSE 回到前端渲染，不能塞进给模型的
文本里（会把上下文撑爆，也会诱导模型复述图层元数据）。

AutoGen 工具与最终响应之间隔着模型循环，所以用回合级 contextvar 收集产物，
编排层在回合结束时取走。

**2. 贵的工具要单独限流。**
`AGENT_MAX_TOOL_ITERATIONS` 控制的是「模型能连续要几轮工具」，轻工具串 5 步只是秒级；
但 detect/segment 是 GPU 重任务，串两个就可能到分钟级，单次 HTTP 请求扛不住；
联网检索则是**按次计费**的外部 API。所以这两类按回合单独记次数，超了就
**返回一段说明文本而不是抛异常**——让模型自己收敛到"我已经做了检测，分割这一步
建议下一轮再来"，而不是整条链路炸掉。

配额必须**先占后用**（`try_reserve`），不能等工具跑完再记账：AutoGen 一个回合里的
多个工具调用是 `asyncio.gather` **并行**执行的（`_assistant_agent.py:1200`），
"执行前查计数、执行后加计数"这种写法下，同时发起的 detect 与 segment 会双双通过检查，
配额形同虚设——而并行跑两个 GPU 任务恰恰是最该拦的情况。

两者都必须是**回合级**而非全局：并发请求各自独立计数。contextvar 天然满足。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Iterator

from app.agent.types import ToolRunResult
from app.core.settings import get_settings

# 需要 GPU 的重工具。与工具注册表里的 Agent 所有权正交：
# 领域是「归谁管」，这里是「跑起来多贵」。
GPU_HEAVY_TOOLS: frozenset[str] = frozenset({"detect_objects", "segment_landcover"})

# 联网检索工具名。按次计费，所以和 GPU 工具一样要按回合限次。
WEB_SEARCH_TOOL = "web_search"

# 配额桶：工具名 -> 桶名。GPU 那几个**共用**一个桶（detect + segment 合计不超上限），
# 检索自己一个桶。不在表里的工具不限次。
_QUOTA_BUCKETS: dict[str, str] = {
    **{name: "gpu" for name in GPU_HEAVY_TOOLS},
    WEB_SEARCH_TOOL: "web_search",
}


def _bucket_limit(bucket: str) -> int:
    settings = get_settings()
    if bucket == "gpu":
        return settings.agent_max_gpu_tool_calls
    return settings.agent_web_search_max_calls


@dataclass(frozen=True)
class ToolInvocation:
    """一次工具执行的完整记录（给编排层组装响应用）。"""

    name: str
    arguments: dict
    result: ToolRunResult


@dataclass
class TurnToolState:
    invocations: list[ToolInvocation] = field(default_factory=list)
    # 桶名 -> 本回合已占用的次数。见模块文档「先占后用」。
    reservations: dict[str, int] = field(default_factory=dict)
    # 检索侧产物。Memory 实现在 update_context() 里写入，编排层回合结束时取走塞进 SSE。
    # 与工具产物同理：AutoGen 的 Memory 协议没有返回值通道，只能靠回合级状态传递。
    retrieved_chunks: int = 0
    rag_trace: dict | None = None
    # 回合级检索缓存：来源 key + query -> MemoryQueryResult。
    # 同一回合里 Agent 每次模型调用前都会触发 memory.update_context()，而
    # 检索词（最新用户消息）在回合内不变——不缓存的话，一次多步工具循环
    # 会对同一句话重复做 embedding + 混合检索 + rerank 好几次，纯烧延迟和费用。
    retrieval_cache: dict = field(default_factory=dict)
    # 「对话控图」目标：look_at_location 工具写入，编排层取走发 map_control 事件。
    map_target: dict | None = None
    # UI-originated parameters are trusted request context.  They override model
    # arguments for the named tool so an LLM cannot silently expand a selected ROI.
    trusted_tool_arguments: dict[str, dict] = field(default_factory=dict)

    def arguments_for(self, tool_name: str, arguments: dict) -> dict:
        trusted = self.trusted_tool_arguments.get(tool_name)
        return {**arguments, **trusted} if trusted else arguments

    def record_retrieval(self, *, retrieved_chunks: int, trace: dict | None) -> None:
        self.retrieved_chunks += retrieved_chunks
        if trace:
            self.rag_trace = {**(self.rag_trace or {}), **trace}

    def record(self, invocation: ToolInvocation) -> None:
        self.invocations.append(invocation)

    def try_reserve(self, tool_name: str) -> bool:
        """执行前占一个配额名额。占不到返回 False，调用方据此拒绝执行。

        同步方法，中间没有 await，所以在单线程事件循环里对并行的工具调用是原子的——
        这正是它必须先于执行的原因。
        """
        bucket = _QUOTA_BUCKETS.get(tool_name)
        if bucket is None:
            return True
        used = self.reservations.get(bucket, 0)
        if used >= _bucket_limit(bucket):
            return False
        self.reservations[bucket] = used + 1
        return True

    def release(self, tool_name: str) -> None:
        """把占而未用的名额还回去（如工具在鉴权阶段就被拒，根本没真跑）。"""
        bucket = _QUOTA_BUCKETS.get(tool_name)
        if bucket is None:
            return
        self.reservations[bucket] = max(0, self.reservations.get(bucket, 0) - 1)

    @property
    def gpu_calls(self) -> int:
        return self.reservations.get("gpu", 0)

    def quota_limit(self, tool_name: str) -> int | None:
        bucket = _QUOTA_BUCKETS.get(tool_name)
        return None if bucket is None else _bucket_limit(bucket)

    @property
    def succeeded(self) -> list[ToolInvocation]:
        return [i for i in self.invocations if i.result.error is None]

    def latest_geospatial_result(self) -> dict | None:
        """最后一个成功产出的地图图层。前端一次只渲染一个主结果。"""
        for invocation in reversed(self.succeeded):
            if invocation.result.geospatial_result:
                return _as_plain_dict(invocation.result.geospatial_result)
        return None

    def latest_tool_result(self) -> dict | None:
        for invocation in reversed(self.succeeded):
            if invocation.result.tool_result:
                return _as_plain_dict(invocation.result.tool_result)
        return None


def _as_plain_dict(value):
    """把产物统一成可 JSON 序列化的 dict。

    现有 runner 全部返回 dict（如 `tools/ndvi/runner.py:62`），但
    `ToolRunResult.geospatial_result` 的类型标注是 `GeospatialResult | None`——
    那是个 Pydantic 联合类型，runner **合法地**返回模型实例也说得通。
    真那样时 `sse_event` 的 `json.dumps` 会直接抛 TypeError，
    表现为流式响应末尾突然变成 error 事件（实测踩到过）。
    这里统一归一，让下游（SSE 与持久化，后者签名就写着 dict）永远拿到 dict。
    """
    if value is None or isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    return value


_turn_state: ContextVar[TurnToolState | None] = ContextVar("turn_tool_state", default=None)


def current_turn_state() -> TurnToolState | None:
    return _turn_state.get()


def set_turn_state(state: TurnToolState | None) -> Token[TurnToolState | None]:
    return _turn_state.set(state)


def reset_turn_state(token: Token[TurnToolState | None]) -> None:
    _turn_state.reset(token)


@contextmanager
def turn_scope(
    *, trusted_tool_arguments: dict[str, dict] | None = None
) -> Iterator[TurnToolState]:
    """一个回合的工具状态作用域。编排层在处理一次用户消息时包住整个链路。

    **按值保存/恢复，刻意不用 Token。** 这个作用域会被用在 async generator 里
    （流式 SSE 链路），而 async generator 每次被恢复时运行在不同的 Context 中，
    `ContextVar.reset(token)` 会抛
    `ValueError: <Token ...> was created in a different Context`。
    实测中这个异常发生在 finally 里，把整个流式响应变成了 error 事件。

    `set()` 没有这个限制，所以改成先记住旧值、结束时再 set 回去。
    """
    previous = _turn_state.get()
    state = TurnToolState(
        trusted_tool_arguments={
            name: dict(values) for name, values in (trusted_tool_arguments or {}).items()
        }
    )
    _turn_state.set(state)
    try:
        yield state
    finally:
        _turn_state.set(previous)
