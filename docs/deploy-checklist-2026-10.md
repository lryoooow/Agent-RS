# 部署检查清单（2026-10-10，随 G 批次修复发布）

> 适用范围：把生产机从上一发布（`61fdbc5`/`9078f0b`）升级到本批
> （含 G8/G9/G10/G11/G14/G20/G23 补与迁移 0014/0015）。
> 所有环境变量名与默认值以 `backend/app/core/settings.py` 实际字段为准（本文逐项核对）。

## 1. 数据库迁移：0014、0015 的执行顺序与回滚

迁移由 `backend/sql/apply.py::run_migrations` 按文件名顺序执行，已应用版本记录在
`agent_rs.schema_migrations`。**顺序固定 0014 → 0015**（后端启动时自动执行，
也可手动：`python -m sql.apply`）。

| 版本 | 内容 | 大库注意事项 |
|---|---|---|
| 0014 | `public.tool_jobs` 状态约束扩为 `('pending','running','complete','failed','cancelled','outcome_unknown')` | 纯约束替换，瞬间完成 |
| 0015 | `public.document_chunks` 建 `(document_id)` B-tree 索引 | **大库先手动并发建索引**：`CREATE INDEX CONCURRENTLY idx_document_chunks_document_id ON public.document_chunks (document_id);` 迁移脚本检测到等价有效索引后自动跳过，避免事务内建索引锁表 |

回滚（仅在下述第 5 节整体回滚且确认需要时执行；**只回滚代码不回滚库也可以**——旧代码
只会写 5 个旧状态值，0014 的新约束对旧值照常放行；0015 的索引对旧代码透明）：

```sql
-- 0015 回滚
DROP INDEX IF EXISTS public.idx_document_chunks_document_id;
DELETE FROM agent_rs.schema_migrations WHERE version = '0015';
-- 0014 回滚（先把新增状态的历史行改成 'failed'，否则旧约束建不起来）
UPDATE public.tool_jobs SET status = 'failed' WHERE status IN ('cancelled', 'outcome_unknown');
ALTER TABLE public.tool_jobs DROP CONSTRAINT IF EXISTS tool_jobs_status_check;
ALTER TABLE public.tool_jobs ADD CONSTRAINT tool_jobs_status_check
  CHECK (status IN ('pending', 'running', 'complete', 'failed'));
DELETE FROM agent_rs.schema_migrations WHERE version = '0014';
```

## 2. 新增/变更环境变量与推荐值

均写入生产 env 文件（systemd unit 里的 `/etc/agent-rs/backend.env`）。未列出的沿用现值。

| 环境变量（settings.py 字段） | 默认值/范围 | 推荐值 | 说明 |
|---|---|---|---|
| `AUTH_ADMIN_USER_IDS`（`auth_admin_user_ids`） | 空 | 运维负责人的用户 UUID（逗号分隔） | 管理端点按它判定管理员；留空则无人可管理 |
| `AUTH_HASH_MAX_CONCURRENCY`（`auth_hash_max_concurrency`） | 4（1–16） | 默认 4；小内存主机降 2 | Argon2 密码哈希并发，防登录风暴拖垮 CPU |
| `IMAGERY_MAX_BAND_COUNT`（`imagery_max_band_count`） | 64（1–512） | 默认 64 | GeoTIFF 波段数上限（G2），超限 413；配套 `IMAGERY_MAX_WORKING_BYTES`（默认 1 GiB，工作图字节数上限） |
| `SAM3_MAX_PIXELS`（`sam3_max_pixels`） | 67108864（64M 像元） | 与 GPU 侧一致：67108864（`ops/sam3_runtime/runtime-manifest.json` 的 `inference.max_pixels` 同值） | SAM3 输入像元预算（G3），超过先降采样再推理；配套 `SAM3_PREPROCESS_MAX_BYTES`（默认 256 MiB） |
| `DOCUMENT_OFFICE_MAX_TOTAL_UNCOMPRESSED_BYTES` | 100 MiB | 默认 | Office zip 解压总量上限（G1），超限 413 |
| `DOCUMENT_OFFICE_MAX_ENTRY_COMPRESSION_RATIO` | 100 | 默认 | 单条目压缩比上限 |
| `DOCUMENT_OFFICE_MAX_ENTRIES` | 10000（≤100000） | 默认 | 条目数上限 |
| `DOCUMENT_OFFICE_MAX_ENTRY_BYTES` | 32 MiB | 默认 | 单条目解压上限 |
| `DOCUMENT_MAX_TEXT_CHARS` / `DOCUMENT_MAX_SHEET_ROWS` / `DOCUMENT_MAX_SHEET_COLUMNS` | 2,000,000 / 100,000 / 1,024 | 默认 | 解析输出规模上限 |
| `DOCUMENT_PARSE_MAX_CONCURRENT` / `DOCUMENT_PARSE_TIMEOUT_SECONDS` / `DOCUMENT_PARSE_MEMORY_BYTES` | 2 / 60s / 768 MiB | 默认（并发=CPU 核数一半且 ≤2） | 解析子进程资源上限 |

## 3. 需要清理的旧缓存

S2 场景合成缓存带版本号（`composition_cache.COMPOSITION_VERSION`，当前为 3）：
**修复前合成的目录不会被新代码复用，只占磁盘**。逐用户清理：

- 位置：`settings.scene_cache_dir`（默认 `backend/storage/scenes`）下按用户分目录，
  其中的场景合成目录（含 `scene.tif`、`manifest.json`，导入完成后另有 `import.json` 标记）。
- 判定：`manifest.json` 里 `composition_version != 3` 的目录（含修复前的 band 顺序/定标错误产物）。
- 操作：停机窗口内删除这些目录即可，无数据库引用需要先解除（已导入影像的 `metadata.json`
  中 `composition_version` 已参与复用判定，不受影响）。
- 量化建议：清理前 `du -sh backend/storage/scenes` 留底，清理后再对比确认。

## 4. 会改变用户可见结果的修复清单

| 修复 | 用户可见变化 | 是否需通知 |
|---|---|---|
| 水体/云掩膜物理阈值（A1/A2，替代分位数封顶） | 水体/云占比不再被人为封顶，大水面、多云影像的统计会明显变大；晴空影像不再虚报阴影 | **建议通知**：重要场景建议重跑并对比 |
| S2 定标（A5，EVI/SAVI/MSVI 按反射率计算） | 指数值与旧版不同（旧值由 DN 直接算出，是错的）；无定标输入（如 GF-2 原始 DN）返回 `uncalibrated_input` 而非错误数值 | **建议通知** |
| NDVI 波段角色（A4） | STAC 合成影像红/近红外不再互换，植被 NDVI 符号正确；缺角色元数据时返回 `band_roles_unknown` 而非静默用 GF-2 默认值 | **建议通知** |
| 64 波段上限（G2） | 超过 64 波段（或工作图 >1 GiB）的 GeoTIFF 上传返回 413，旧版接受 | 需在发布说明列出 |
| Office 文档 zip 预检（G1） | 高压缩比/超限 docx/pptx/xlsx 返回 413，旧版接受（有解压炸弹风险） | 需在发布说明列出 |
| SAM3 像元预算（G3） | 超大影像先降采样再推理（同一 ROI、预算内分辨率），不再先整幅读入被服务端拒绝 | 需在发布说明列出 |
| SAM3 有效区掩膜 / 边缘切片方形补齐 / 碎片过滤 | 带透明边（NoData）的影像不再把无效区算作实例或面积；边缘目标轮廓不再因非方形切片被拉伸；低于最小面积阈值的碎片不再计入实例数（服务侧环境变量 `SAM3_MIN_INSTANCE_AREA`，默认 32 推理像元，设 0 关闭）。GPU 侧需同步部署新版 `ops/sam3_service.py` 并重算发布清单里的适配器摘要 | 需在发布说明列出 |
| 目标检测边缘切片方形补齐 | 任一维度短于 1024 的边缘/整图切片先补齐成 1024 方形再推理：分块边缘目标不再被 letterbox 自动重采样（小图上采样导致观测尺度与内部切片不一致），合成灰条不再进入推理输入（此前可能产生贴边假框）；补齐区不产生检出框。结果 JSON 的 runtime 新增 `edge_tiles_padded`。需重建并部署 `rs-detect-mcp` 镜像后生效 | 建议通知：边缘带检出数可能变化，重要影像建议重跑对比 |
| 非法 ID 统一 404（G8） | 会话/文档/记忆/报告的非法 UUID 由 500 变 404（与"不存在"同信封） | 无需专门通知 |
| 小用户向量召回（G9） | 多用户大库下小用户的 RAG/记忆检索结果更完整（取满 limit） | 无需专门通知 |
| 历史会话快速切换（G20） | 前端连点历史会话不再被慢请求覆盖成错误会话 | 无需专门通知 |
| GraphFlow 检索词（G14） | 报告等下游节点的检索 query 用用户原话而非上一位专家输出，引用可能变化 | 无需专门通知 |

## 5. 回滚步骤

1. **代码**：生产发布目录切回上一发布（`git checkout 61fdbc5` 对应的构建产物或旧镜像），
   重启服务（`sudo systemctl restart agent-rs`）。**不需要**先回滚数据库（见第 1 节）。
2. **数据库**：仅当诊断确认新迁移本身造成问题时，按第 1 节 SQL 手动回滚 0015 → 0014。
3. **缓存**：第 3 节清理不可逆但无回滚必要（旧代码会按旧版本号重算）。
4. **环境变量**：新增上限类变量留空即可回落默认值，无需删除。
5. 验证：`/api/health` 200；登录、上传、聊天 SSE 各一笔冒烟。

## 6. 运维提醒：Tavily 密钥轮换

`TAVILY_API_KEY` 已出现在旧会话的诊断输出里，视为已泄露：

1. Tavily 控制台作废旧 key、生成新 key。
2. 更新生产 env 文件（`/etc/agent-rs/backend.env`）中的 `TAVILY_API_KEY`
   （settings 字段 `tavily_api_key`，默认空=联网搜索禁用）。
3. `sudo systemctl restart agent-rs` 后，用任意需要联网搜索的问题冒烟验证。

另（随 G23）：同步 `ops/agent-rs.service` 到生产机后执行
`sudo systemctl daemon-reload && sudo systemctl restart agent-rs`，
`ss -tlnp | grep 5173` 应只显示 `127.0.0.1:5173`（详见 `docs/deployment.md`）。

## 7. 发布包内容规则（每次发布必须遵守）

发布目录（当前生产为 `/home/LRY/Agent-RS-current`）只允许包含平台运行所需文件。
发布包一律按**白名单**打包，禁止整仓复制。

### 7.1 白名单（只打包以下内容）

| 部分 | 允许内容 |
|---|---|
| 后端 | `backend/app/`、`backend/sql/`、`backend/pyproject.toml`、`backend/uv.lock` |
| 运维 | `deploy/`、`ops/` 中的运行文件（systemd unit、推理服务及其运行时、卫星目录准备脚本、发布校验脚本） |
| 容器 | `docker/` 中构建所需文件 |
| 前端 | 仅构建产物 `Agent-frontend/dist/`（含 satvis 资产） |

### 7.2 明确排除（包内出现即打包失败）

- `backend/tests/`，以及任何 `test_*.py`、`conftest.py` 文件
- 前端 `__tests__/` 目录、`*.test.ts(x)` 文件、`Agent-frontend/tests/`
- `docs/test-results/`、`.data/`、`recordings/`
- 各类评测脚本，以及工作规划与整改类文档（`docs/next-plan-*`、`docs/bugfix-plan-*`、`docs/test-remediation-*` 等）
- 前端源码与 `node_modules/`、本地存储目录（`storage/`、`backend/storage/`）

### 7.3 打包与部署方式

1. 打包脚本在打包完成后必须列出包内全部文件并逐条核对，命中 7.2 任一路径即终止报错，
   不允许带警告继续。
2. 禁止在服务器上以 `git clone` / `git pull` 整个仓库作为部署方式；服务器发布目录内容
   只能来自白名单发布包。
3. 前端只在发布机上执行 `ops/build_release_frontend.sh` 产出 `dist/`，服务器不执行前端构建。
