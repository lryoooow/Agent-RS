# Chatbot Python

一个全栈 AI 聊天机器人系统，支持多管道路由、RAG 知识库、联网搜索、用户记忆和流式对话。

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (React + Vite + Tailwind)                     │
│  SSE Streaming / Chat / Knowledge / Memory / Auth       │
└────────────────────────┬────────────────────────────────┘
                         │ /api
┌────────────────────────▼────────────────────────────────┐
│  Request Router                                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐ │
│  │Direct Chat│  │ RAG QA   │  │ Web Search + Agent    │ │
│  │(短链路)   │  │(检索增强) │  │(联网搜索)             │ │
│  └──────────┘  └──────────┘  └───────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│  Context Assembly / Prompt Engine / Memory / Rerank     │
├─────────────────────────────────────────────────────────┤
│  LLM Provider (OpenAI-compatible API)                   │
└─────────────────────────────────────────────────────────┘
```

## 核心特性

- **多管道路由** — 请求前置分类，简单对话走短链路（跳过 RAG/Memory），复杂问题走完整管线
- **联网搜索** — Tavily API 集成，规则分类 + 轻量模型决策 + 决策缓存 + 结果缓存
- **RAG 知识库** — 文档上传（PDF/DOCX/TXT + OCR）、分块、向量嵌入、混合检索、Rerank、MMR
- **用户记忆** — 自动提取对话中的关键信息，后续对话中召回
- **流式响应** — SSE 实时推送，支持 thinking 状态、搜索状态、逐字输出
- **认证系统** — JWT + Session，多用户隔离
- **Thinking Budget** — 主模型推理预算控制，平衡质量与速度

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + Vite + Tailwind CSS + Lucide Icons |
| 后端 | FastAPI + Uvicorn + Pydantic |
| LLM | OpenAI-compatible API (Qwen3.7-Max / Qwen3.6-Flash) |
| 向量检索 | PostgreSQL + pgvector + 混合 RRF |
| 嵌入 | text-embedding-v4 (DashScope) |
| 重排 | gte-rerank-v2 (DashScope) |
| 联网搜索 | Tavily API |
| 文档解析 | pypdf + python-docx + pytesseract (OCR) |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+ (可选，启用 RAG/Memory 时需要)

### 安装

```bash
# 后端
cd backend
pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env 填入 API Key

# 前端
cd ../frontend
npm install
```

### 启动

```bash
# 后端 (端口 3000)
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload

# 前端 (端口 5173，自动代理 /api 到后端)
cd frontend
npm run dev
```

### 使用 Conda

```bash
conda activate chatbot
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

## 关键配置 (.env)

```env
# LLM 主模型
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_API_KEY=your_key
AI_DEFAULT_MODEL=qwen3.7-max
AI_THINKING_BUDGET=1024

# 联网搜索
TAVILY_API_KEY=your_key
AGENT_PLANNING_MODEL=qwen3.6-flash

# 数据库 (启用 RAG/Memory)
DATABASE_ENABLED=true
DATABASE_URL=postgresql://user:pass@localhost:5432/chatbot

# 嵌入 & 重排
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
RERANK_MODEL=gte-rerank-v2
```

## 项目结构

```
├── frontend/                  React 前端
│   └── src/app/
│       ├── components/        UI 组件
│       ├── hooks/             状态管理
│       └── lib/               API 客户端
├── backend/                   FastAPI 后端
│   └── app/
│       ├── api/routes/        API 端点
│       ├── lib/ai/
│       │   ├── router.py      请求路由（短链路/完整管线）
│       │   ├── ai_service.py  AI 服务编排
│       │   ├── agents/        Agent Runtime + Web Search
│       │   ├── context/       上下文组装 + 预算管理
│       │   ├── prompting/     Jinja2 模板化提示词
│       │   ├── rag/           RAG 检索 + MMR
│       │   ├── embedding/     向量嵌入服务
│       │   └── rerank.py      重排服务
│       ├── lib/db/            数据库 + 向量检索
│       ├── lib/documents/     文档解析 + 分块
│       └── lib/auth/          认证
└── tests/                     测试套件
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 聊天（支持 stream: true/false） |
| GET | `/api/conversations` | 对话列表 |
| POST | `/api/documents/upload` | 上传文档 |
| GET | `/api/memories` | 用户记忆 |
| GET | `/api/health` | 健康检查 |

## 性能优化设计

1. **请求路由分流** — 简单消息跳过 RAG/Memory/Agent，直接 LLM 回答
2. **联网搜索决策** — 规则优先 → 缓存 → 轻量模型(thinking=off, max_tokens=3) → 大模型兜底
3. **Thinking Budget** — 限制主模型内部推理 token 数，减少等待时间
4. **搜索结果 Rerank** — 提升注入 LLM 的搜索内容相关性
5. **决策缓存 + 结果缓存** — 相同/相似问题不重复调用模型和搜索 API

## License

MIT
