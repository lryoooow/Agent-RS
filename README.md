<div align="center">

<img src="docs/assets/logo-rsagent.png" alt="Agent-RS Logo" width="180" />

# Agent-RS

**面向遥感影像分析的 AI 助手 — 用自然语言完成专业遥感处理**

</div>

Agent-RS 是一个面向遥感影像分析的 AI 助手。你可以像聊天一样上传卫星或航拍影像，用自然语言让它完成植被分析、水体提取、地物分类、目标检测等遥感任务，结果会以可交互的地图图层直接呈现。

它把"会聊天的大模型"和"专业的遥感算法"接在了一起：模型负责理解你的意图、规划该用哪个工具；真正的影像计算则交给容器化的遥感算法去跑。你不需要写代码、配参数，也不需要懂 GDAL，一句话就能得到结果。

## 功能特性

**智能对话**
- 普通问答、长文本整理、资料总结，支持流式回复
- 按需联网查询实时资料（基于独立的搜索子代理）
- 可选接入知识库，用于文档检索与上下文记忆

**影像管理**
- 上传 GeoTIFF 影像，自动压缩处理并在地图上预览原图
- 多结果图层叠加展示，可单独开关、查看图例

**遥感分析工具**（全部由 AI 按需自动调用）

| 工具 | 能力 | 说明 |
|------|------|------|
| 影像质检 | 读取影像元信息 | 尺寸、波段、坐标系、像素统计 |
| NDVI | 归一化植被指数 | 植被长势与覆盖度分析 |
| 光谱指数 | 10 种指数 | NDWI/MNDWI（水体）、NDBI/BSI（建成区/裸土）、EVI/SAVI/MSAVI/GNDVI（植被）、NDMI（水分）、NBR（火烧迹地） |
| 波段组合 | 真彩色 / 假彩色 | 自定义波段渲染合成图 |
| 目标检测 | PP-YOLOE-R / DOTA 15 类 | 飞机、舰船、车辆、储油罐、港口、桥梁等，输出旋转框图层 |
| 地物分割 | U-Net / LandCover.ai | 建筑、林地、水体、背景的像素级分类掩膜 |

## 更新日志

### 2026-06-16

本次更新对前端做了一次彻底的升级换代，启用全新设计的界面，并将其与后端能力全面打通：

- **全新前端界面**：采用全新设计的交互界面，以全屏地图为主视角，对话以悬浮窗形式呈现，整体视觉更现代、操作更聚焦。
- **沉浸式地图工作台**：影像与分析结果直接叠加在地图上，支持图层开关、透明度调节与图例查看；带地理坐标的结果自动定位，无坐标影像以原图比例完整展示。
- **对话与分析一体化**：聊天、影像上传、工具调用状态、遥感结果在同一界面内串联，工具执行进度以气泡形式实时反馈。
- **功能全面补齐**：登录注册、知识库文档（上传、检索、删除）、长期记忆、历史会话（载入、改名、删除）等能力全部接入新界面。
- **细节优化**：修正大尺寸影像在地图上的完整展示，对话窗支持上下滚动并新增返回入口，交互更顺手。

### 2026-06-07

本次更新为 Agent-RS 新增了两类全新的遥感分析能力，并大幅扩展了已有工具：

- **新增「目标检测」工具**：接入 PP-YOLOE-R（DOTA 数据集，15 类）旋转框检测模型，可识别飞机、舰船、车辆、储油罐、港口、桥梁等遥感目标，输出带类别计数的旋转框图层。算法以独立 GPU 容器（`rs-detect-mcp`）封装，通过 MCP 协议调用。
- **新增「地物语义分割」工具**：接入 U-Net（LandCover.ai 数据集）分割模型，对影像做像素级地物分类（建筑、林地、水体、背景），输出彩色分类掩膜与各类别占比。算法以独立容器（`rs-segment-mcp`）封装，支持 GPU 推理、无 GPU 时自动回退 CPU。
- **光谱指数从 5 种扩展到 10 种**：新增 GNDVI、MSAVI（植被）、NDMI（植被水分）、NBR（火烧迹地）、BSI（裸土）五种指数，覆盖水体、建成区、植被、水分、灾后评估等更多场景。
- **前端地图增强**：新增目标检测旋转框图层、地物分割掩膜图层及对应图例，可按类别查看颜色与数量/占比。
- **架构升级 · 按领域拆分子 Agent**：将原先「单一管线平铺 6 个工具」重构为「顶层统一规划 → 三个领域子 Agent 执行」的两级结构。三个领域分别是 **指数分析**（NDVI、光谱指数、波段合成、影像检视）、**地物分类**（语义分割）、**目标检测**。工具仍是无状态的既定流程（经 MCP 调用 Docker 算法容器），领域子 Agent 维护各自的局部上下文与执行边界。以后新增能力只需登记到对应领域的归属表，互不干扰，扩展更清晰、更不易出错。
- **文档重写**：README 从安装手册式结构重写为面向用户的项目介绍，新增功能总览、工作原理图与使用示例。

> 检测与分割工具均已通过端到端验证（真实影像 → 容器推理 → 结果图层），后端测试 21 项全部通过。

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

模型本身不碰像素。每个遥感工具都是一个独立的容器化算法（通过 MCP 协议以 stdio 通信），由 AI 按你的意图自动选择并调用。这样做的好处是：算法环境彼此隔离、可独立升级，模型只负责"理解和编排"，计算结果可信且可复现。

新增一个遥感能力，只需注册一个工具 + 封装一个算法容器，不需要改动模型的编排逻辑。详见 [`docs/agent-tool-architecture.md`](docs/agent-tool-architecture.md)。

## 技术栈

- **后端**：Python + FastAPI，异步 Agent 运行时，MCP（Model Context Protocol）stdio 调用 Docker 工具容器
- **前端**：React + Vite + TypeScript + Tailwind CSS + shadcn/ui，MapLibre GL 地图渲染
- **遥感算法容器**：rasterio / NumPy（指数计算）、PaddleDetection PP-YOLOE-R（目标检测）、PyTorch + segmentation-models-pytorch（地物分割）
- **可选**：PostgreSQL（知识库、记忆、会话持久化）

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker Desktop（运行遥感工具容器；目标检测与分割需要 NVIDIA GPU + nvidia-container-toolkit 以获得最佳性能，无 GPU 时自动回退 CPU）
- PostgreSQL 15+（仅在启用知识库 / 记忆 / 历史持久化时需要）

### 1. 配置后端

在 `backend/.env` 中填写配置（参考 `backend/.env.example`）：

```env
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_API_KEY=your_api_key          # 必填，否则无法调用模型
AI_DEFAULT_MODEL=qwen3.7-max

TAVILY_API_KEY=your_tavily_key   # 联网搜索用，可选
DATABASE_ENABLED=false           # 不用知识库时保持 false

IMAGERY_UPLOAD_DIR=storage/imagery
RS_TOOLS_MCP_USE_DOCKER=true
RS_DETECT_MCP_USE_DOCKER=true
RS_SEGMENT_MCP_USE_DOCKER=true
RS_DOC_MCP_USE_DOCKER=true
```

### 2. 构建遥感工具镜像

按需构建（首次使用对应能力前执行）：

```bash
docker build -t rs-tools-mcp:0.1.0 docker/rs_tools       # 质检 / NDVI / 光谱指数 / 波段组合
docker build -t rs-detect-mcp:0.1.0 docker/rs_detect     # 目标检测（较大，含模型权重）
docker build -t rs-segment-mcp:0.1.0 docker/rs_segment   # 地物分割
```

### 3. 启动后端

```bash
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 3000 --reload --reload-exclude "storage/*"
```

### 4. 启动前端

```bash
npm --prefix Agent-frontend install
npm --prefix Agent-frontend run dev
```

前端默认 http://localhost:5173 ，通过 Vite proxy 将 `/api` 转发到后端 http://localhost:3000 。

## 使用示例

打开前端页面即可开始对话。普通问题直接回答；遥感任务则先上传影像，再用自然语言描述需求：

- 上传一张 GeoTIFF 后，地图自动显示原图预览
- "帮我算一下这张影像的 NDVI" → 生成植被指数图层
- "提取图里的水体" → 自动选用 NDWI 光谱指数
- "检测图中的飞机和船只" → 输出旋转框检测图层与各类别计数
- "把这张图做地物分类" → 输出建筑/林地/水体的彩色分割掩膜与占比
- "用真彩色显示这张影像" → 生成波段组合图层

每个结果都是地图上的独立图层，可单独开关、查看图例。

## 可选：启用数据库

需要知识库、记忆或会话持久化时：

```env
DATABASE_ENABLED=true
DATABASE_URL=postgresql://agent_rs:your_password@localhost:15432/agent_rs
```

```bash
cd backend && python sql/apply.py
```

## 开发与测试

```bash
python -m pytest backend/tests -q              # 后端测试
npm --prefix Agent-frontend run type-check     # 前端类型检查
npm --prefix Agent-frontend run build          # 前端构建检查
```
