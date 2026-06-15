# Planner Prompt Dev-Set Analysis

> 说明：本报告是 dev-set 分析，只说明当前 300 条程序化题库上的表现，不代表泛化结论。
> live 调用只用于录制 raw 输出；正式分数均来自 historical replay。

## Summary

| run | main acc | main FP | main FN | positive acc | hard_negative FP | diagnostic FP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_structure_only | 92.9% | 19 | 0 | 100.0% | 19 | 24 |

## Baseline hard_negative FP

- FP count: 19
- By category: none_contradiction=7, none_missing_id=12
- By actual capability: calculate_ndvi=3, cloud_shadow_mask=3, detect_objects=7, extract_water_mask=3, segment_landcover=3

| case_id | category | actual | attribution | selector/validator reason | query |
| --- | --- | --- | --- | --- | --- |
| gen_none_missing_id_001 | none_missing_id | calculate_ndvi | planner_mismatch | planner_action_mismatch | 计算刚才那张图的NDVI |
| gen_none_contradiction_001 | none_contradiction | detect_objects | planner_mismatch | planner_action_mismatch | 用 NDVI 算法检测影像 94e758f38ede 里的船只 |
| gen_none_missing_id_002 | none_missing_id | extract_water_mask | planner_mismatch | planner_action_mismatch | 给这张影像做水体掩膜，但我没有提供影像 ID |
| gen_none_missing_id_003 | none_missing_id | segment_landcover | planner_mismatch | planner_action_mismatch | 帮我处理上面那张图的地物分割 |
| gen_none_missing_id_004 | none_missing_id | cloud_shadow_mask | planner_mismatch | planner_action_mismatch | 计算刚才那张图的云检测 |
| gen_none_contradiction_004 | none_contradiction | detect_objects | planner_mismatch | planner_action_mismatch | 用重投影功能识别 94e758f38ede 里的车辆 |
| gen_none_contradiction_005 | none_contradiction | detect_objects | planner_mismatch | planner_action_mismatch | 用 NDVI 算法检测影像 94e758f38ede 里的船只 |
| gen_none_missing_id_006 | none_missing_id | calculate_ndvi | planner_mismatch | planner_action_mismatch | 帮我处理上面那张图的NDVI |
| gen_none_missing_id_007 | none_missing_id | extract_water_mask | planner_mismatch | planner_action_mismatch | 计算刚才那张图的水体掩膜 |
| gen_none_missing_id_008 | none_missing_id | segment_landcover | planner_mismatch | planner_action_mismatch | 给这张影像做地物分割，但我没有提供影像 ID |
| gen_none_contradiction_008 | none_contradiction | detect_objects | planner_mismatch | planner_action_mismatch | 用重投影功能识别 94e758f38ede 里的车辆 |
| gen_none_missing_id_009 | none_missing_id | cloud_shadow_mask | planner_mismatch | planner_action_mismatch | 帮我处理上面那张图的云检测 |
| gen_none_contradiction_009 | none_contradiction | detect_objects | planner_mismatch | planner_action_mismatch | 用 NDVI 算法检测影像 94e758f38ede 里的船只 |
| gen_none_missing_id_011 | none_missing_id | calculate_ndvi | planner_mismatch | planner_action_mismatch | 给这张影像做NDVI，但我没有提供影像 ID |
| gen_none_missing_id_012 | none_missing_id | extract_water_mask | planner_mismatch | planner_action_mismatch | 帮我处理上面那张图的水体掩膜 |
| gen_none_contradiction_012 | none_contradiction | detect_objects | planner_mismatch | planner_action_mismatch | 用重投影功能识别 94e758f38ede 里的车辆 |
| gen_none_missing_id_013 | none_missing_id | segment_landcover | planner_mismatch | planner_action_mismatch | 计算刚才那张图的地物分割 |
| gen_none_contradiction_013 | none_contradiction | detect_objects | planner_mismatch | planner_action_mismatch | 用 NDVI 算法检测影像 94e758f38ede 里的船只 |
| gen_none_missing_id_014 | none_missing_id | cloud_shadow_mask | planner_mismatch | planner_action_mismatch | 给这张影像做云检测，但我没有提供影像 ID |

## Baseline diagnostic_unsupported

- Diagnostic FP count: 24
- By selected capability: calculate_ndvi=6, cloud_shadow_mask=6, ocr_recognize=6, render_band_composite=6
- Selected first requested task: 24/24

| case_id | selected | first_requested_task | query |
| --- | --- | --- | --- |
| gen_unsupported_multi_tool_001 | calculate_ndvi | calculate_ndvi | 对影像 94e758f38ede 同时计算 NDVI 并提取水体掩膜 |
| gen_unsupported_multi_tool_002 | cloud_shadow_mask | cloud_shadow_mask | 先给影像 94e758f38ede 做云掩膜，再马上做地物分割 |
| gen_unsupported_multi_tool_004 | ocr_recognize | ocr_recognize | 同时读取影像 94e758f38ede 的文字注记并计算 NBR 指数 |
| gen_unsupported_multi_tool_005 | render_band_composite | render_band_composite | 对影像 94e758f38ede 一次完成真彩色预览和目标检测 |
| gen_unsupported_multi_tool_006 | calculate_ndvi | calculate_ndvi | 对影像 94e758f38ede 同时计算 NDVI 并提取水体掩膜 |
| gen_unsupported_multi_tool_007 | cloud_shadow_mask | cloud_shadow_mask | 先给影像 94e758f38ede 做云掩膜，再马上做地物分割 |
| gen_unsupported_multi_tool_009 | ocr_recognize | ocr_recognize | 同时读取影像 94e758f38ede 的文字注记并计算 NBR 指数 |
| gen_unsupported_multi_tool_010 | render_band_composite | render_band_composite | 对影像 94e758f38ede 一次完成真彩色预览和目标检测 |
| gen_unsupported_multi_tool_011 | calculate_ndvi | calculate_ndvi | 对影像 94e758f38ede 同时计算 NDVI 并提取水体掩膜 |
| gen_unsupported_multi_tool_012 | cloud_shadow_mask | cloud_shadow_mask | 先给影像 94e758f38ede 做云掩膜，再马上做地物分割 |
| gen_unsupported_multi_tool_014 | ocr_recognize | ocr_recognize | 同时读取影像 94e758f38ede 的文字注记并计算 NBR 指数 |
| gen_unsupported_multi_tool_015 | render_band_composite | render_band_composite | 对影像 94e758f38ede 一次完成真彩色预览和目标检测 |
| gen_unsupported_multi_tool_016 | calculate_ndvi | calculate_ndvi | 对影像 94e758f38ede 同时计算 NDVI 并提取水体掩膜 |
| gen_unsupported_multi_tool_017 | cloud_shadow_mask | cloud_shadow_mask | 先给影像 94e758f38ede 做云掩膜，再马上做地物分割 |
| gen_unsupported_multi_tool_019 | ocr_recognize | ocr_recognize | 同时读取影像 94e758f38ede 的文字注记并计算 NBR 指数 |
| gen_unsupported_multi_tool_020 | render_band_composite | render_band_composite | 对影像 94e758f38ede 一次完成真彩色预览和目标检测 |
| gen_unsupported_multi_tool_021 | calculate_ndvi | calculate_ndvi | 对影像 94e758f38ede 同时计算 NDVI 并提取水体掩膜 |
| gen_unsupported_multi_tool_022 | cloud_shadow_mask | cloud_shadow_mask | 先给影像 94e758f38ede 做云掩膜，再马上做地物分割 |
| gen_unsupported_multi_tool_024 | ocr_recognize | ocr_recognize | 同时读取影像 94e758f38ede 的文字注记并计算 NBR 指数 |
| gen_unsupported_multi_tool_025 | render_band_composite | render_band_composite | 对影像 94e758f38ede 一次完成真彩色预览和目标检测 |
| gen_unsupported_multi_tool_026 | calculate_ndvi | calculate_ndvi | 对影像 94e758f38ede 同时计算 NDVI 并提取水体掩膜 |
| gen_unsupported_multi_tool_027 | cloud_shadow_mask | cloud_shadow_mask | 先给影像 94e758f38ede 做云掩膜，再马上做地物分割 |
| gen_unsupported_multi_tool_029 | ocr_recognize | ocr_recognize | 同时读取影像 94e758f38ede 的文字注记并计算 NBR 指数 |
| gen_unsupported_multi_tool_030 | render_band_composite | render_band_composite | 对影像 94e758f38ede 一次完成真彩色预览和目标检测 |
