# Agent-RS

Agent-RS 是一个面向遥感影像分析的 AI 助手应用。它可以完成日常对话、资料问答、联网查询、影像上传预览，以及基于上传影像计算 NDVI 植被指数。

项目适合用于遥感影像初步分析、影像结果快速预览、知识资料辅助问答，以及把常见分析工具接入到统一的 AI 工作流中。

## 主要能力

- 对话问答：支持普通问答、长文本整理、资料总结和流式回复。
- 知识增强：可选接入数据库，用于文档检索、记忆和上下文补充。
- 联网查询：配置搜索服务后，可按需查询实时资料。
- 影像管理：支持 GeoTIFF 上传、压缩处理、原图预览和结果图层展示。
- NDVI 计算：上传多光谱影像后，可计算并展示 NDVI 结果图层。

## 环境准备

需要提前准备：

- Python 3.11+
- Node.js 18+
- Docker Desktop：用于 NDVI 工具容器
- PostgreSQL 15+：仅在启用知识库、记忆或历史持久化时需要

## 1. 配置后端环境

在项目根目录创建或修改 `backend/.env`：

```env
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_API_KEY=your_api_key
AI_DEFAULT_MODEL=qwen3.7-max
AI_THINKING_BUDGET=1024

TAVILY_API_KEY=your_tavily_key
AGENT_PLANNING_MODEL=qwen3.6-flash

DATABASE_ENABLED=false
DATABASE_URL=postgresql://user:pass@localhost:5432/chatbot

IMAGERY_UPLOAD_DIR=storage/imagery
IMAGERY_MAX_FILE_BYTES=500000000
IMAGERY_WORKING_MAX_DIMENSION=4096
IMAGERY_PREVIEW_MAX_DIMENSION=2048

NDVI_MCP_IMAGE=ndvi-mcp:0.1.0
NDVI_MCP_USE_DOCKER=true
NDVI_MCP_ALLOW_LOCAL_FALLBACK=true
NDVI_MCP_MEMORY_LIMIT=2g
NDVI_MCP_CPUS=2
NDVI_MCP_NETWORK=none
```

说明：

- `AI_API_KEY` 是必填项，否则后端无法调用模型。
- 不需要知识库时，保持 `DATABASE_ENABLED=false` 即可。
- `DATABASE_URL` 中的 `chatbot` 可以只是本地数据库名，不影响项目名称。
- 生产环境建议设置 `NDVI_MCP_ALLOW_LOCAL_FALLBACK=false`，让 NDVI 工具失败时明确报错。

## 2. 构建 NDVI 工具镜像

首次使用 NDVI 计算前，在项目根目录执行：

```powershell
docker build -t ndvi-mcp:0.1.0 docker/ndvi
```

如果暂时不使用 NDVI，可以先跳过这一步。

## 3. 启动后端

推荐从项目根目录启动，固定使用 `3000` 端口：

```powershell
conda activate chatbot
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 3000 --reload --reload-exclude storage/* --reload-exclude storage/**/*
```

也可以进入 `backend` 后启动：

```powershell
conda activate chatbot
python -m uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

这里的 Conda 环境名 `chatbot` 只是本机环境名称，可以按自己的实际环境调整。

## 4. 启动前端

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```

前端默认地址通常是：

```text
http://localhost:5173
```

后端接口地址是：

```text
http://localhost:3000/api
```

## 5. 使用流程

1. 打开前端页面。
2. 在设置中确认后端接口地址为 `/api/chat` 或 `http://localhost:3000/api/chat`。
3. 输入普通问题，可直接对话。
4. 上传 GeoTIFF 影像后，地图会显示原图预览图层。
5. 输入“计算 NDVI”等请求，系统会基于已上传影像生成 NDVI 结果图层。
6. 原图预览和 NDVI 结果是两个独立图层，可分别查看。

## 6. 可选数据库配置

如需启用知识库、记忆和会话持久化：

```env
DATABASE_ENABLED=true
DATABASE_URL=postgresql://user:pass@localhost:5432/chatbot
```

然后执行数据库初始化脚本：

```powershell
cd backend
python sql/apply.py
```

## 7. 验证命令

```powershell
python -m compileall -q backend/app backend/sql docker/ndvi
python -m pytest backend/tests -q
npm --prefix frontend run build
```

前端构建时如果提示地图相关文件较大，通常是地图组件依赖导致，不影响正常运行。
