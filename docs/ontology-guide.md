# 功能图谱使用指南

从左侧导航进入 **功能图谱**，或访问平台的 `/#ontology` 页面。这里展示业务实体、数据关系、工具动作和固定作业流程，与知识库中从文档提取的知识图谱分别管理。

## 浏览平台能力

默认视图展示业务对象与工具。圆形节点表示实体，方形节点表示工具动作，箭头表示数据流转，虚线表示实体继承。点击节点或关系可查看属性和绑定；支持搜索、拖动、缩放和适应画布。

勾选“显示代码结构”后，还会显示工具参数模型及自动识别的数据模型。参数要求以当前后端注册表中的真实定义为准。

| 业务路径 | 绑定工具 | 输出 |
| --- | --- | --- |
| 地图选区 → 遥感影像 | `prepare_map_roi` | 可用于检测、分割的 RGB 影像 |
| 请求 → 卫星场景 → 遥感影像 | `search_imagery`、`fetch_scene` | 场景列表、导入影像 |
| 遥感影像 → 影像质检 | `raster_inspect` | 波段、范围、质量等信息 |
| 遥感影像 → 地物分类与提取 | `segment_instances` | SAM3 按概念提取的地物实例、轮廓和统计 |
| 遥感影像 → 目标检测结果 | `detect_objects` | 检测框、类别、置信度及统计 |
| 遥感影像 → 分析结果 | `calculate_ndvi`、`calculate_spectral_index`、`render_band_composite`、`extract_water_mask`、`cloud_shadow_mask`、`ocr_recognize` | 指数、合成、掩膜或文字结果 |
| 遥感影像 → 派生栅格 | `clip_reproject_raster` | 裁剪或重投影成果 |
| 文档 → 文档全文 | `parse_document` | 已解析文档正文 |
| 已完成的分析 → 报告 | `generate_report` | 可下载报告 |
| 请求 → 地图位置或检索证据 | `look_at_location`、`web_search` | 定位信息或检索结果 |

“地物分类与提取”对应现有 SAM3 概念分割能力，不表示另行训练了覆盖所有像素的土地覆盖分类模型。工具能否执行仍取决于原有模型服务、数据、权限及配置；图谱中的定义不会代替这些条件。

## 编辑个人定义

1. 点击“实体”新增业务对象，设置名称、说明、属性、属性类型、标识字段、颜色及父实体。
2. 点击“关系”选择起点、终点与数量关系。
3. 点击“绑定工具”选择或填写工具名称，设置所属关系、输出实体及前置条件。
4. 点击“保存定义”。保存后，当前账号后续的新规划使用更新后的定义；正在执行的回合保留开始时的定义。

基础定义可以补充和调整，不能删除；个人新增的定义可以删除。删除个人实体或关系时，会一并移除只属于个人定义的关联关系和动作；仍被基础定义或子实体引用时会拒绝删除。

前置条件可使用 `entity`（当前资源）、`request`（当前请求）和 `arguments`（工具参数）字段，支持存在、等于、属于列表、包含全部元素及大于等于。条件只处理数据，不执行表达式或脚本。“参数满足时检查”可限定某个分析模式下才需要的条件。

手动填写尚未注册的工具名可记录未来能力，但不会让它变成可执行函数。新增实体类型也不会凭空生成业务数据实例；接入新的业务数据时，需要由后端可信结果或资源元数据提供对应状态。

个人定义按账号保存在数据库中，不会写回源码或改变其他账号。数据库未启用时，可以浏览、编辑和导出 JSON，不能保存。切换平台页面会保留草稿，关闭或刷新网页前会提示尚未保存。

## 自动识别与同步

页面打开时，每分钟以及窗口重新获得焦点时自动同步。存在未保存修改时暂停自动同步；“同步代码”可以主动合并新增代码定义并保留草稿。同一项在两处发生不同修改时会提示冲突，可先导出草稿，再撤销草稿并同步；不会静默覆盖个人修改。

当前识别范围：

| 来源 | 识别内容 | 生效方式 |
| --- | --- | --- |
| `backend/app/agent/tool_registry.py` 中的 `TOOLS` | 已注册工具、真实参数、启用状态及执行入口 | 注册新工具并重新加载后端后自动加入 |
| `backend/app/agent/tools/*/schema.py` | 形如 `*_TOOL_NAME = "tool_name"` 的声明 | 未注册工具显示为“源码发现 · 待接入” |
| `backend/app/schemas/*.py` | 顶层 `BaseModel`、`TypedDict` 数据类及声明字段 | 同步时读取；不展示配置、凭据等类型 |
| `backend/app/agent/engine/flows.py` | `PRESET_FLOWS` 的固定流程与顺序 | 同步时读取 |
| `backend/app/agent/ontology/ontology_schema.json` | 人工核实的业务语义、条件、来源和输出 | 修改后同步 |

源码扫描仅解析语法，不导入或执行新文件。任意目录中的普通函数不会自动变为工具。新注册工具先以其资源类型连接到“执行记录”，输出业务语义可以在图谱中补充。已保存的个人覆盖项优先于同名代码定义；新增的代码定义仍会合并进来。

## 规划与执行约束

本体路由器根据当前账号真实可访问的影像、选区、场景、文档和已完成结果，提供下游工具及以下状态：

- `allowed`：已知语义条件满足，调用仍需原有参数和权限校验。
- `needs_evidence`：元数据不足或分析参数未确定，不能宣称条件已满足；由工具继续核验。
- `blocked`：已知条件不满足，不应调用。

不同影像的状态分别计算。例如，另一幅影像拥有近红外波段，不会使当前 RGB 底图具备 NDVI 能力；Alpha 通道也不会被当成近红外。失败结果不解锁报告能力，成功的零目标检测可以生成真实的零目标报告。

这层约束接入现有规划上下文与工具调用前检查，保留现有 Agent、固定作业流程、权限校验、参数验证及工具执行器。个人编辑不能取消平台必要的波段等条件。用 `ONTOLOGY_ENABLED=false` 可以关闭规划和执行中的本体约束，图谱页面仍可浏览。

## 导出定义与可视化配置

“导出定义”下载当前草稿的完整 `ontology_schema.json`，包含实体、关系、数据来源与动作绑定。“Playground”导出当前已保存的图谱；有草稿时需先保存。

可视化配置采用 `name`、`entityTypes`、`relationships` 结构，关系使用 `from`、`to`、`cardinality`，保留原始实体与关系 ID。工具名称与前置条件写入关系说明，对象、数组属性按 JSON 文本标注。将导出的 `ontology_playground.json` 导入支持该结构的可视化工具，即可展示实体和关系；该文件不执行 Agent-RS 工具，也不是服务部署文件。

也可以在项目根目录转换已导出的定义：

```bash
uv run --project backend python backend/scripts/export_ontology.py \
  --input ontology_schema.json --output ontology_playground.json
```

省略 `--input` 时导出当前代码的基础图谱，不含账号个人定义。导出不会自动上传内容到外部网站。

## 升级与配置

1. 同步前后端代码，按项目启动方式安装依赖并重新构建前端。若通过 Python 包安装后端，确保安装的是包含 `ontology_schema.json` 的新构建。
2. 个人定义保存需要启用数据库。后端初始化数据库连接时，会执行现有迁移流程，新增 `0016_ontology_definitions.sql` 中的个人定义表；无需手工重建已有业务表。未启用数据库时，仍可浏览、编辑草稿和导出 JSON。
3. `ONTOLOGY_ENABLED` 默认开启，控制规划上下文和工具调用前的本体条件检查。设为 `false` 时关闭这两处约束，图谱页面及个人定义仍保留；修改配置后重新加载后端。
4. 开发者新增工具时，先完成工具参数、执行入口和注册，再重新加载后端并在页面点击“同步代码”。页面中的自定义绑定只记录语义关系，不会创建新的可执行代码。

当前会话中的一次规划使用开始时建立的定义与资源状态；保存个人修改后，在后续新规划中生效。编辑冲突时可先导出草稿，再同步代码并合并修改。

## 接入位置

| 位置 | 作用 |
| --- | --- |
| `backend/app/agent/ontology/` | 基础定义、动态目录、校验、路由和账号存储 |
| `backend/app/api/routes/ontology.py` | 读取、保存及导出接口 |
| `backend/sql/migrations/0016_ontology_definitions.sql` | 个人定义表；由现有迁移流程创建 |
| `Agent-frontend/src/app/components/OntologyPage.tsx` | 独立图谱页面 |
| `OntologyGraph.tsx`、`OntologyEditor.tsx` | 图谱交互与编辑表单 |
| `backend/app/agent/engine/input.py`、`context.py`、`router.py`、`turn_context.py`、`orchestrator.py` | 为每次规划建立独立资源状态，注入语义上下文并传递到工具调用 |
| `backend/app/agent/tool_execution.py`、`roi_buildings.py` | 复用原执行入口，增加调用前条件检查及成功结果状态更新 |
| `backend/app/core/settings.py`、`backend/.env.example` | 本体约束开关 |
| `backend/app/api/routes/__init__.py`、`backend/pyproject.toml` | 注册接口并将基础 JSON 纳入后端包 |
| `Agent-frontend/src/app/lib/ontology-api.ts` | 接口请求、草稿合并、删除引用检查和下载 |
| `App.tsx`、`TopBar.tsx`、`TaskBar.tsx` | 图谱页面入口、左侧导航、移除欢迎浮窗并保留页面状态 |
| `AgentChat.tsx`、`hooks/useChatPanelSize.ts` | 右侧对话、收起恢复、尺寸调整和窄屏标题 |
| `RightPanel.tsx`、`hooks/useLayerPanelSize.ts` | 左侧可展开图层面板及尺寸调整 |
| `MapView.tsx`、`RoiAnalysisPanel.tsx`、`SatelliteWorkspace.tsx`、`src/styles/index.css` | 地图控件、选区与卫星工作区适应新的导航和对话位置 |
| `Agent-frontend/src/app/data/rs.ts` | 目标检测说明与实际 YOLO11s-OBB 配置保持一致 |
| `README.md`、`docs/screenshots/` | 当前功能说明与真实界面截图 |

上表仅列文件名的前端组件位于 `Agent-frontend/src/app/components/`；`App.tsx` 位于 `src/app/`，前端 `hooks/` 相对于 `src/app/`。仅列文件名的后端编排模块相对于 `backend/app/agent/engine/`。

保存时会校验重复 ID、属性重名、无效引用、继承循环和条件格式。并发保存使用版本检查；代码目录变化时也需先同步。遇到存储异常时保留草稿供导出，已有工具的运行逻辑保持原有校验。
