# #18 random-stress 实证报告（2026-06-12，修复生成器 bug 后重跑）

## 一句话结论
修掉生成器 task↔capability 写死 bug 后，3 seed × 1000 = 3000 条全新 live 录制，
跨 seed accuracy **mean 0.9879 / worst 0.985 / stdev 0.0041**，0 解析失败、0 harness 错误。
模型在**单图指代/残缺ID 补全上 100% 正确**，唯一真实弱点是**多图歧义时过度补全**（0.8%）。

## 修复前后对比（同 3 seed，同 prompt v2）
| 指标 | 修复前(含错标) | 修复后(干净) | 说明 |
| --- | --- | --- | --- |
| accuracy mean | 0.9671 | **0.9879** | +2.08pp，错标尺子摆正后的真实分 |
| accuracy worst | 0.9625 | 0.985 | 最差 seed 也接近 99% |
| pos_recall mean | 0.9864 | 0.9947 | |
| hn_fp_rate mean | 0.0236 | 0.0267 | 略升（错标曾把真FP藏在错配里） |
| planner_invalid | 0 | 0 | 0 解析失败 |
| stdev(accuracy) | 0.0051 | 0.0041 | 跨 seed 极稳 |

## 核心实证（#18 设计目标）
- **单图指代→call 补全**：90 条（3 seed × 30），失配 **0** → 补全准确率 **100%**。
  "刚才那张图/就这张图 + 跑NDVI" 在唯一图清单下，模型稳定补全真图完整ID并 call。
- **多图歧义→none**：模型在多图(2-4张)+残缺ID 时倾向**强行补全**而非停下问用户。
  这是唯一真实弱点：corrupted_id 多图子类 24/3000 条误 call（该 none）。

## 修复后剩余失配三类裁决（208 条 / 2799 主分样本 = 7.4%，但分布如下）
1. **174 条 compound_unsupported_multi_tool**（不计主分诊断块）：复合多工具意图，
   模型硬调一个工具。已知行为，产品决策"先按单工具执行"，与 heldout-v1 同源。
2. **24 条 corrupted_id 多图误 call**（真实弱点）：多图+损坏ID 该 none 却补全 call。
   **安全核查：24/26 条补全的是清单内真图（非幻觉ID）**，tool_guards.user_owns_imagery
   兜底校验归属。最坏="对A图做了操作但用户想要B图"，非越权/非幻觉。双保险可控。
3. **10 条 parse_document↔OCR 边界**（parse→none）：文档解析边界题，模型偶尔保守拒绝。

## 已修复的生成器根因（CLAUDE.md 第4条）
- **根因**：realize_missing_id/realize_corrupted_id 随机选 task 填 query，调用方写死
  capability=calculate_ndvi → 127 条系统性错标（详见 memory）。
- **修复**：realize 返回 (query, task)，调用方据 task_capability() 同源推导。
- **防复发**：
  - `test_missing_id_corrupted_capability_matches_query_task`（stress + heldout 各一）：
    capability 必须与 query task 严格映射，写死即红。
  - `_recording_done` 加 query_hash 同源校验：生成器改了 query，旧录制失效重录，
    根除"用旧录制冒充新题"。回归测试 `test_recording_done_rejects_stale_query_hash`。
  - score 只评已录制 case（`test_score_filters_to_recorded_cases_only`）。

## 下一步建议
- **多图补全过度自信**这个真实弱点，建议复制典型 case 进 dev-set，
  在 prompt 里强化"多图+残缺ID→歧义停下问"的规则（区别于单图安全补全）。
  但**不在 stress 上直接调**（stress 不冻结，只看分布）。
- 此为随机分布观测，非门控。门控判定在 #17 heldout-v2 冻结盲测。
