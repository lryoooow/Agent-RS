# Agent-RS Backend

Agent-RS 后端基于 FastAPI，负责对话接口、上下文组装、Agent 运行时、联网搜索、遥感影像上传，以及统一 RS Tools Docker MCP 工具调用。AI 层使用 OpenAI-compatible Provider 接口，可通过配置切换 DashScope、OpenAI、DeepSeek、Moonshot/Kimi 等服务。

## 启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

Windows Conda 环境可直接运行：

```powershell
conda activate agent-rs
python -m uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

`agent-rs` 只是推荐的 Conda 环境名，可按自己的环境实际名称调整。

## API

- `GET /api/health`
- `GET /api/config`
- `POST /api/chat`
- `POST /api/imagery/upload`
- `GET /api/imagery`
- `DELETE /api/imagery/{imagery_id}`
- `POST /api/imagery/cleanup`

`POST /api/chat` 接收 `messages`、可选 `model`、可选 `system_prompt`、可选 Provider 配置，以及 `stream`。后端拥有基础系统提示词；请求级 `system_prompt` 只作为当前对话的额外指令，不能替换基础规则。

Prompt 模板位于 `app/lib/ai/prompting/templates/`。通过 `AI_PROMPT_PROFILE` 选择激活的提示词 profile。渲染器只注入当前请求需要的模块，任务专用提示词不会无条件进入每次 Provider 请求。

## SSE 流式事件

前端默认发送 `stream: true`，并通过 `fetch()` + `ReadableStream` 读取响应。因为对话请求是 `POST` body，不能直接使用浏览器 `EventSource`。

示例：

```txt
event: meta
data: {"model":"qwen3.7-max","provider":"openai-compatible"}

event: analysis_status
data: {"status":"analyzing","label":"正在解析问题..."}

event: analysis_status
data: {"status":"preparing","label":"正在整理内容..."}

event: analysis_status
data: {"status":"answering","label":"正在组织回复..."}

event: delta
data: {"content":"你好"}

event: done
data: {"finish_reason":"stop"}
```

当 Provider 返回 `reasoning_content`、`reasoning`、`thinking`、`thought` 或显式 `<think>...</think>` 文本时，后端会从用户可见响应中剥离原始思考内容。流式客户端只接收安全的 `analysis_status` 进度事件和最终答案增量。

## 上下文与工具

后端在发送 Provider 请求前通过 `app/lib/ai/context/` 组装上下文。基础系统提示词、请求级额外指令、历史摘要、重要记忆、最近对话、RAG 片段、影像清单和工具结果拥有独立边界与预算；空的可选模块不会注入。

联网搜索走 Agent runtime 调度。配置 `TAVILY_API_KEY` 后，后端可以在需要时调用搜索 Agent，并把精简结果作为工具上下文注入最终回答。

遥感处理走统一 Docker MCP 工具。后端启动 `rs-tools-mcp:0.1.0` 镜像并调用 `calculate_ndvi`、`raster_inspect`、`calculate_spectral_index` 或 `render_band_composite`，工具无状态且不做本地兜底：

```env
RS_TOOLS_MCP_IMAGE=rs-tools-mcp:0.1.0
RS_TOOLS_MCP_USE_DOCKER=true
```

## 常用配置

```env
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_API_KEY=your_key
AI_DEFAULT_MODEL=qwen3.7-max

TAVILY_API_KEY=your_key
AGENT_WEB_SEARCH_MAX_CALLS=1
AGENT_WEB_SEARCH_MAX_RESULTS=5

RS_TOOLS_MCP_IMAGE=rs-tools-mcp:0.1.0
RS_TOOLS_MCP_USE_DOCKER=true
RS_TOOLS_MCP_MEMORY_LIMIT=2g
RS_TOOLS_MCP_CPUS=2
RS_TOOLS_MCP_NETWORK=none
```
