# Agent-RS

Agent-RS 是一个面向遥感影像分析的 AI Agent 应用。项目由 React 前端、FastAPI 后端、上下文管线、联网搜索 Agent，以及 Docker MCP 封装的 NDVI 工具组成。当前支持普通对话、流式输出、RAG/Memory、GeoTIFF 上传预览、原图/NDVI 双图层展示，以及通过 MCP 工具计算 NDVI。

## 架构概览

```text
frontend/ React + Vite
  -> /api
backend/ FastAPI
  -> request router: direct_chat / full_pipeline
  -> context: history / memory / rag / imagery_inventory / tool_result
  -> agent runtime:
       web_search agent
       calculate_ndvi tool -> Docker MCP -> docker/ndvi/compute_ndvi.py
storage/
  -> imagery/{imagery_id}/source.tif
  -> imagery/{imagery_id}/working.tif
  -> imagery/{imagery_id}/metadata.json
  -> imagery/{imagery_id}/results/preview.png
  -> imagery/{imagery_id}/results/ndvi_colored.png
```

NDVI 计算当前按工具形态运行：后端优先通过 Docker 启动 MCP 服务并调用 `calculate_ndvi`，工具本身无状态；联网搜索是当前主要的子 Agent 能力。

## 环境要求

- Python 3.11+
- Node.js 18+
- Docker Desktop：计算 NDVI 时需要
- PostgreSQL 15+：仅在启用 RAG/Memory 数据库能力时需要

## 后端启动

推荐在项目根目录运行，后端固定使用 3000 端口：

```powershell
conda activate chatbot
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 3000 --reload --reload-exclude storage/* --reload-exclude storage/**/*
```

也可以进入 `backend` 后运行：

```powershell
conda activate chatbot
python -m uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

说明：这里的 Conda 环境名仍可继续使用原来的 `chatbot`，它只是本机环境名称，不影响项目对外名称。

## 前端启动

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```

前端默认 Vite 端口为 `5173`。

## NDVI Docker MCP 工具

构建镜像：

```powershell
docker build -t ndvi-mcp:0.1.0 docker/ndvi
```

关键配置：

```env
NDVI_MCP_IMAGE=ndvi-mcp:0.1.0
NDVI_MCP_USE_DOCKER=true
NDVI_MCP_ALLOW_LOCAL_FALLBACK=true
NDVI_MCP_MEMORY_LIMIT=2g
NDVI_MCP_CPUS=2
NDVI_MCP_NETWORK=none
```

生产环境建议：

```env
NDVI_MCP_ALLOW_LOCAL_FALLBACK=false
```

这样 Docker MCP 失败时会明确报错，不会静默回退到后端本地 Python 环境。

## 关键环境变量

```env
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_API_KEY=your_key
AI_DEFAULT_MODEL=qwen3.7-max
AI_THINKING_BUDGET=1024

TAVILY_API_KEY=your_key
AGENT_PLANNING_MODEL=qwen3.6-flash

DATABASE_ENABLED=false
DATABASE_URL=postgresql://user:pass@localhost:5432/chatbot

IMAGERY_UPLOAD_DIR=storage/imagery
IMAGERY_MAX_FILE_BYTES=500000000
IMAGERY_WORKING_MAX_DIMENSION=4096
IMAGERY_PREVIEW_MAX_DIMENSION=2048
```

`DATABASE_URL` 中的 `chatbot` 可以只是本地数据库名；如需更名，需要同步迁移数据库 schema 与连接配置。

## 常用接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/chat` | 对话，支持 `stream: true/false` |
| GET | `/api/config` | 前端运行配置 |
| GET | `/api/health` | 后端健康检查与关键运行配置状态 |
| POST | `/api/imagery/upload` | 上传 GeoTIFF |
| GET | `/api/imagery` | 影像列表 |
| GET | `/api/imagery/{imagery_id}` | 影像元数据 |
| DELETE | `/api/imagery/{imagery_id}` | 删除影像及结果 |
| POST | `/api/imagery/cleanup` | 清理过期影像残留目录 |
| GET | `/api/imagery/{imagery_id}/results/{filename}` | 获取预览图或 NDVI 结果图 |

## 验证命令

```powershell
python -m compileall -q backend/app docker/ndvi
python -m pytest backend/tests -q
npm --prefix frontend run build
```

当前 `MapPanel` 构建 chunk 较大主要来自 `maplibre-gl`。它已经被拆到独立 chunk；如果后续首屏性能成为问题，再进一步做地图区域按需加载。
