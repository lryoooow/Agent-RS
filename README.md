<div align="center">

<img src="docs/assets/logo-rsagent.png" alt="Agent-RS Logo" width="180" />

# Agent-RS

**面向遥感影像分析的 AI 助手 — 用自然语言完成专业遥感处理**

</div>

Agent-RS 是一个面向遥感影像分析的 AI 助手。你可以像聊天一样上传卫星或航拍影像，用自然语言让它完成植被分析、水体提取、地物分类、目标检测等遥感任务，结果以可交互的地图图层直接呈现。

它把"会聊天的大模型"和"专业的遥感算法"接在一起：模型负责理解意图、规划该用哪个工具；真正的影像计算交给容器化的遥感算法去跑。你不需要写代码、配参数，也不需要懂 GDAL，一句话就能得到结果。

## 功能特性

**智能对话**
- 普通问答、长文本整理、资料总结，流式回复 + Markdown 渲染（标题、列表、表格、代码块）
- 按需联网查询实时资料（独立搜索子代理）
- 知识库文档检索与长期记忆（向量召回 + 全文检索 + RRF 融合 + 重排 + MMR 去冗）

**影像管理**
- 上传 GeoTIFF，自动压缩并在地图上预览原图；结果图层可叠加、单独开关、查看图例
- 框选 ROI 聚焦感兴趣区域；分析报告一键生成

**遥感分析工具**（全部由 AI 按需自动调用）

| 工具 | 能力 | 说明 |
|------|------|------|
| 影像质检 | 读取影像元信息 | 尺寸、波段、坐标系、像素统计 |
| NDVI | 归一化植被指数 | 植被长势与覆盖度分析 |
| 光谱指数 | 10 种指数 | NDWI/MNDWI（水体）、NDBI/BSI（建成区/裸土）、EVI/SAVI/MSAVI/GNDVI（植被）、NDMI（水分）、NBR（火烧迹地） |
| 波段组合 | 真彩色 / 假彩色 | 自定义波段渲染合成图 |
| 目标检测 | PP-YOLOE-R / DOTA 15 类 | 飞机、舰船、车辆、储油罐、港口、桥梁等，输出旋转框图层 |
| 地物分割 | U-Net / LandCover.ai | 建筑、林地、水体、背景的像素级分类掩膜 |
| 云/阴影掩膜 | 阈值法粗筛 | 标记云与阴影区域，用于质量控制 |
| 水体掩膜 | 阈值法提取 | 基于光谱特征提取水体范围 |
| 裁剪 / 重投影 | 范围裁剪与坐标系转换 | 产出可下载的派生栅格 |
| 文档解析 | 提取已入库文档全文 | 配合知识库回答文档相关问题 |
| 影像 OCR | 识别影像 / 扫描件文字 | 对栅格影像、扫描地图做光学字符识别 |

**准入与多用户**
- 开放注册 + 登录认证，按用户隔离数据
- 登录加密：PBKDF2-SHA256（600k 迭代）

## 更新日志

### 2026-06-24 · RAG 全链路优化 + 简化认证

**RAG 检索增强**
- **中文全文检索修复**：PostgreSQL bigram 切分，解决中文查询命中率问题
- **文档切块语义连贯**：章节面包屑写入块正文，每个块带归属信息，提高召回准确性
- **上下文扩展**：检索锚点块自动补充相邻块（±1），修复跨块论述被切断问题
- **文档解析增强**：DOCX/PPTX 标题层级恢复，元信息保留

**认证简化**
- 移除邀请码准入机制，改为开放注册
- 移除登录限流和管理员体系
- 保留基础认证功能（注册/登录/会话管理）

### 2026-06-22 · 对象存储 + 持久化工具队列

- **影像对象存储**：影像二进制可落 MinIO（`STORAGE_BACKEND=minio`），owner 鉴权统一走 DB，支持多实例/可迁移；默认仍落本地盘（单机够用）。
- **durable 工具任务队列**：工具执行记录持久化，进程重启后恢复被打断的孤儿任务；并发上限保护宿主机内存。正常流量仍同步实时推送 SSE。

### 2026-06-18 · 统一 PostgreSQL 持久化

- 存储后端统一为 **PostgreSQL（pgvector）**：登录、长期记忆、历史会话、知识库全部落库，检索管线（向量 + 全文 + RRF + 重排 + MMR）不变。

### 2026-06-17 · 回答呈现与对话准确性

- **Markdown 渲染**：助手回复正确渲染标题、列表、加粗、表格、代码块；多类别遥感结果以表格呈现。
- **修复上下文串扰**：分离联网搜索的引用规范，加入「只回答当前问题、不复述历史」硬约束。
- **回答更专业**：重写遥感结果回答范式（核心结论 → 指标解读 → 建议与局限），简单问题保持简洁。
- **地图地名搜索**：右上角搜索框输入地名即可定位飞行（公开地理编码服务）。

### 2026-06-07 · 检测 / 分割工具 + 领域子 Agent

- 新增**目标检测**（PP-YOLOE-R / DOTA 15 类）与**地物语义分割**（U-Net / LandCover.ai），独立 GPU 容器经 MCP 调用，无 GPU 自动回退 CPU。
- 光谱指数 5 → 10 种；前端新增对应图层与图例。
- **架构升级**：「单一管线」重构为「顶层统一规划 → 三个领域子 Agent 执行」（指数分析 / 地物分类 / 目标检测）。新增能力只需登记到领域归属表。详见 [`docs/agent-tool-architecture.md`](docs/agent-tool-architecture.md)。

## 工作原理

```
用户提问  ─►  AI 模型（理解意图 + 规划）
                   │
                   ├─ 直接回答 / 联网搜索
                   │
                   └─ 需要影像计算 ─►  选择遥感工具 ─►  MCP Docker 容器执行算法
                                                              │
                                          结果图层  ◄──────────┘
                                          （叠加到地图）
```

模型本身不碰像素。每个遥感工具都是独立的容器化算法（经 MCP 协议以 stdio 通信），由 AI 按意图自动选择调用。算法环境彼此隔离、可独立升级，模型只负责"理解和编排"，计算结果可信且可复现。新增一个能力只需注册工具 + 封装算法容器，无需改动编排逻辑。

## 技术栈

- **后端**：Python + FastAPI，异步 Agent 运行时，MCP（stdio）调用 Docker 工具容器
- **前端**：React + Vite + TypeScript + Tailwind CSS + shadcn/ui，MapLibre GL 地图渲染
- **遥感算法容器**：rasterio / NumPy（指数）、PaddleDetection PP-YOLOE-R（检测）、PyTorch + segmentation-models-pytorch（分割）
- **存储**：PostgreSQL + pgvector（知识库 / 记忆 / 会话 / 登录）；影像二进制落本地盘或 MinIO（可选）
- **鉴权**：PBKDF2-SHA256（600k）+ HMAC 会话令牌
- **文档解析**：pypdf / python-docx / python-pptx / openpyxl（PDF / Word / PPT / Excel），PDF 支持 OCR

## 快速开始

### 环境要求

- Python 3.11+、Node.js 18+
- Docker Desktop（运行遥感工具容器与本地 PostgreSQL；检测/分割需 NVIDIA GPU + nvidia-container-toolkit 以获最佳性能，无 GPU 自动回退 CPU）

### 1. 起本地基础设施（PostgreSQL，可选 MinIO）

```bash
docker compose up -d db          # 只起 PostgreSQL（影像落本地盘，单机够用）
docker compose up -d db minio    # 起库 + 对象存储（STORAGE_BACKEND=minio 时）
```

### 2. 配置后端

复制 `backend/.env.example` 为 `backend/.env` 并填写。最少需要：

```env
AI_API_KEY=your_api_key          # 必填，否则无法调用模型
AI_BASE_URL=https://api.openai.com/v1   # OpenAI 兼容端点；阿里云百炼填 https://dashscope.aliyuncs.com/compatible-mode/v1
AI_DEFAULT_MODEL=gpt-4.1-mini           # 按所用服务商填，如 qwen-max

DATABASE_ENABLED=true
DATABASE_URL=postgresql://agent_rs:agent_rs_local@127.0.0.1:15432/agent_rs

# 【公网部署必改】会话令牌的 HMAC 密钥，改成长随机串（openssl rand -hex 32）
AUTH_SECRET_KEY=change-this-to-a-long-random-string

TAVILY_API_KEY=                  # 联网搜索，可选
STORAGE_BACKEND=local            # 影像落本地盘；多实例改 minio
```

初始化表结构：

```bash
cd backend && python sql/apply.py
```

### 3. 构建遥感工具镜像（按需，首次使用对应能力前）

```bash
docker build -t rs-tools-mcp:0.1.0 docker/rs_tools       # 质检 / NDVI / 光谱指数 / 波段组合
docker build -t rs-detect-mcp:0.1.0 docker/rs_detect     # 目标检测（较大，含模型权重）
docker build -t rs-segment-mcp:0.1.0 docker/rs_segment   # 地物分割
```

### 4. 启动后端与前端

```bash
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 3000 --reload --reload-exclude "storage/*"
npm --prefix Agent-frontend install
npm --prefix Agent-frontend run dev
```

前端默认 http://localhost:5173 ，通过 Vite proxy 把 `/api` 转发到后端 http://localhost:3000 。首次打开会因强制登录显示登录页，用上一步的邀请码注册即可。

## 使用示例

上传一张 GeoTIFF 后地图自动显示原图预览，再用自然语言描述需求：

- "帮我算一下这张影像的 NDVI" → 生成植被指数图层
- "提取图里的水体" → 自动选用 NDWI 光谱指数
- "检测图中的飞机和船只" → 输出旋转框检测图层与各类别计数
- "把这张图做地物分类" → 输出建筑/林地/水体的彩色分割掩膜与占比
- "用真彩色显示这张影像" → 生成波段组合图层

每个结果都是地图上的独立图层，可单独开关、查看图例。

## 访问控制（邀请码 / 管理）

面向定向内测的准入层（`AUTH_ENABLED=true` 且 `DATABASE_ENABLED=true` 时生效）：

- **注册**：`INVITE_REQUIRED=true` 时必须持有效邀请码（高熵单次/限时，DB 仅存 HMAC）。
- **管理员**：邮箱 ∈ `ADMIN_EMAILS` 即管理员，登录后界面出现管理入口，可签发/撤销邀请码、停用用户。
- **首个管理员**：`python -m scripts.admin_bootstrap mint-invite` 铸码，再用 `ADMIN_EMAILS` 内邮箱 + 该码注册。
- **公网部署务必**：改 `AUTH_SECRET_KEY` 为长随机串、走 HTTPS 时设 `AUTH_COOKIE_SECURE=true`。

`DATABASE_ENABLED=false` 时存储能力整体关闭（仅用于无库的纯算子调试），不强制登录。

## 开发与测试

```bash
docker compose up -d db                        # PG 集成测试需要本地库
python -m pytest backend/tests -q              # 后端测试
npm --prefix Agent-frontend run type-check     # 前端类型检查
npm --prefix Agent-frontend test               # 前端单测（vitest）
npm --prefix Agent-frontend run build          # 前端构建检查
```
