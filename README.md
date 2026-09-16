<div align="center">

<img src="docs/assets/logo-rsagent.png" alt="Agent-RS Logo" width="180" />

# Agent-RS

**基于 AutoGen 的遥感智能分析平台**

</div>

Agent-RS 把大模型、多 Agent 编排与容器化遥感算法连接起来。用户可上传 GeoTIFF，使用自然语言完成影像质检、光谱指数、目标检测、地物分类、裁剪重投影、报告生成等任务，并在 MapLibre 地图上查看结果图层。

> **使用限制：本项目不是开源软件。仅允许个人、非商业、本地学习与评估。未经项目权利人事先书面许可，禁止商业使用、对外提供服务、二次分发，以及使用本项目的代码、设计、数据、结果或衍生成果发表论文、预印本、学位论文、专利、项目申报或竞赛作品。发现违规使用，权利人将保留停止授权并依法追究责任的权利。完整条款见 [LICENSE](LICENSE)。**

## 本次更新（2026-09-14）

本轮为一次系统性重构与加固：编排架构收敛、免账号卫星影像检索接入、请求层制度化、层级倒置修复，共 **24 个提交**，后端测试从 821 → **876 全绿**、前端从 62 → **68 全绿**。

### 一、编排架构收敛（Phase 3/4）

- **共享工具制**：联网搜索（`web_search`）、地图定位（`look_at_location`）、报告生成（`generate_report`）从平级"专家 Agent"降级为所有 Agent 共有的共享工具——用一次检索不再需要交棒往返两次完整 LLM 调用，中间答案不再泄漏给用户。
- **两层编排定型**：`SelectorGroupChat`、8 位平级专家、`[DONE]`/`[HANDOFF]` 交棒协议与约 300 行流式净化器整体移除。自由请求由持有全部工具的单主 Agent（`main_agent`）直接完成；完整命中标准作业走 `GraphFlow` 固定流水线（报告收尾由专用节点保证确定性）。
- **工具 schema 单一事实源**（Phase 1）：13 个遥感工具的手写 OpenAI function dict 全部删除，注册时由 Pydantic 参数模型生成（含 anyOf 展开、定长元组降级等归一化），约束与描述不再有两份漂移源。
- **影像清单结构化**（Phase 2）：上传时提取波段描述/标签派生**波段角色表**（`B1蓝,B3红,B8近红外`），模型选波段以角色表为准（来源标注可信度），取代散落提示词里的「GF-2 默认波序」硬编码；清单含传感器/拍摄时间，最新优先且有条数上限。
- **性能**（Phase 5）：RAG/长期记忆回合级缓存（工具循环内同一检索词不再重复 embedding+检索+rerank）；无影像用户跳过路由 LLM 调用直达主 Agent（`AGENT_ROUTER_FAST_PATH`，默认开，`has_imagery` 保守默认避免误杀 GraphFlow）。

### 二、免账号卫星影像检索（Phase 7）

- **双源免账号**：EarthSearch（Sentinel-2 L2A，10m）+ Microsoft Planetary Computer（Landsat 8-9，30m，匿名 SAS 签名自行实现，未引入停更 SDK）；`auto` 双源并发、单源失败降级不拖垮。
- **检索页**：顶部导航「卫星影像」，NASA EarthData Search 三栏形态（左筛选：地名/当前视野/框选 + 时间 + 云量 + 数据源；中主地图；右结果卡片），非模态设计中央地图保持可交互。
- **对话驱动**：`search_imagery` 共享工具支持自然语言取图（"找深圳湾上个月云量低于 20% 的影像"），结果以场景卡片进对话（落库/历史恢复全链路），卡片上可**预览**（地图定位）/ **下载多波段 TIF**（含加载反馈）/ **一键导入**平台直接分析。
- **数据正确性**：五波段 GeoTIFF（蓝/绿/红/近红外/短波红外）带波段描述与地理参照；S2 的 10m/20m 混合分辨率按地理范围对齐窗口；Landsat SR 偏置量化转真反射率（保证 NDVI 等比值指数正确）。
- **安全**：出网端点硬编码白名单（无 SSRF 面）；资产 URL/SAS 令牌只存服务端按用户隔离的缓存（TTL 30 分钟），不进提示词/日志/落库；下载导入滑动窗口限流 + 产物文件数封顶；回合配额（搜索 2 次、导入 1 次）。

### 三、请求层制度化（P0-P3）

- **后端统一错误契约**（P1）：全平台唯一错误信封 `{"error":{"code","message"}}`——新增 HTTPException 全局处理器与兜底 500 处理器；32 处裸字符串错误编码迁移；上游异常原文不再泄进响应体；`/health` 存储故障返回 503。状态码规则文档化（`backend/app/api/errors.py`）。
- **前端统一 HTTP 客户端**（P2）：`lib/http.ts` 成为唯一 fetch 出口——统一基址、cookie、**所有请求默认 30s 超时**（重活按场景放宽）、错误归一 `ApiError`（读懂新旧契约与反向代理 HTML 页）、幂等 GET 自动重试。删除 7 份重复错误解析与 4 个死代码 URL 派生助手，拆除 5 个组件的 endpoint 穿线链。SSE 加固：90s 空闲看门狗；连接被掐断显式报"回答可能不完整"。
- **可观测性**（P3）：每个请求 `X-Request-ID`（响应头回显）+ 结构化完成日志（method/path/status/duration_ms/user）——工具审计日志自此可与 HTTP 流量关联；新增 `docs/deployment.md`（反代要求/错误契约/降级模式）。

### 四、层级倒置修复与方向断言（P4.5）

依赖方向全量审计后修复三处接入期倒置：影像持久化助手从 HTTP 路由层下沉到 `services/imagery_persist.py`（服务层不再向上依赖路由）；`look_at_location` runner 不再直写编排状态（产物统一经 `ToolRunResult.metadata` 回流）。边界测试新增两条 **AST 级方向断言**：agent 核心层禁止 import `app.api`、工具 runner 禁止 import 编排层——此类错误提交即红。

### 五、问题修复

- 下载 TIF 点击无响应：后端实际 200（远程合成需数十秒），`<a>` 直跳零反馈——改为 fetch+blob 带进度/错误/防重复。
- 卫星影像面板点输入框整体关闭：双 Sheet 共享开关 + 模态判定外部交互误关——改非模态并阻止外部点击关闭。
- 影像检索全部 404：前端端点拼装违反基址约定——统一客户端内定基址并加回归用例。
- 城市级地名跳转"只缩小"：Nominatim 把城市解析为行政区划 bbox，fitBounds 拉远视角——点状地名改定心 + 城市级缩放（city=11）。
- SSRF 校验误伤 fake-ip 代理（Clash TUN）用户：报错带主机名与白名单补救方法（`AI_PROVIDER_ALLOWED_HOSTS`）。
- 存量 bug：422 处理器序列化 model_validator 异常对象会 500；上传测试隐式依赖 `.env` 密钥。

### 破坏性变更提示

- 路由策略字面量 `selector` → `main`（仅日志/trace 元数据，不落库）。
- `AGENT_WEB_SEARCH_MAX_CALLS` 默认 1 → 3（共享工具自主多轮检索）。
- 错误响应体统一为 `{"error":{code,message}}`（旧客户端读 `detail` 需适配）。
- `docker-compose.yml` 数据库端口映射改为 `5432:5432`（本机 5432 被占用时自行调整）。

## 架构

```text
用户请求
   │
   ▼
AutoGen 结构化路由 Agent（无影像用户走快车道直达主 Agent）
   ├── 完整标准作业 ──► GraphFlow（流内领域专家 + report 收尾节点）
   └── 其余一切 ─────► main_agent（持有全部工具 + 共享工具的单主 Agent）
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        遥感领域工具      共享工具          卫星影像检索
      （AutoGen BaseTool） web_search /       search_imagery /
              │           look_at_location /  fetch_scene
              │           generate_report        │
       MCP stdio / Docker                    STAC 双源（免账号）
              │                              EarthSearch + PC
       遥感算法与结果图层                     预览/下载TIF/导入
```

业务代码通过 `backend/app/agent/engine/` 适配 AutoGen，避免在 API、存储和领域代码中散落框架调用。层级方向受 AST 级边界测试强制：只有 engine 可 import `autogen_*`；agent 核心层不得向上依赖 HTTP 层；工具 runner 不得感知编排层。请求层制度：后端唯一错误信封 `{"error":{code,message}}`、`X-Request-ID` 贯穿、结构化访问日志；前端统一 HTTP 客户端（超时/重试/错误归一）。详见 `docs/agent-tool-architecture.md` 与 `docs/deployment.md`。

## 主要能力

| 类别 | 能力 |
| --- | --- |
| 智能对话 | 流式 Markdown、上下文压缩、长期记忆、文档 RAG |
| 卫星影像检索 | 免账号搜 Sentinel-2 / Landsat（区域/时间/云量），预览 / 下载多波段 TIF / 导入分析 |
| 联网搜索 | Tavily 查询改写、多轮检索、来源整理与调用次数限制 |
| 影像管理 | GeoTIFF 上传、压缩预览、图层开关、图例、ROI 框选、波段角色表 |
| 影像质检 | 尺寸、波段、坐标系、范围与像素统计 |
| 光谱分析 | NDVI、NDWI、MNDWI、NDBI、BSI、EVI、SAVI、MSAVI、GNDVI、NDMI、NBR |
| 栅格处理 | 真/假彩色合成、云影掩膜、水体掩膜、裁剪、重投影 |
| 深度学习 | SAM3 开放词汇实例分割、YOLO11s-OBB 旋转框目标检测、ROI 目标提取 |
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
npm --prefix Agent-frontend ci   # 或 pnpm --prefix Agent-frontend install
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
```

光谱工具与目标检测通过 `RS_*_MCP_USE_DOCKER=true` 使用容器。开放词汇提取与分割由独立的 SAM3 GPU 服务提供，部署见 `ops/agent-rs-sam3.service`。

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
