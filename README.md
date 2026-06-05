# Agent-RS

Agent-RS 是一个面向遥感影像分析的 AI 助手应用。支持日常对话、知识问答、联网查询、影像上传预览，以及基于上传影像计算 NDVI 植被指数。

## 主要能力

- 对话问答：普通问答、长文本整理、资料总结、流式回复
- 知识增强：可选接入数据库，用于文档检索、记忆和上下文补充
- 联网查询：通过 SearchChildAgent 按需查询实时资料
- 影像管理：GeoTIFF 上传、压缩处理、原图预览和结果图层展示
- NDVI 计算：通过 MCP Docker Tool 计算并展示 NDVI 结果图层

## 环境准备

- Python 3.11+
- Node.js 18+
- Docker Desktop（用于 NDVI 工具容器）
- PostgreSQL 15+（仅在启用知识库、记忆或历史持久化时需要）

## 1. 配置后端环境

在项目根目录创建或修改 `backend/.env`（参考 `backend/.env.example`）：

```env
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_API_KEY=your_api_key
AI_DEFAULT_MODEL=qwen3.7-max
AI_THINKING_BUDGET=1024

TAVILY_API_KEY=your_tavily_key
AGENT_PLANNING_MODEL=qwen3.6-flash

DATABASE_ENABLED=false
DATABASE_URL=postgresql://agent_rs:your_password@localhost:15432/agent_rs

IMAGERY_UPLOAD_DIR=storage/imagery
IMAGERY_MAX_FILE_BYTES=500000000
NDVI_MCP_IMAGE=ndvi-mcp:0.1.0
NDVI_MCP_USE_DOCKER=true
NDVI_MCP_NETWORK=none
```

说明：

- `AI_API_KEY` 是必填项，否则后端无法调用模型。
- 不需要知识库时，保持 `DATABASE_ENABLED=false` 即可。
- 生产环境建议设置 `NDVI_MCP_ALLOW_LOCAL_FALLBACK=false`。

## 2. 构建 NDVI 工具镜像

首次使用 NDVI 计算前，在项目根目录执行：

```bash
docker build -t ndvi-mcp:0.1.0 docker/ndvi
```

## 3. 启动后端

推荐使用 Conda 环境（名称可自定义，示例用 `agent-rs`）：

```bash
conda activate agent-rs
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 3000 --reload --reload-exclude "storage/*"
```

## 4. 启动前端

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

前端默认 http://localhost:5173，后端接口 http://localhost:3000/api。

## 5. 使用流程

1. 打开前端页面，确认后端接口地址为 `/api/chat`。
2. 输入普通问题，直接对话。
3. 上传 GeoTIFF 影像后，地图显示原图预览图层。
4. 输入"计算 NDVI"，系统基于已上传影像生成 NDVI 结果图层。

## 6. 可选数据库配置

启用知识库、记忆和会话持久化：

```env
DATABASE_ENABLED=true
DATABASE_URL=postgresql://agent_rs:your_password@localhost:15432/agent_rs
```

执行数据库初始化：

```bash
cd backend && python sql/apply.py
```

## 7. 验证

```bash
python -m compileall -q backend/app backend/sql docker/ndvi
python -m pytest backend/tests -q
npm --prefix frontend run build
```
