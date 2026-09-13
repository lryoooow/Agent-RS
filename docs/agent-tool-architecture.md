# Agent-RS Agent and Tool Architecture

Agent-RS 只使用 AutoGen 作为生成式 Agent 编排框架。聊天回答、标准流程路由、领域协作、
联网搜索和长期记忆判断都经过 AutoGen；embedding、rerank、资源鉴权和遥感计算保持确定性。

## 请求路径

```text
ChatRequest
  → build_turn_input：历史 + 安全 system prompt + 地图 + 影像/文档清单 + 既有结果
  → flow_router（AutoGen structured output）
      ├─ 完整命中标准作业 → GraphFlow
      └─ 不完整 / 不确定 / 自由任务 → SelectorGroupChat
  → general / navigation / spectral / preprocess / segmentation / detection /
    document / report / search AssistantAgent
  → 统一工具执行管线
  → AutoGen event bridge → 既有 SSE 与 ChatResponse
```

路由失败必须回退到 SelectorGroupChat，不得根据不完整请求猜测一个固定流程。当前标准流程：

- `inspect_index_report`：影像质检与指数计算 → 报告
- `mask_segment_report`：云阴影掩膜 → 地物分类 → 报告
- `detect_report`：目标检测 → 报告

## 单一注册表

`backend/app/agent/tool_registry.py` 是工具契约与所有权的唯一数据源。每个工具声明：

- 唯一名称、Pydantic 参数模型和 async runner
- `agent_name`：唯一持有它的 AutoGen Agent
- `resource_kind`：`imagery`、`document`、`conversation` 或 `none`
- 可用性判据、模型可见描述和 tags

发给模型的 function 定义**不再手写**：`app/agent/tools/schema_gen.py` 在注册时从
Pydantic 参数模型生成（default/ge/pattern/description 全部来自 `Field`，归一化规则见
该模块文档），约束与描述只有参数模型这一份来源。`tests/agent/test_tool_schema_gen.py`
锁定生成形状，改字段约束必须过这组快照。

Agent 清单和资源 guard 都从注册表派生，不再维护并行的 routing、capability 或 domain 映射表。
新增工具时必须登记所有权与资源类型，并为执行阶段文案增加标签。

## 工具执行与安全边界

`backend/app/agent/tool_execution.py` 是唯一工具执行实现：

```text
工具可用性 → 参数模型校验 → 资源归属鉴权 → durable 队列登记
→ 影像 staging → runner → 终态落库
```

每一次工具调用都独立经过上述管线。模型不能声明用户身份；身份来自请求级 contextvar。
影像和文档 ID 只能来自该用户的可信清单，未知、歧义或非属主资源会在执行前拒绝。

遥感 runner 继续通过受控的 stdio MCP 客户端调用 Docker 容器。MCP `tools/list` 不用于动态
信任或注册外部工具。

## 上下文与 Memory

`engine/input.py` 复用既有 request builder，一次装配完整可信上下文，并为 group manager 与
每个 Agent 创建独立的 `BudgetedChatCompletionContext`。当前用户消息只作为 AutoGen task
发送一次，避免重复。

影像清单是结构化的：上传时 `_extract_metadata` 提取波段描述与标签，派生
`band_roles`（角色→波段号，描述优先、位置约定兜底）与传感器/拍摄时间；清单按最新优先、
`AGENT_IMAGERY_INVENTORY_LIMIT` 条数上限注入。模型选 `red_band`/`nir_band` 等参数以
角色表为准，不再依赖「GF-2 默认波序」的硬编码假设。老影像元数据缺新字段时自动回退
位置约定，零迁移。

RAG 与长期记忆实现 AutoGen `Memory` 协议，在每次 Agent 模型调用前按当前问题更新。
检索块按来源覆盖，纳入 token 预算，避免多步链路重复注入。记忆判官也使用 AutoGen
structured output；embedding 与写库仍走确定性服务。

## 框架边界

只有 `backend/app/agent/engine/` 可以直接导入 `autogen_*`。业务层通过
`app.agent.engine` 门面调用框架能力，这条约束由 `backend/tests/test_engine_boundary.py`
做 AST 检查。

主要模块：

| 模块 | 职责 |
| --- | --- |
| `engine/input.py` | 完整请求上下文转 AutoGen 消息 |
| `engine/router.py` | 结构化 GraphFlow/Selector 路由 |
| `engine/agents.py` | 通用、导航和领域 AssistantAgent |
| `engine/flows.py` | 固定标准作业 GraphFlow |
| `engine/orchestrator.py` | 团队构造、执行、终止与收尾 |
| `engine/tools.py` | 注册工具的 AutoGen 包装 |
| `engine/search.py` | 可多轮检索的搜索 Agent |
| `engine/memory/` | RAG 与长期记忆协议适配 |
| `engine/memory_judge.py` | 结构化记忆判断 |
| `engine/event_bridge.py` | AutoGen 消息映射为现有 SSE trace |
| `engine/service.py` | AIService 使用的流式/非流式入口 |

## 运行约束

- `[DONE]` 只在 Agent 消息末尾触发终止，避免规则复述误杀流程。
- `[DONE]`、进度自检、推理标签和显式过程旁白不进入用户正文；流式路径用有状态 sanitizer
  处理跨分片标记，并在推理块未闭合时 fail closed。
- 原始 reasoning/thought 不建立 SSE 契约、不进入 `agent_trace`、不持久化。前端只接受
  `thinking_summary`，阶段和文案均来自固定枚举；服务端事件中的任意 label 不会被渲染。
- AutoGen 的 core/agentchat event 与 trace logger 固定为 WARNING，避免其 INFO 事件记录完整
  system prompt、历史消息、工具结果和模型 thought。
- 路由模型自由文本 reason 仅在内存中用于诊断分类，不进入 SSE trace 或日志；失败元数据只保存
  error code/type，不保存可能携带供应商请求或响应正文的异常字符串。
- 落库正文合并所有专家的可见结论，不能只保留最后一条。
- 前端断连使用 `ExternalTermination` 停止后续步骤，并后台排空在飞调用后关闭模型客户端。
- `AGENT_MAX_TOOL_ITERATIONS` 限制工具循环；GPU 工具和联网搜索另有按回合硬配额。
- `mcp` 依赖固定在 `<2`，与当前 AutoGen 版本保持兼容。

## 测试与评测

评测录制格式为 schema v2：按顺序保存 router、selector、Agent 以及每次工具调用，附带
`strategy` 与 `flow_name`。旧单次规划 JSON 录制已经移除。红队仍独立检查越权资源、
幻觉 ID、文档注入和过度代理；所有执行层安全结论以统一工具 guard 为准。
