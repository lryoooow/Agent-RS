<div align="center">

<img src="docs/assets/logo-rsagent.png" alt="Agent-RS Logo" width="180" />

# Agent-RS

**基于 AutoGen 的遥感智能分析平台**

</div>

Agent-RS 把大模型、多 Agent 编排与容器化遥感算法连接起来。用户可上传 GeoTIFF，使用自然语言完成影像质检、光谱指数、目标检测、地物分类、裁剪重投影、报告生成等任务，并在 MapLibre 地图上查看结果图层。

> **使用限制：本项目不是开源软件。仅允许个人、非商业、本地学习与评估。未经项目权利人事先书面许可，禁止商业使用、对外提供服务、二次分发，以及使用本项目的代码、设计、数据、结果或衍生成果发表论文、预印本、学位论文、专利、项目申报或竞赛作品。发现违规使用，权利人将保留停止授权并依法追究责任的权利。完整条款见 [LICENSE](LICENSE)。**

## 本次更新（2026-08-12）

- **两层编排（AutoGen 0.7.5）**：标准作业走 `GraphFlow` 固定流水线，其余请求由持有全部工具的单主 Agent 直完成；联网搜索、地图定位、报告生成是所有 Agent 共有的共享工具，不再经过专家交棒。
- **原生工具接入**：现有遥感能力封装为 AutoGen `BaseTool`，MCP Docker 算法层保持隔离；RAG 与长期记忆通过 AutoGen Memory 协议注入。
- **推理泄漏防护**：后端在模型、AutoGen 事件、SSE、日志和持久化边界过滤原始 reasoning/`<think>` 内容。前端不显示“思考摘要”标题，只滚动展示“正在思考”“正在调用工具”“正在回复”等固定安全阶段词，光晕仅裁剪在文字内部。
- **终止与去重修复**：为 Agent 回合、工具次数、GPU 重工具和流式结束设置硬边界，拦截重复回复、无止境对话以及正文结束后 SSE 长时间不关闭的问题。
- **Tavily 联网搜索**：可使用服务端密钥，也可在前端设置中填写；密钥按请求传递，不进入提示词、日志、消息元数据或数据库。
- **ROI 地物分类**：地图框选区域后可直接执行“分类选区”；可信 ROI 由请求上下文传入，后端先裁剪栅格，再调用地物分割工具。
- **动态模型选择**：右上角模型名可下拉选择供应商 `/models` 返回的已拉取模型，并按创建时间优先展示较新模型。
- **30 天登录保持**：账号会话默认有效期调整为 30 天，本机浏览器在 Cookie 有效且未主动退出时可持续登录。
- **稳定性与安全加固**：增加模型结构化输出兼容回退、搜索输入脱敏、embedding 失败熔断、消息顺序修复、输出文件名隔离和前端地图包拆分。

## 架构

```text
用户请求
   │
   ▼
AutoGen 结构化路由 Agent
   ├── 完整标准作业 ──► GraphFlow
   └── 开放/不确定任务 ► main_agent（单主 Agent，全部工具）
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
       遥感领域 Agent      搜索 Agent       通用 Agent
             │                │
       AutoGen BaseTool     Tavily
             │
       MCP stdio / Docker
             │
       遥感算法与结果图层
```

业务代码通过 `backend/app/agent/engine/` 适配 AutoGen，避免在 API、存储和领域代码中散落框架调用。旧的自研 planner、单工具 runtime、JSON 规划解析器与 decision cache 已移除，不再存在双运行时。

## 主要能力

| 类别 | 能力 |
| --- | --- |
| 智能对话 | 流式 Markdown、多 Agent 协作、上下文压缩、长期记忆、文档 RAG |
| 联网搜索 | Tavily 查询改写、多轮检索、来源整理与调用次数限制 |
| 影像管理 | GeoTIFF 上传、压缩预览、图层开关、图例、ROI 框选 |
| 影像质检 | 尺寸、波段、坐标系、范围与像素统计 |
| 光谱分析 | NDVI、NDWI、MNDWI、NDBI、BSI、EVI、SAVI、MSAVI、GNDVI、NDMI、NBR |
| 栅格处理 | 真/假彩色合成、云影掩膜、水体掩膜、裁剪、重投影 |
| 深度学习 | PP-YOLOE-R 旋转框目标检测、U-Net/LandCover.ai 地物分割、ROI 地物分类 |
| 文档能力 | PDF、Word、PPT、Excel 解析，影像与扫描件 OCR，分析报告生成 |
| 多用户 | 开放注册、用户数据隔离、PBKDF2-SHA256 密码哈希、30 天会话 |

## 技术栈

- 后端：Python 3.11+、FastAPI、AutoGen AgentChat/Core/Ext 0.7.5、MCP
- 前端：React 18、TypeScript、Vite、Tailwind CSS、MapLibre GL
- 存储：PostgreSQL 16 + pgvector；本地文件或 MinIO 对象存储
- 算法：rasterio、NumPy、PaddleDetection、PyTorch、segmentation-models-pytorch
- 检索：向量召回 + 全文检索 + RRF + rerank + MMR

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop（本地 PostgreSQL 和遥感 MCP 工具需要；使用外部数据库并关闭 Docker 工具时可不启用）

### 1. 安装依赖

```bash
cp backend/.env.example backend/.env
uv sync --project backend
npm --prefix Agent-frontend ci
```

随后编辑 `backend/.env`，至少配置 `AUTH_SECRET_KEY`，并在后端环境变量或前端设置页提供可用的模型端点、API Key 与模型名。

### 2. 单终端启动

```bash
npm run dev
```

该命令会在 Docker 可用时启动并等待本地 PostgreSQL，然后在同一个终端启动 FastAPI 与 Vite；按 `Ctrl+C` 会同时停止前后端。数据库迁移由后端启动过程幂等执行。前端地址为 <http://localhost:5173>，后端地址为 <http://localhost:3000>。

如果 Docker 不可用，启动脚本会跳过本地数据库；此时需要让 `DATABASE_URL` 指向可访问的 PostgreSQL，或仅在无存储算子调试时设置 `DATABASE_ENABLED=false`。

## 必要配置

所有服务端配置均放在不入库的 `backend/.env`。仓库只提供无真实密钥的 `backend/.env.example`。

| 配置 | 是否必需 | 说明 |
| --- | --- | --- |
| `AI_BASE_URL` | 是 | OpenAI 兼容 API 根地址，例如 `https://api.openai.com/v1` |
| `AI_API_KEY` | 二选一 | 服务端模型密钥；留空时本地模式可从前端设置按请求提供 |
| `AI_DEFAULT_MODEL` | 是 | 默认模型；兼容 function calling 的模型才能完整使用 Agent 工具 |
| `AUTH_SECRET_KEY` | DB 模式必需 | 长随机串，公网部署前必须更换；可用 `openssl rand -hex 32` 生成 |
| `AUTH_SESSION_DAYS` | 否 | 默认 `30`，控制登录 Cookie 与服务端会话有效期 |
| `DATABASE_URL` | DB 模式必需 | PostgreSQL 连接串；示例值与 `docker-compose.yml` 对齐 |
| `TAVILY_API_KEY` | 搜索可选 | 服务端搜索密钥；也可在前端设置中填写，仅随当前请求传递 |
| `EMBEDDING_API_KEY` | RAG 可选 | 文档向量化和长期记忆；不可用时有熔断保护，不影响基础对话 |
| `RERANK_API_KEY` | rerank 可选 | 检索重排服务密钥 |
| `STORAGE_BACKEND` | 否 | `local` 或 `minio`；多实例部署建议 MinIO |
| `ALLOW_CLIENT_PROVIDER_CONFIG` | 否 | 本地默认 `true`；公网多用户部署建议设为 `false` 并锁定服务端模型配置 |
| `AUTH_COOKIE_SECURE` | 公网必需 | HTTPS 部署设为 `true` |

AutoGen 关键配置：

```env
AGENT_AUTO_FLOW_ENABLED=true
AGENT_ROUTER_MODEL=
AGENT_ROUTER_MAX_TOKENS=256
AGENT_MODEL_INFO=
AGENT_MAX_TOOL_ITERATIONS=5
AGENT_MAX_GPU_TOOL_CALLS=1
AGENT_WEB_SEARCH_MAX_CALLS=1
```

`AGENT_MODEL_INFO` 仅用于兼容端点无法被 AutoGen 正确识别时覆盖模型能力，例如：

```env
AGENT_MODEL_INFO={"vision":false,"function_calling":true,"json_output":true,"structured_output":true,"family":"unknown"}
```

## Tavily 联网搜索

有两种配置方式：

1. 单用户/服务端：在 `backend/.env` 设置 `TAVILY_API_KEY`。
2. 本地多配置：在前端设置页填写 Tavily Key。前端只在本机浏览器保存，并随对话请求传给后端；后端使用请求级上下文，不写入数据库。

设置 `AGENT_WEB_SEARCH_MAX_CALLS=0` 可完全关闭搜索 Agent；设为 `2` 或 `3` 可允许查询改写与交叉验证，但会增加 Tavily 调用次数。

## 模型选择

右上角模型区域会读取当前供应商的 `/models` 接口。选择结果保存在本机设置并随请求传入 AutoGen 模型客户端。若供应商未实现 `/models`、返回鉴权错误或模型不支持 function calling，界面会保留手动填写的默认模型，但相关 Agent 工具可能不可用。

## 遥感工具容器

首次使用对应能力前构建镜像：

```bash
docker build -t rs-tools-mcp:0.1.0 docker/rs_tools
docker build -t rs-detect-mcp:0.1.0 docker/rs_detect
docker build -t rs-segment-mcp:0.1.0 docker/rs_segment
```

默认通过 `RS_*_MCP_USE_DOCKER=true` 使用容器。检测和分割镜像体积较大；NVIDIA GPU 可显著加速，未配置 GPU 时按镜像能力回退 CPU。

## 思考信息安全边界

平台只向用户展示后端白名单生成的阶段状态，不展示、存储或转发模型的原始思维链。防护覆盖：

- provider 流增量和最终文本中的常见 reasoning 字段与 `<think>` 标签；
- AutoGen 内部事件、路由理由、工具异常和模型异常；
- SSE 事件、trace、应用日志、消息元数据和会话持久化；
- 前端事件解析与正文渲染。

阶段状态是运行状态提示，不代表模型原始推理内容。安全相关改动配有后端、前端和日志回归测试。

## 测试

```bash
uv run --project backend pytest backend/tests -q
npm --prefix Agent-frontend test && npm --prefix Agent-frontend run type-check && npm --prefix Agent-frontend run build
```

## 部署注意事项

- 公网部署必须使用 HTTPS，设置强 `AUTH_SECRET_KEY`、`AUTH_COOKIE_SECURE=true`，并关闭客户端模型配置覆盖。
- 不要提交 `.env`、API Key、数据库、影像、模型权重、日志、`.claude`、`.codex` 或其他本地 Agent/编辑器状态。
- `DATABASE_ENABLED=false` 仅用于无库算子调试，会关闭登录、会话、知识库、记忆和持久化能力。
- MinIO 模式需同时配置 `MINIO_*` 并启动 `docker compose up -d db minio`。

## 许可与权利保留

本仓库采用限制性、源码可见许可，不授予开源许可，也不授予任何商业或学术发表权利。除 [LICENSE](LICENSE) 明确允许的个人非商业本地评估外，其他使用均须取得项目权利人的事先书面许可。第三方依赖仍分别受其原始许可证约束。

架构细节见 [docs/agent-tool-architecture.md](docs/agent-tool-architecture.md)。
