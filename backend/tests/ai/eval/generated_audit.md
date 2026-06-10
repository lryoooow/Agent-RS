# LLM Planner Generated Case Audit

本报告用于抽检第一批程序化生成的遥感工具路由评测题库。当前批次只作为 prompt 消融前的评测尺子扩充，不代表最终泛化结论；300 条质量确认后再扩展到 1000+。

## Summary

- Golden cases: 30
- Generated cases: 300
- Generated buckets:
  - simple: 120
  - none: 90
  - multiple: 45
  - parallel: 45
- Generated none ratio: 30.0%
- Diagnostic unsupported multi-tool cases: 30
- Prompt-near generated cases: 2

## Scoring Policy

- `scoring="main"`: 计入主准确率。
- `scoring="diagnostic_unsupported"`: 只进入诊断块，不计入主准确率。
- `prompt_near=True`: 单独统计，不进入 hard score。
- `parallel_web_search`: 只校验 `queries` 的结构（是 list、有效条数 >= `min_query_count`），不做任何关键词/语义比对；检索语义质量留给后续独立 judge 诊断。

## Sample Checks

| bucket | case_id | expected | scoring | sample query |
| --- | --- | --- | --- | --- |
| simple | gen_raster_inspect_simple_001 | raster_inspect | main | 检查影像 94e758f38ede 的元数据 |
| none_negation | gen_none_negation_001 | none | main | 我不要算NDVI，只想知道它是什么 |
| none_concept | gen_none_concept_001 | none | main | 影像 94e758f38ede 的近红外波段通常代表什么？ |
| none_missing_id | gen_none_missing_id_001 | none | main | 计算刚才那张图的NDVI |
| edge_non_owner | gen_edge_non_owner_001 | none | main | 请对影像 aaaaaaaaaaaa 做NDVI |
| none_contradiction | gen_none_contradiction_001 | none | main | 用 NDVI 算法检测影像 94e758f38ede 里的船只 |
| multiple | gen_multiple_water_mask_001 | extract_water_mask | main | 我关注影像 94e758f38ede 的水域边界，不要只给指数，直接圈出水体范围 |
| parallel_web_search | gen_parallel_web_search_weather_travel_001 | web_search | main | 明天南京天气怎么样？如果适合出行，再给我一个两天自驾计划 |
| unsupported_multi_tool | gen_unsupported_multi_tool_001 | none | diagnostic_unsupported | 对影像 94e758f38ede 同时计算 NDVI 并提取水体掩膜 |

## Prompt-Near Cases

- `gen_ndvi_simple_001`
- `gen_segment_landcover_simple_001`

这两条与 planner prompt few-shot 高度相似，保留用于可复现锚点，但从 hard score 中剔除。

## Gate Checks

- 生成器确定性: 同一代码重复生成，fingerprint 相同。
- 参数覆盖: `imagery_id`、`document_id`、`index_type`、`mode`、`dst_crs`、多条 `queries` 结构均已覆盖。
- 对抗类别: 否定、概念、缺 ID、非属主、矛盾诱导、unsupported multi-tool 均已覆盖。
- CI replay: 当前只跑已录制的 30 条 golden 基线，录制目录为 `recordings/ci_subset/`。

## Next Step

确认本批题目质量后，再运行 300 条 live 基线并写入 `recordings/live_runs/<tag>/`。若基线仍接近满分，不下调验收阈值，而是继续补合法难例。
