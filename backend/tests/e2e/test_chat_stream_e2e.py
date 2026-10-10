"""C1：HTTP 流式端到端测试（真实路由 + 真实 ChatService + 真实工具执行管线）。

覆盖评测与单元测试都绕过的完整生产路径：
POST /api/chat(stream=true) → 鉴权/持久化 → 心跳包装 → AutoGen 编排 → 工具执行管线
（可用性→参数校验→归属鉴权→tool_jobs 登记→staging→runner→终态落库）→ SSE 事件契约 → 落库。

被替换的层（其余全部真实）：
1. 上游 LLM 的 HTTP 层：本地起一个 OpenAI 兼容假服务器回放固定的 tool_call 脚本
   （主 Agent 开了 model_client_streaming，请求带 stream=true，因此假服务器按 SSE chunk 返回）。
2. Docker 传输层：monkeypatch ``RSToolsMCPClient.call_tool``，raster_inspect 不再 `docker run`，
   而是用独立子进程直接调用仓库里的生产 compute 代码 ``docker/rs_tools/compute_raster_inspect.py``
   （该文件不在阶段 A 的指数 runner 改动集内，避免与并行修复冲突）。
   SAM3 GPU 服务保持不可用：segment_instances 走真实 runner 后如实返回 service_unavailable，
   且配额名额已被占用——这正是断言"第 2 次 GPU 调用被配额拒绝"所需的前置状态。
3. 心跳间隔：路由默认 15s，通过 monkeypatch 把 stream_with_heartbeat 绑定为 0.05s，
   让本地工具耗时（人为 sleep + 真实 compute）稳定超过心跳间隔，制造静默期内的 keepalive。

数据库：本模块独占的物理测试库 agent_rs_test_e2e（共享 agent_rs_test 会被并行的其他 pytest
进程在用例间隙 TRUNCATE/写入，与本模块跨越真实 HTTP 的长用例互相污染，实测踩到）。
PostgreSQL 不可达时**显式 fail**（不静默 skip）并输出建库指引——端到端契约一旦静默跳过，
"真实路径回归"就形同虚设；确要排除本组时用 `-m "not e2e"` 显式 deselect。
影像：走真实上传路由 POST /api/imagery/upload 生成（working.tif/metadata.json/DB 行俱全）。

断言清单（工作单 C1）：
- SSE 依次出现 tool_call（tool_requested/…started）、tool_result（tool_execution_completed）、done；
  done 里带 geospatial_result；静默期出现 keepalive 注释（工具耗时超过心跳间隔）。
- 工具内读到的 conversation_id 非空（tool_jobs 行的 conversation_id == SSE meta 里的会话 ID）。
- GPU 配额：第 2 次 segment_instances 被拒（tool_quota_exceeded / execution_status=rejected，
  且被拒调用发生在 tool_jobs 登记之前——库里只有一条 segment job 行）。
- UI ROI 覆盖模型参数：模型给了一个远离影像的错误 bbox，tool_jobs 落库的是 UI 传入的 bbox。
- generate_report 成功：done.geospatial_result.type == "report"，.docx 文件真实存在。
- 客户端中途断开（真实 uvicorn socket，ASGITransport 无法产生 http.disconnect）：
  tool_job 进入终态 interrupted（cancelled/outcome_unknown），恢复 worker 不重跑。

关于断开用例的状态断言：`mark_job_interrupted` 写 'cancelled'（runner 启动前取消）或
'outcome_unknown'（runner 已启动后取消）。本地存储后端下 job 登记与 runner 启动之间没有任何
await 点，"取消恰好落在登记之后、runner 之前"不可确定性构造，因此断言两种终态皆可、
但必须是与状态配对的错误码。不可重领性在本用例内用**真实 claim_stale_job 直接证明**
（stale_after=0 领空独占库，断言本 job 从未被领；另有
tests/agent/test_tool_jobs.py::test_interrupted_job_is_not_reopened_or_claimed 单元锁定）。

回归守卫（旧版心跳包装）：使用 `tests/e2e/legacy_heartbeat.py` 中的故障样本
stream_with_heartbeat（每次 anext 新建 Task、不共享 Context），跑同一场景必须观察到
"流式丢失上下文"P0 症状（conversation_id 丢失、配额失效、trusted ROI 丢失、报告失败）。
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from tests.e2e.legacy_heartbeat import stream_with_heartbeat as _LEGACY_STREAM_WITH_HEARTBEAT

import httpx
import numpy as np
import pytest
import pytest_asyncio
import rasterio
import uvicorn
from fastapi import Request
from fastapi.responses import StreamingResponse
from rasterio.transform import from_origin

from app.api.routes.chat import stream_with_heartbeat as _CURRENT_STREAM_WITH_HEARTBEAT
from app.core.paths import resolve_project_path
from app.core.settings import get_settings
from app.db import pool as db_pool_module
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient
from tests.conftest import _BUSINESS_TABLES
from tests.db_isolation import db_name, ensure_test_database, resolve_test_dsn, with_dbname

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.e2e]

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
RS_TOOLS_DIR = REPO_ROOT / "docker" / "rs_tools"

HEARTBEAT_INTERVAL_SECONDS = 0.05
HAPPY_TOOL_DELAY_SECONDS = 0.4
DISCONNECT_TOOL_DELAY_SECONDS = 2.5
SYNTHETIC_SIZE = 32
SYNTHETIC_BAND_COUNT = 4
MODEL_NAME = "e2e-fake-model"

# 模型自作主张的选区：远离影像，必须被 UI 传入的 ROI 覆盖。
MODEL_WRONG_BBOX = [100.0, 0.0, 101.0, 1.0]
# "当前影像"触发 use_current_selection，trusted imagery_id 注入；不含 12 位 hex/检索类词，
# 且不匹配 direct_roi_target 的窄模式（不走直连建筑提取路径）。
USER_QUERY = "请对当前影像完成一次质检，随后分割建筑目标，最后汇总生成报告。"

INTERRUPTED_STATUSES = {"cancelled", "outcome_unknown"}

# 场景驱动需要在函数内部安装 monkeypatch（按场景选择心跳实现），由各用例注入夹具。
_MONKEYPATCH_HOLDER: dict = {}


# ───────────────────────── 本地 compute 传输层（替换 docker run，不替换计算本身） ─────────────────────────
_TRANSPORT: dict = {"delay_seconds": HAPPY_TOOL_DELAY_SECONDS, "compute_calls": [], "imagery_id": None}

_COMPUTE_SNIPPET = (
    "import json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from compute_raster_inspect import inspect\n"
    "print(json.dumps(inspect(input_path=sys.argv[2])))\n"
)


async def _local_compute_call_tool(self, tool_name, *, source_path, output_dir=None, arguments=None):
    """独立调用副本：直接跑仓库里的 compute_raster_inspect（生产代码），不经 Docker、不经 mcp_server。

    人为 delay 让工具耗时稳定超过心跳间隔（C1 要求的静默期）。
    """
    if _TRANSPORT["delay_seconds"]:
        await asyncio.sleep(_TRANSPORT["delay_seconds"])
    if tool_name != "raster_inspect":
        raise MCPCallError(f"e2e local transport only wires raster_inspect, got {tool_name}")
    _TRANSPORT["compute_calls"].append(tool_name)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        _COMPUTE_SNIPPET,
        str(RS_TOOLS_DIR),
        str(source_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise MCPCallError(f"local compute failed: {err.decode(errors='replace')[:500]}")
    return json.loads(out.decode())


# ───────────────────────── 上游 LLM 假服务器（OpenAI 兼容，回放固定 tool_call 脚本） ─────────────────────────
def _tool_call_deltas(call_id: str, name: str, payload: dict) -> list[dict]:
    return [
        {"role": "assistant", "content": None},
        {"tool_calls": [{"index": 0, "id": call_id, "type": "function",
                         "function": {"name": name, "arguments": ""}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(payload)}}]},
    ]


class FakeUpstreamLLM:
    """按对话进度回放固定响应：质检 → 分割(错误bbox) → 分割重试(同参) → 报告 → 最终文本。

    主 Agent 开启 model_client_streaming，请求 stream=true → 以 chat.completion.chunk SSE 返回；
    非流式请求按完整 JSON 返回。另实现 /v1/embeddings 供消息向量后台任务使用。
    segment 两次调用都显式带 imagery_id（模型从清单读到后重试，符合真实模型行为），
    使"配额是否生效"与"trusted ROI 是否覆盖模型参数"在两种心跳实现下都可观测。
    """

    def __init__(self) -> None:
        from fastapi import FastAPI

        self.app = FastAPI()
        self._register()

    def _register(self) -> None:
        # Request/StreamingResponse 必须用模块级导入：本模块启用了 `from __future__ import
        # annotations`，函数内局部导入会让 FastAPI 解析不到注解，把 request 当成查询参数（422）。
        @self.app.post("/v1/chat/completions")
        async def chat_completions(request: Request):
            body = await request.json()
            deltas, finish = self._script(body)
            if body.get("stream"):
                return StreamingResponse(self._sse(deltas, finish), media_type="text/event-stream")
            message: dict = {"role": "assistant"}
            for delta in deltas:
                for key, value in delta.items():
                    if key == "tool_calls":
                        message["tool_calls"] = value
                    elif value not in (None, ""):
                        message.setdefault(key, value)
            return {
                "id": "chatcmpl-e2e",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model") or MODEL_NAME,
                "choices": [{"index": 0, "finish_reason": finish, "message": message}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }

        @self.app.post("/v1/embeddings")
        async def embeddings(request: Request):
            body = await request.json()
            count = max(1, len(body.get("input") or []))
            dims = int(body.get("dimensions") or 1536)
            return {
                "object": "list",
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.0] * dims} for i in range(count)
                ],
                "model": body.get("model") or "e2e-embedding",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }

    def _script(self, body: dict) -> tuple[list[dict], str]:
        imagery_id = _TRANSPORT.get("imagery_id") or ""
        tool_results = [m for m in (body.get("messages") or []) if m.get("role") == "tool"]
        step = len(tool_results)
        if step == 0:
            deltas = _tool_call_deltas(
                f"e2e-call-{step}", "raster_inspect", {"imagery_id": imagery_id, "reason": "e2e 质检"}
            )
            return deltas, "tool_calls"
        if step in (1, 2):
            # step1 带远离影像的错误 bbox（必须被 UI ROI 覆盖）；step2 原样重试。
            payload = {"imagery_id": imagery_id, "concepts": ["building"]}
            if step == 1:
                payload["bbox"] = list(MODEL_WRONG_BBOX)
                payload["bbox_crs"] = "EPSG:4326"
            return _tool_call_deltas(f"e2e-call-{step}", "segment_instances", payload), "tool_calls"
        if step == 3:
            return _tool_call_deltas(f"e2e-call-{step}", "generate_report", {}), "tool_calls"
        return ([{"role": "assistant", "content": ""}, {"content": "e2e: 分析与报告已完成。"}], "stop")

    @staticmethod
    async def _sse(deltas: list[dict], finish: str):
        for delta in deltas:
            yield _chunk_line(delta, None)
        yield _chunk_line({}, finish)
        yield b"data: [DONE]\n\n"


def _chunk_line(delta: dict, finish) -> bytes:
    chunk = {
        "id": "chatcmpl-e2e",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": MODEL_NAME,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(chunk)}\n\n".encode()


# ───────────────────────── 合成 GeoTIFF（期望值来自本函数手造的数据，非被测实现推导） ─────────────────────────
def _band_values(band_index: int, rows: int, cols: int) -> np.ndarray:
    """确定性像元值：100 + 10*band + (row % 7) + (col % 5)。"""
    row_pattern = np.arange(rows).reshape(-1, 1) % 7
    col_pattern = np.arange(cols).reshape(1, -1) % 5
    return (100 + 10 * band_index + row_pattern + col_pattern).astype(np.uint16)


def synthetic_geotiff_bytes() -> bytes:
    import io

    buffer = io.BytesIO()
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        height=SYNTHETIC_SIZE,
        width=SYNTHETIC_SIZE,
        count=SYNTHETIC_BAND_COUNT,
        dtype="uint16",
        crs="EPSG:32650",  # 投影坐标系、2 米像元：通过 segment 的分辨率门槛（≤5 m）
        transform=from_origin(500000.0, 4400000.0, 2.0, 2.0),
    ) as dst:
        for band in range(1, SYNTHETIC_BAND_COUNT + 1):
            dst.write(_band_values(band, SYNTHETIC_SIZE, SYNTHETIC_SIZE), band)
        dst.set_band_description(1, "blue")
        dst.set_band_description(2, "green")
        dst.set_band_description(3, "red")
        dst.set_band_description(4, "nir")
    return buffer.getvalue()


def expected_band_stats(band_index: int) -> dict:
    """独立于被测实现的期望统计量（直接对本测试手造的数组计算）。"""
    values = _band_values(band_index, SYNTHETIC_SIZE, SYNTHETIC_SIZE).astype(np.float64)
    return {
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "std": float(values.std()),
    }


# ───────────────────────── 心跳包装注入 ─────────────────────────
def install_heartbeat_wrapper(monkeypatch, wrapper=None) -> None:
    """把路由使用的 stream_with_heartbeat 换成短间隔版本（不修改工作区 chat.py 的内容）。

    wrapper 传入固定的旧版故障样本即可复现历史缺陷做回归对比。
    路由在请求时全局查找该名字，monkeypatch 模块属性即可生效。
    """
    from app.api.routes import chat as chat_route

    impl = wrapper or _CURRENT_STREAM_WITH_HEARTBEAT
    monkeypatch.setattr(
        chat_route,
        "stream_with_heartbeat",
        functools.partial(impl, interval_seconds=HEARTBEAT_INTERVAL_SECONDS),
    )


# ───────────────────────── SSE 解析 ─────────────────────────
def parse_sse(raw: str) -> tuple[list[tuple[str, dict]], int]:
    events: list[tuple[str, dict]] = []
    keepalives = 0
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        if block.lstrip().startswith(":"):
            keepalives += 1
            continue
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        if name is not None:
            events.append((name, json.loads(data) if data else {}))
    return events, keepalives


def status_events(events: list[tuple[str, dict]], stage: str, tool: str) -> list[dict]:
    return [
        data
        for name, data in events
        if name == "agent_status" and data.get("status") == stage and data.get("tool_name") == tool
    ]


def event_index(events: list[tuple[str, dict]], predicate) -> int:
    for index, (name, data) in enumerate(events):
        if predicate(name, data):
            return index
    return -1


# ───────────────────────── HTTP 辅助 ─────────────────────────
async def upload_synthetic_imagery(app) -> dict:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/imagery/upload",
            files={"file": ("e2e_synthetic.tif", synthetic_geotiff_bytes(), "image/tiff")},
        )
    assert response.status_code == 200, response.text
    return response.json()


def chat_payload(imagery_id: str, roi: list[float]) -> dict:
    return {
        "messages": [{"role": "user", "content": USER_QUERY}],
        "stream": True,
        "model": MODEL_NAME,
        "use_memory": False,
        "use_rag": False,
        "analysis_roi": {"kind": "geo", "bbox": roi},
        "metadata": {"active_imagery_id": imagery_id, "analysis_source": "selected_imagery"},
    }


def center_roi(bounds: list[float]) -> list[float]:
    """UI 选区：影像 WGS84 四至的中心一半（独立于被测代码计算）。"""
    west, south, east, north = bounds
    cx, cy = (west + east) / 2, (south + north) / 2
    dx, dy = (east - west) / 4, (north - south) / 4
    return [cx - dx, cy - dy, cx + dx, cy + dy]


async def fetch_tool_job_rows(
    e2e_conn, *, user_id: str, conversation_id: str, imagery_id: str
) -> dict[str, list[dict]]:
    """按本用例自己的会话/影像圈定 job 行。

    只按 user_id 过滤会被共享同一测试库的并发测试运行（其他代理的 pytest 进程）写入的
    行干扰；conversation_id 与 imagery_id 都是本用例独有（新会话 + 刚上传的影像），
    旧版心跳包装下 conversation_id 为 NULL，则退回用 imagery_id 识别。
    """
    rows = await e2e_conn.fetch(
        """
        SELECT tool_name, status, error_code, arguments::text AS arguments,
               conversation_id::text, attempts
        FROM public.tool_jobs
        WHERE user_id = $1
          AND (conversation_id::text = $2 OR imagery_id = $3)
        ORDER BY created_at, id
        """,
        user_id,
        conversation_id,
        imagery_id,
    )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        item = dict(row)
        item["arguments"] = json.loads(item["arguments"] or "{}")
        grouped.setdefault(row["tool_name"], []).append(item)
    return grouped


# ───────────────────────── 夹具 ─────────────────────────
def e2e_database_dsn() -> str:
    """本模块独占的物理测试库（agent_rs_test_e2e）。

    共享 agent_rs_test 的其他 pytest 进程会在用例间隙 TRUNCATE/写入业务表，与本模块
    跨越真实 HTTP 流程的长用例并发时互相清掉/污染对方数据（实测踩到）。本模块单独建库。
    """
    base = resolve_test_dsn()
    return with_dbname(base, f"{db_name(base)}_e2e")


async def _truncate_business_tables(pool) -> None:
    """清空业务表（只清当前库中实际存在的，schema 漂移兜底；与全局 conftest 同一清单）。"""
    async with pool.acquire() as conn:
        existing = await conn.fetch(
            """
            SELECT quote_ident(table_schema) || '.' || quote_ident(table_name) AS fq
            FROM information_schema.tables
            WHERE (table_schema || '.' || table_name = ANY($1::text[]))
              AND table_type = 'BASE TABLE'
            """,
            list(_BUSINESS_TABLES),
        )
        names = [row["fq"] for row in existing]
        if names:
            await conn.execute(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_db():
    """session 级独立池 + 迁移。

    PostgreSQL 不可达时显式 fail（不静默 skip）并给出建库指引：本模块守卫的是
    评测/单测都绕不过的真实 HTTP 路径契约，静默 skip 会让它悄悄失去守卫。
    确要排除本组时必须显式 `-m "not e2e"` deselect（见 pyproject markers）。
    """
    try:
        import asyncpg
    except ImportError:  # pragma: no cover
        pytest.fail("e2e 需要 asyncpg（backend 依赖），当前环境未安装", pytrace=False)
    dsn = e2e_database_dsn()
    try:
        await ensure_test_database(dsn)
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
    except Exception as exc:
        pytest.fail(
            f"e2e 测试需要真实 PostgreSQL，但测试库不可达（{type(exc).__name__}: {exc}）。\n"
            f"请先在仓库根目录执行 `docker compose up -d db` 启动数据库，\n"
            f"并确认连接串可达：{dsn}\n"
            "（应用库 DSN 来自 backend/.env 的 DATABASE_URL；测试库默认由其派生\n"
            " agent_rs_test / agent_rs_test_e2e，也可用 TEST_DATABASE_URL 显式指定。）\n"
            '如需跳过端到端组，请显式使用 `-m "not e2e"`，不允许静默 skip。',
            pytrace=False,
        )
    from sql.apply import run_migrations

    async with pool.acquire() as conn:
        await run_migrations(conn, log=None)
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(loop_scope="session")
async def e2e_conn(e2e_db):
    async with e2e_db.acquire() as conn:
        yield conn


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def fake_llm_server():
    """session 级：一个假上游服务整个模块共用（端口稳定，后台 embedding 客户端不漂移）。"""
    fake = FakeUpstreamLLM()
    config = uvicorn.Config(fake.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(250):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started, "fake upstream LLM server failed to start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield SimpleNamespace(fake=fake, port=port)
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=10)


@pytest_asyncio.fixture(loop_scope="session")
async def e2e_stack(fake_llm_server, e2e_db, monkeypatch, tmp_path):
    """每用例：独占测试库配置 + 真实 create_app() + 本地 compute 传输。"""
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", e2e_database_dsn())
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AI_BASE_URL", f"http://127.0.0.1:{fake_llm_server.port}/v1")
    monkeypatch.setenv("AI_API_KEY", "e2e-test-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", MODEL_NAME)
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("AI_MAX_RETRIES", "0")
    monkeypatch.setenv("AGENT_AUTO_FLOW_ENABLED", "false")  # 关路由 LLM：脚本只回放主 Agent 分支
    monkeypatch.setenv("AGENT_MAX_GPU_TOOL_CALLS", "1")
    monkeypatch.setenv("MEMORY_JUDGE_ENABLED", "false")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("RS_TOOLS_DOCKER_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    get_settings.cache_clear()

    await db_pool_module.close_db_pool()  # 清掉可能存在的旧池（绑定别的 DSN/loop）
    monkeypatch.setattr(RSToolsMCPClient, "call_tool", _local_compute_call_tool)
    _TRANSPORT.update(delay_seconds=HAPPY_TOOL_DELAY_SECONDS, compute_calls=[], imagery_id=None)

    from app.main import create_app

    app = create_app()
    try:
        yield SimpleNamespace(app=app, fake=fake_llm_server.fake, port=fake_llm_server.port)
        await asyncio.sleep(1.5)  # 给消息 embedding 等后台任务排空时间（实测约 1s）
    finally:
        await db_pool_module.close_db_pool()
        await _truncate_business_tables(e2e_db)  # 独占库，用例间自清理
        get_settings.cache_clear()


# ───────────────────────── 场景驱动 ─────────────────────────
async def drive_tool_flow(e2e_stack, e2e_conn, *, heartbeat: str) -> dict:
    """跑完整流式场景并采集观测值（SSE 事件、keepalive、tool_jobs 行、消息行）。

    heartbeat: "current"=当前实现；"legacy"=固定旧版故障样本（回归对比用）。
    """
    install_heartbeat_wrapper(
        _MONKEYPATCH_HOLDER["monkeypatch"],
        wrapper=_LEGACY_STREAM_WITH_HEARTBEAT if heartbeat == "legacy" else None,
    )
    user_id = get_settings().default_user_id

    upload = await upload_synthetic_imagery(e2e_stack.app)
    imagery_id = upload["imagery_id"]
    _TRANSPORT["imagery_id"] = imagery_id  # 假模型从"清单"拿到 ID（真实模型行为）
    roi = center_roi(upload["bounds"])
    payload = chat_payload(imagery_id, roi)

    transport = httpx.ASGITransport(app=e2e_stack.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/chat", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events, keepalives = parse_sse(response.text)
    conversation_id = next(data["conversation_id"] for name, data in events if name == "meta")
    job_rows = await fetch_tool_job_rows(
        e2e_conn, user_id=user_id, conversation_id=conversation_id, imagery_id=imagery_id
    )
    messages = await e2e_conn.fetch(
        """
        SELECT id::text, role, status, metadata_json AS metadata
        FROM agent_rs.messages
        WHERE conversation_id::text = $1
        ORDER BY created_at
        """,
        conversation_id,
    )
    parsed_messages = []
    for row in messages:
        item = dict(row)
        metadata = item.get("metadata")
        item["metadata"] = json.loads(metadata) if isinstance(metadata, str) else (metadata or {})
        parsed_messages.append(item)
    return {
        "events": events,
        "keepalives": keepalives,
        "job_rows": job_rows,
        "messages": parsed_messages,
        "imagery_id": imagery_id,
        "roi": roi,
        "conversation_id": conversation_id,
        "raw": response.text,
    }


# ───────────────────────── 用例 1：完整工具链 happy path（C1 主断言） ─────────────────────────
async def assert_full_tool_flow_contract(obs: dict) -> None:
    events = obs["events"]
    names = [name for name, _ in events]
    conversation_id = obs["conversation_id"]

    # SSE 首个业务事件是 meta，末个事件是 done（协议终点）。
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert conversation_id  # 新建会话 ID 非空
    done = events[-1][1]

    def idx(stage: str, tool: str) -> int:
        return event_index(
            events,
            lambda name, data, s=stage, t=tool: (
                name == "agent_status" and data.get("status") == s and data.get("tool_name") == t
            ),
        )

    # 依次：tool_call（请求+开始）→ tool_result（完成）→ done。
    inspect_call = idx("tool_execution_started", "raster_inspect")
    inspect_result = idx("tool_execution_completed", "raster_inspect")
    assert 0 < inspect_call < inspect_result < names.index("done")
    assert idx("tool_requested", "raster_inspect") < inspect_call

    # GPU 配额：第 1 次 segment 真实执行后因 SAM3 服务不可用失败（名额已被占用），
    # 第 2 次被配额拒绝（rejected + tool_quota_exceeded），顺序在前一次失败之后。
    seg_failures = status_events(events, "tool_execution_failed", "segment_instances")
    assert [item.get("error_code") for item in seg_failures] == ["service_unavailable", "tool_quota_exceeded"]
    assert seg_failures[1].get("execution_status") == "rejected"
    assert idx("tool_execution_failed", "segment_instances") < idx("tool_execution_started", "generate_report")

    # generate_report 成功：完成事件 + done 带 report 图层结果 + 真实 .docx 文件。
    assert idx("tool_execution_completed", "generate_report") > idx("tool_execution_started", "generate_report")
    geo = done.get("geospatial_result")
    assert geo and geo.get("type") == "report"
    assert geo.get("imagery_id") == obs["imagery_id"]
    report_path = (
        resolve_project_path(get_settings().imagery_upload_dir)
        / obs["imagery_id"]
        / "results"
        / Path(geo["download_url"]).name
    )
    assert report_path.is_file() and report_path.stat().st_size > 0

    # 质检数值来自手造数据（独立期望值），宽度/波段数与上传一致。
    tool_result = done.get("tool_result")
    assert tool_result and tool_result["type"] == "raster_inspect"
    assert tool_result["width"] == SYNTHETIC_SIZE and tool_result["band_count"] == SYNTHETIC_BAND_COUNT
    stats = {item["band"]: item for item in tool_result["per_band_stats"]}
    for band in (1, SYNTHETIC_BAND_COUNT):
        expected = expected_band_stats(band)
        assert stats[band]["mean"] == pytest.approx(expected["mean"], abs=1e-3)
        assert stats[band]["min"] == pytest.approx(expected["min"], abs=1e-3)
        assert stats[band]["std"] == pytest.approx(expected["std"], abs=1e-3)

    # 工具静默期出现 keepalive：工具耗时超过了（缩短后的）心跳间隔。
    assert obs["keepalives"] >= 1

    # 正文 delta 在 done 之前出现。
    assert names.index("done") > next(i for i, n in enumerate(names) if n == "delta")

    # ── 数据库侧 ──
    rows = obs["job_rows"]
    inspect_rows = rows.get("raster_inspect", [])
    segment_rows = rows.get("segment_instances", [])
    report_rows = rows.get("generate_report", [])

    # 工具内读到的 conversation_id 非空：tool_jobs 行带本会话 ID。
    assert len(inspect_rows) == 1
    assert inspect_rows[0]["status"] == "complete"
    assert inspect_rows[0]["conversation_id"] == conversation_id

    # 配额拒绝发生在 job 登记之前：被拒的那次没有产生第二条 job 行。
    assert len(segment_rows) == 1
    assert segment_rows[0]["status"] == "failed"
    assert segment_rows[0]["error_code"] == "service_unavailable"

    # UI ROI 覆盖模型参数：落库 bbox 是 UI 选区，不是模型的错误 bbox。
    seg_args = segment_rows[0]["arguments"]
    assert seg_args["bbox"] == pytest.approx(obs["roi"])
    assert seg_args["bbox"] != pytest.approx(MODEL_WRONG_BBOX)

    assert len(report_rows) == 1 and report_rows[0]["status"] == "complete"
    assert report_rows[0]["conversation_id"] == conversation_id

    # 流式 assistant 消息持久化为 complete，且带 geospatial_result 元数据。
    assistant = [m for m in obs["messages"] if m["role"] == "assistant"]
    assert assistant and assistant[-1]["status"] == "complete"
    persisted_geo = (assistant[-1]["metadata"] or {}).get("geospatial_result")
    assert persisted_geo and persisted_geo.get("type") == "report"


async def test_chat_stream_full_tool_flow_over_real_route(e2e_stack, e2e_conn, monkeypatch):
    _MONKEYPATCH_HOLDER["monkeypatch"] = monkeypatch
    obs = await drive_tool_flow(e2e_stack, e2e_conn, heartbeat="current")
    await assert_full_tool_flow_contract(obs)


async def run_full_tool_flow(e2e_stack, e2e_conn, monkeypatch, *, heartbeat: str = "current") -> None:
    """供外部（旧包装回归证明）以指定心跳实现运行同一份契约断言。"""
    _MONKEYPATCH_HOLDER["monkeypatch"] = monkeypatch
    obs = await drive_tool_flow(e2e_stack, e2e_conn, heartbeat=heartbeat)
    await assert_full_tool_flow_contract(obs)


# ───────────────────────── 用例 2：客户端中途断开 → job 终止且不被恢复 worker 重跑 ─────────────────────────
async def test_client_disconnect_cancels_tool_job_and_recovery_worker_skips_it(
    e2e_stack, e2e_conn, monkeypatch
):
    from app.agent.tool_jobs import recover_one_stale_job, run_tool_job_worker
    from app.db.repositories.tool_job import claim_stale_job, get_tool_job

    install_heartbeat_wrapper(monkeypatch)  # 短间隔心跳：静默期产生 keepalive，也加速断开检测
    _TRANSPORT["delay_seconds"] = DISCONNECT_TOOL_DELAY_SECONDS
    user_id = get_settings().default_user_id

    upload = await upload_synthetic_imagery(e2e_stack.app)
    imagery_id = upload["imagery_id"]
    _TRANSPORT["imagery_id"] = imagery_id
    payload = chat_payload(imagery_id, center_roi(upload["bounds"]))

    # ASGITransport 无法产生 http.disconnect，断开语义必须走真实 socket。
    config = uvicorn.Config(
        e2e_stack.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(250):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]

    conversation_id = None
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
        async with client.stream("POST", "/api/chat", json=payload) as response:
            assert response.status_code == 200
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                if conversation_id is None:
                    match = re.search(r'"conversation_id"\s*:\s*"([^"]+)"', buffer)
                    if match:
                        conversation_id = match.group(1)
                tool_started = (
                    '"status": "tool_execution_started"' in buffer
                    and '"tool_name": "raster_inspect"' in buffer
                )
                if tool_started and ": keepalive" in buffer.rsplit('"tool_execution_started"', 1)[1]:
                    break  # 工具已静默（超过心跳间隔）→ 模拟客户端断开

    assert conversation_id, "未从 SSE meta 事件捕获 conversation_id"

    # 等待取消链路把 in-flight job 写成终态（cancelled / outcome_unknown）。
    # 按本会话过滤：共享测试库的其他并发测试运行不产生干扰。
    job_row = None
    for _ in range(300):
        job_row = await e2e_conn.fetchrow(
            """
            SELECT id::text, status, error_code, attempts, conversation_id::text
            FROM public.tool_jobs
            WHERE tool_name = 'raster_inspect' AND user_id = $1 AND conversation_id::text = $2
            ORDER BY created_at DESC LIMIT 1
            """,
            user_id,
            conversation_id,
        )
        if job_row and job_row["status"] not in ("pending", "running"):
            break
        await asyncio.sleep(0.05)
    assert job_row is not None, "断开后未找到 raster_inspect 的 tool_jobs 行"
    print(
        f"\n[disconnect] tool_job 终态: status={job_row['status']} "
        f"error_code={job_row['error_code']} attempts={job_row['attempts']}"
    )
    assert job_row["status"] in INTERRUPTED_STATUSES, job_row
    expected_code = "tool_cancelled" if job_row["status"] == "cancelled" else "tool_outcome_unknown"
    assert job_row["error_code"] == expected_code
    assert job_row["attempts"] == 1
    # 断开链路里上下文仍然完整：job 行带本会话 ID。
    assert job_row["conversation_id"] == conversation_id
    # 取消发生在工具人为静默期内，compute 尚未执行。
    assert _TRANSPORT["compute_calls"] == []

    # ── 不可重领的直接证明（C1 修正意见 1）──
    # 用真实 claim_stale_job 验证，而不是只查状态字段：stale_after_seconds=0 时
    # 任何仍处 pending/running 的 job 都会被立即领走（心跳再新鲜也超时）；
    # 循环领空整个独占库并断言本 job 的 id 从未被领过、attempts 未被 claim 累加。
    claimed_ids: list[str] = []
    for _ in range(10):
        claimed = await claim_stale_job(e2e_conn, stale_after_seconds=0)
        if claimed is None:
            break
        claimed_ids.append(claimed["id"])
    assert job_row["id"] not in claimed_ids, (
        f"断开取消的 tool_job（{job_row['status']}）被 claim_stale_job 重领: {job_row['id']}"
    )
    unclaimed = await get_tool_job(e2e_conn, job_id=job_row["id"])
    assert unclaimed["status"] == job_row["status"]
    assert unclaimed["attempts"] == 1

    # 流式 assistant 消息被标记失败（Stream interrupted），不留 streaming 状态。
    assistant_failed = False
    for _ in range(200):
        row = await e2e_conn.fetchrow(
            """
            SELECT status FROM agent_rs.messages
            WHERE conversation_id::text = $1 AND role = 'assistant'
            ORDER BY created_at DESC LIMIT 1
            """,
            conversation_id,
        )
        if row and row["status"] == "failed":
            assistant_failed = True
            break
        await asyncio.sleep(0.05)
    assert assistant_failed, "断开后 assistant 消息未被标记为 failed"

    # 恢复 worker：跑足够一轮轮询，终态 job 不得被领取重跑。
    monkeypatch.setenv("TOOL_JOBS_POLL_INTERVAL_SECONDS", "1")
    get_settings.cache_clear()
    stop = asyncio.Event()
    worker = asyncio.create_task(run_tool_job_worker(stop))
    await asyncio.sleep(2.2)
    stop.set()
    await asyncio.wait_for(worker, timeout=5)

    assert await recover_one_stale_job() is None
    after = await get_tool_job(e2e_conn, job_id=job_row["id"])
    assert after["status"] == job_row["status"]
    assert after["attempts"] == 1
    assert _TRANSPORT["compute_calls"] == []  # 没有任何重跑

    server.should_exit = True
    await asyncio.wait_for(server_task, timeout=10)


# ───────────────────────── 用例 3：旧版心跳包装回归守卫（C1 回归价值） ─────────────────────────
async def test_legacy_heartbeat_wrapper_loses_request_context(e2e_stack, e2e_conn, monkeypatch):
    """固定旧版 stream_with_heartbeat（每次 anext 新建 Task）跑同一场景，必须复现 P0 症状：
    会话上下文丢失（job 行 conversation_id 为空）、trusted ROI 丢失（模型的错误选区未被覆盖，
    直接被 invalid_roi 前置拒绝）、回合配额失效（第 2 次 segment 本应被配额拒绝却被真实执行）、
    报告拿不到会话而失败（done 无 geospatial_result）。
    """
    _MONKEYPATCH_HOLDER["monkeypatch"] = monkeypatch
    obs = await drive_tool_flow(e2e_stack, e2e_conn, heartbeat="legacy")

    rows = obs["job_rows"]
    all_rows = [row for group in rows.values() for row in group]
    # 症状 1：所有工具 job 行的 conversation_id 均为空（conversation_scope 在心跳 Task 间丢失）。
    assert all_rows, "旧包装下应仍有工具 job 行"
    assert all(row["conversation_id"] is None for row in all_rows)

    # 症状 2：trusted ROI 丢失 + 配额失效。
    # 第一次 segment：模型自拟的错误 bbox 未被 UI ROI 覆盖，直接被 invalid_roi 前置拒绝
    # （analysis_precondition，不产生 job 行）；第二次 segment（模型未传 bbox，也没有 trusted
    # 注入，bbox=None）：配额完全失效——本应被 tool_quota_exceeded 拒绝的调用被真实执行，
    # 落了一条 job 行并因 SAM3 不可用失败。
    segment_rows = rows.get("segment_instances", [])
    failed_codes = [
        data.get("error_code")
        for name, data in obs["events"]
        if name == "agent_status"
        and data.get("status") == "tool_execution_failed"
        and data.get("tool_name") == "segment_instances"
    ]
    assert failed_codes == ["analysis_precondition", "service_unavailable"]
    assert "tool_quota_exceeded" not in failed_codes
    assert len(segment_rows) == 1
    # 落库 bbox 既不是 UI 选区也没有模型错误 bbox（模型未传、trusted 注入丢失）。
    assert segment_rows[0]["arguments"].get("bbox") is None
    assert segment_rows[0]["arguments"].get("bbox") != pytest.approx(obs["roi"])

    # 症状 4：generate_report 读不到会话上下文而失败；done 不带 geospatial_result。
    assert obs["events"][-1][0] == "done"
    assert "geospatial_result" not in obs["events"][-1][1]
    report_failed = status_events(obs["events"], "tool_execution_failed", "generate_report")
    assert report_failed and report_failed[0].get("error_code") == "no_conversation"
