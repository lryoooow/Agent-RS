# cloud_shadow_mask 接入计划（preprocess_agent 样板）

## 目标
接入第一个预处理工具 `cloud_shadow_mask`，同时落地新领域子 Agent `preprocess_agent`。
本工具作为后续所有工具接入的**样板**，设计点一次做对，后续 extract_water_mask / clip_reproject_raster 照抄。

## 设计决策（已确认）
- **算法**：纯阈值法，无模型权重，纯 numpy/rasterio。复用 `rs-tools-mcp` 镜像（不新建镜像）。
- **领域归属**：新增 `preprocess_agent`。
- **输入**：单影像 `imagery_id`（贴合现有模式，不引入双影像/几何/矢量复杂度）。
- **输出**：掩膜 .tif + 预览 PNG + 统计，走现有 `geospatial_result` 链路。
- **配置**：零新增（复用 rs_tools_mcp_* 全部设置）。

## 算法（纯阈值，多光谱组合）
云：高亮度（红/绿/蓝均高）且低 NDVI、低 NDWI → 云像素。
阴影：低亮度（NIR 很低）且非水体 → 阴影像素。
无效：原始 nodata 像素。
输出单波段分类栅格：0=clear, 1=cloud, 2=shadow, 3=nodata。
阈值用相对分位数（不写死绝对 DN，避免不同传感器/辐射定标失效），并在 formatter 里声明"阈值法为粗筛，非精确云检"的边界。

## 改动清单

### A. Docker 工具侧（docker/rs_tools/）
1. **新建 `compute_cloud_mask.py`**
   - `def compute(*, input_path, output_dir, red_band=3, green_band=2, blue_band=1, nir_band=4) -> dict`
   - 照抄 compute_ndvi 的 I/O 骨架：rasterio 读波段 → 阈值分类 → 写 cloud_mask.tif（uint8）+ cloud_mask_colored.png + cloud_mask_stats.json
   - 返回 stats：cloud_pct / shadow_pct / clear_pct / nodata_pct + output_tif + output_png
2. **mcp_server.py**
   - import `from compute_cloud_mask import compute as compute_cloud_mask`
   - TOOL_DEFINITIONS 加 cloud_shadow_mask 定义（input_path/output_dir/red_band/green_band/blue_band/nir_band）
   - handle() tools/call 加 `elif name == "cloud_shadow_mask": result = compute_cloud_mask(**args)`
3. **重建镜像**：`docker build -t rs-tools-mcp:0.1.0 docker/rs_tools/`（用户执行或确认）

### B. Backend 接入侧（backend/app/agent/）
4. **新建 tools/cloud_mask/{__init__,schema,runner,formatter}.py**（照抄 ndvi/ 三件套）
   - schema.py：`CloudMaskArguments`(imagery_id + red/green/blue/nir_band 默认 3/2/1/4 + reason) + `CLOUD_MASK_TOOL` 定义
   - runner.py：`run_cloud_mask`，复用 common.py 的 IMAGERY_ID_PATTERN/resolve_imagery_paths/validate_band_indices/imagery_not_found_result/read_bounds/execution_metadata；MCP 调 "cloud_shadow_mask"；组装 geospatial_result(type="cloud_mask")
   - formatter.py：`format_cloud_mask_context`，输出云/阴影/晴空占比 + 阈值法边界声明
5. **tool_registry.py**：import + TOOLS 注册 "cloud_shadow_mask"（tags=("imagery","preprocess","mcp")）
6. **domain_agents.py**：
   - TOOL_DOMAIN 加 `"cloud_shadow_mask": "preprocess_agent"`
   - DOMAIN_LABELS 加 `"preprocess_agent": "预处理"`
   - DOMAIN_GUIDANCE 加 preprocess_agent 指引（声明掩膜为质量控制粗筛，引用真实占比，不编造）
7. **routing.py**：ALL_IMAGERY_TOOLS 元组加 "cloud_shadow_mask"（**关键：漏了会被 plan_validator 拦成 capability_not_allowed_by_route**）
8. **llm_planner.py**：_planner_prompt 加示例（"帮我做云掩膜/去云质检" → cloud_shadow_mask）

## 测试（覆盖正常/边界/非法/异常/回归）

### 单元测试 tests/ai/test_cloud_mask_runner.py（照抄 test_segment_runner.py 模式）
- schema 默认值（red/green/blue/nir = 3/2/1/4）
- schema 拒绝非法 imagery_id
- runner 非法 imagery_id → error="invalid_imagery_id"
- runner 影像不存在 → error="imagery_not_found"（monkeypatch IMAGERY_UPLOAD_DIR）
- runner MCP 未启用（rs_tools_mcp_use_docker=false）→ error="mcp_disabled"
- runner MCP 抛 MCPCallError → error="mcp_error"（monkeypatch _client）
- runner 成功路径（mock _client 返回 stats）→ 校验 geospatial_result.type/result_url/占比、artifacts、metadata

### 领域归属测试（扩 test_domain_agents.py）
- domain_for_tool("cloud_shadow_mask") == "preprocess_agent"
- DOMAIN_LABELS / DOMAIN_GUIDANCE 含 preprocess_agent
- DomainToolAgent("preprocess_agent") 成功时给 tool_context 追加指引

### 注册/路由回归（扩 test_tool_registry.py）
- "cloud_shadow_mask" in TOOLS 且 list_tool_definitions 含其定义
- "cloud_shadow_mask" in routing.ALL_IMAGERY_TOOLS（防漏第7步）
- capability_registry 自动派生该能力（get_capability 非空、kind="tool"）

### docker 计算函数单测 tests/（若 docker 函数可直接 import 测）
- 用合成多波段 tif 跑 compute，校验输出 tif/png 存在、stats 占比和为 ~100%、nodata 正确识别

### 全套回归
- pytest tests 全绿（全量零回归；tests/ai 只作为 Agent/Tool 专项快速检查，不能替代最终验收）

## 防重复保障
- routing.ALL_IMAGERY_TOOLS 漏登记 → 加专门回归测试（第7步那条），后续每个新工具都加一条，防同类问题复发。
- 阈值法精度边界写进 formatter，避免模型把粗筛掩膜当精确云检解读。
