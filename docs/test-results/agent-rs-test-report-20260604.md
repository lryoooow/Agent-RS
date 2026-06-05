# Agent-RS 测试报告

生成日期：2026-06-04  
测试环境：Windows / PowerShell / Conda 环境 `agent-rs`  
项目路径：`D:\\Lry\\AI\\LLM\\agent-rs`

## 1. 最终结论

本次重新执行了两类测试：

| 测试层级 | 测试目标 | 结果 | 结论 |
| --- | --- | --- | --- |
| A/B 层确定性冒烟测试 | 路由触发、NDVI 触发、搜索触发、NDVI 数值计算、工具 runner 边界 | `21 passed, 5 warnings in 2.54s` | 通过 |
| 后端全量测试 | 后端 API、鉴权、安全边界、文档、影像、Agent、工具、向量检索等 | `143 passed, 7 warnings in 5.67s` | 通过 |

当前结论：确定性代码路径测试全部通过，未发现阻断性失败。告警均为测试环境或依赖层提示，不影响本次测试通过结论。

## 2. 原始结果文件

本次测试同时保存了原始 pytest 输出，便于后续复查：

- 冒烟测试原始输出：`docs/test-results/agent-rs-smoke-raw-20260604.txt`
- 后端全量测试原始输出：`docs/test-results/agent-rs-backend-all-raw-20260604.txt`

## 3. A/B 层确定性冒烟测试

### 3.1 执行命令

```powershell
D:\miniconda3\envs\\agent-rs\python.exe -m pytest `
  backend\tests\ai\test_routing_matrix.py `
  backend\tests\ai\test_ndvi_trigger_matrix.py `
  backend\tests\ai\test_search_trigger_matrix.py `
  backend\tests\ai\test_ndvi_compute.py `
  backend\tests\ai\test_ndvi_runner.py `
  backend\tests\ai\test_web_search_agent.py `
  -q -p no:cacheprovider --basetemp .test-tmp\pytest-smoke-report
```

### 3.2 测试结果

```text
21 passed, 5 warnings in 2.54s
```

### 3.3 覆盖模块

| 模块 | 测试内容 | 重点观察 |
| --- | --- | --- |
| 路由触发 | `DIRECT_CHAT` / `FULL_PIPELINE` 分类 | 是否把普通聊天、写代码、最新信息、RAG 场景分错 |
| 搜索触发 | `SKIP` / `FORCE` / `UNCERTAIN` 三态 | 是否错误联网、漏联网、重复联网 |
| NDVI 触发 | 解释类、计算类、有无影像 ID、可信上传上下文 | 是否把“解释 NDVI”误判成“计算 NDVI” |
| NDVI 数值计算 | 小尺寸合成 GeoTIFF、手算 ground truth | min/max/mean/std 是否与预期一致 |
| NDVI runner 边界 | 非法 imagery_id、非法波段、超出波段数 | 是否在执行前拦截错误输入 |
| Web Search Agent | mock 搜索结果链路 | 工具结果是否能被整理并进入回答链路 |

### 3.4 指标含义

| 指标 | 含义 | 本次结果 | 判断 |
| --- | --- | --- | --- |
| 触发准确率 | 规则路由和工具触发是否符合预期 | 所有用例通过 | 当前稳定 |
| 误触发率 | 不该进入工具/联网/NDVI 的输入是否被误触发 | 未出现失败 | 当前稳定 |
| 漏触发率 | 应该进入工具/联网/NDVI 的输入是否被漏掉 | 未出现失败 | 当前稳定 |
| NDVI 数值误差 | 计算结果与手算 ground truth 的差异 | 测试通过 | 当前稳定 |
| 非法输入拦截 | 错误 ID、错误波段是否在执行前拦住 | 测试通过 | 当前稳定 |

A/B 层是确定性代码，不应接受概率性通过。后续只要这类测试失败，就应该视为真实 bug 或规则变更，需要定位根因。

## 4. 后端全量测试

### 4.1 执行命令

```powershell
D:\miniconda3\envs\\agent-rs\python.exe -m pytest backend\tests -q -p no:cacheprovider --basetemp .test-tmp\pytest-all-report
```

### 4.2 测试结果

```text
143 passed, 7 warnings in 5.67s
```

### 4.3 覆盖模块

| 模块 | 覆盖重点 |
| --- | --- |
| API 路由 | 请求响应、错误分支、接口契约 |
| 鉴权与安全 | session、默认用户降级、请求大小、资源归属 |
| 文档模块 | 上传、查询、删除、用户隔离 |
| 影像模块 | 上传、预览、结果访问、删除、metadata 容错 |
| Agent 运行链路 | 路由、上下文构建、工具触发、流式/非流式结果 |
| NDVI 工具 | schema 校验、runner 边界、计算结果 |
| Web Search 工具 | 搜索触发、结果格式化、上下文注入 |
| 向量检索 | 文档向量、用户隔离、查询路径 |

## 5. 本次告警说明

### 5.1 Rasterio NotGeoreferencedWarning

出现位置：`tests/ai/test_ndvi_runner.py`

含义：测试里使用的是小尺寸合成 GeoTIFF，没有真实地理变换、GCP 或 RPC 信息，因此 rasterio 使用 identity matrix。

判断：这是测试数据特性导致的告警，不代表真实影像处理失败。真实 GF-2 / WV3 等遥感影像通常带坐标信息，应在 live 数据测试中单独观察 bounds、CRS 和地图叠加效果。

### 5.2 Starlette TestClient DeprecationWarning

出现位置：FastAPI / Starlette 测试客户端。

含义：依赖库提示未来版本中 TestClient 行为会调整。

判断：不影响当前测试结果。后续升级 FastAPI/Starlette/httpx 时需要关注。

### 5.3 Cookie DeprecationWarning

出现位置：`tests/auth/test_security.py`

含义：Starlette 提示 per-request cookies 写法未来可能变化。

判断：不影响当前安全测试结果。后续可把测试里的 cookies 设置迁移到 client 实例级别。

## 6. 当前测试结论如何解读

| 结论 | 代表什么 | 不代表什么 |
| --- | --- | --- |
| A/B 冒烟通过 | 规则触发和工具确定性执行当前稳定 | 不代表真实 LLM 回答质量已经最优 |
| 后端全量通过 | 现有后端回归测试未发现失败 | 不代表没有未覆盖的业务场景 |
| NDVI 合成数据通过 | 核心公式、边界拦截、结果统计正常 | 不代表真实大影像性能、坐标叠加都已验证 |
| Web Search mock 通过 | Agent 能接收并整理搜索结果 | 不代表真实联网搜索结果一定最佳 |

## 7. 后续建议测试阶段

### 阶段 C：真实数据 live 测试

使用真实 GF-2 影像：

```text
D:\Lry\预研\图像融合\NND\GF-2\GF2_PMS2_E115.9_N22.9_20211210_L1A0006125619\GF2_PMS2_E115.9_N22.9_20211210_L1A0006125619-MSS2.tif
```

重点观察：

- 上传耗时
- preview 生成耗时
- 影像尺寸与压缩后 working 尺寸
- bounds / CRS 是否正确
- 地图原图图层是否正常展示
- NDVI 计算耗时
- NDVI 输出统计值是否合理
- Docker MCP 是否成功执行，是否发生本地回退

### 阶段 D：真实联网搜索质量测试

重点观察：

- 是否应该联网时触发联网
- 是否不该联网时避免联网
- 来源是否可信
- 回答是否引用来源
- 首字延迟和总耗时
- 搜索失败时是否能给出清晰降级说明

### 阶段 E：Prompt 消融测试

前提：A/B 确定性测试和 C/D live 测试稳定后再做。

重点观察：

- 删除 few-shot 后回答质量是否下降
- 简化 system prompt 后是否更容易越界
- NDVI 场景 prompt 是否能稳定输出业务化解释
- Web Search prompt 是否能稳定带来源、不编造

## 8. 本次保存的最终判断

本次测试结果可以作为 Agent-RS 当前阶段的基础质量基线：

- 确定性触发层：通过
- 工具执行层：通过
- 后端回归层：通过
- 真实大影像性能：尚未在本报告中执行
- 真实联网搜索质量：尚未在本报告中执行
- Prompt 消融：尚未执行

下一步应进入真实 GF-2 影像 live 测试，并将上传、预览、NDVI、地图展示、Docker MCP 执行状态和耗时指标继续保存为报告。
