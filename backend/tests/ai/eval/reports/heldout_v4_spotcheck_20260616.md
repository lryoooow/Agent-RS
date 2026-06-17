# heldout-v4 人工抽检报告（分层抽样，每 category 12.5%）

- dataset_hash: `aeeab8e8643463f2cfab445e87328e188253d83f082a3650e0746c66ddd0102d`
- seed: 20260617  case_count: 1000  sampled: 126
- 抽样：按 category 分层、seed 确定性随机，每子类至少 1 条——任何子类都不会成为盲区。
- 检查点：①表达无歧义 ②场景合理 ③label 与场景一致。
- 纪律：发现错标不许单条改题；整体废弃本数据集（删除冻结目录——它尚未运行），换新 seed 重新生成冻结。

| # | case_id | expected | query |
| --- | --- | --- | --- |
| 2 | heldout_pos_calculate_spectral_index_002 | calculate_spectral_index | 麻烦了，1c46ef9cc4c2 需要做 水体指数 NDWI 分析，今天要 |
| 5 | heldout_pos_extract_water_mask_005 | extract_water_mask | 急用，我要 a69737f93564 的水域边界图层 |
| 6 | heldout_pos_clip_reproject_raster_006 | clip_reproject_raster | 辛苦帮个忙，85306f58963a 帮我换到 EPSG:32649 这个坐标系，拜托拜托 |
| 10 | heldout_pos_parse_document_010 | parse_document | 麻烦了，把 39f9cc1f-d0a2-4a10-4173-a7ede306031e 里的章节要点列一列 麻烦尽快 |
| 11 | heldout_pos_web_search_011 | web_search | 麻烦了，查查 2026 年新发布的开源遥感数据集有哪些，拜托拜托 |
| 28 | heldout_pos_cloud_shadow_mask_028 | cloud_shadow_mask | 急用，44db512241b1 需要云和云影的质检掩膜 |
| 37 | heldout_pos_calculate_ndvi_037 | calculate_ndvi | 在吗？想请教下，评估下 de9ef8a8d181 的植被覆盖，用 NDVI 就行，拜托拜托 |
| 38 | heldout_pos_calculate_spectral_index_038 | calculate_spectral_index | 急用，算 建筑指数 NDBI 吧，影像是 83ffdd35497c，今天要 |
| 43 | heldout_pos_detect_objects_043 | detect_objects | 嗨，那个，扫一下 9d4c9a6c49e5 看看飞机在哪，先这样 |
| 44 | heldout_pos_segment_landcover_044 | segment_landcover | 嗨，那个，我要 2d21aa33b10a 的 landcover 分割结果 越快越好 |
| 47 | heldout_pos_web_search_047 | web_search | 对了，帮我查今天北京的空气质量指数 谢谢啦 |
| 54 | heldout_pos_clip_reproject_raster_054 | clip_reproject_raster | 在吗？想请教下，对 f41878824226 做投影转换，目标 EPSG:32649，先这样 |
| 61 | heldout_pos_calculate_ndvi_061 | calculate_ndvi | 对了，评估下 dc239ea8e032 的植被覆盖，用 NDVI 就行 |
| 63 | heldout_pos_render_band_composite_063 | render_band_composite | 在吗？想请教下，真彩色合成图来一张，用 d3babfcf63ad 越快越好 |
| 71 | heldout_pos_web_search_071 | web_search | 辛苦帮个忙，下周成都的天气趋势帮我查下 |
| 83 | heldout_pos_web_search_083 | web_search | 下周成都的天气趋势帮我查下 谢谢啦 |
| 88 | heldout_pos_cloud_shadow_mask_088 | cloud_shadow_mask | 麻烦了，94220cd1f08b 需要云和云影的质检掩膜，拜托拜托 |
| 93 | heldout_pos_ocr_recognize_093 | ocr_recognize | 辛苦帮个忙，fb02b19bbfb3 的图廓注记帮我转成文本，先这样 |
| 96 | heldout_pos_raster_inspect_096 | raster_inspect | 在吗？想请教下，帮我确认 a0d67298981c 的投影和覆盖范围对不对，今天要 |
| 108 | heldout_pos_raster_inspect_108 | raster_inspect | 辛苦帮个忙，上传的 00daa7004dbd 是多少波段的？顺便看下 CRS，先这样 |
| 109 | heldout_pos_calculate_ndvi_109 | calculate_ndvi | 急用，我要 30119b40f95a 的 NDVI 结果图 麻烦尽快 |
| 127 | heldout_pos_detect_objects_127 | detect_objects | 麻烦了，扫一下 5c488a1f3d1b 看看桥在哪 谢谢啦 |
| 130 | heldout_pos_parse_document_130 | parse_document | d52a218e-0123-01ce-a618-8e331faddbcf 内容整理成几条要点 麻烦尽快 |
| 135 | heldout_pos_render_band_composite_135 | render_band_composite | 在吗？想请教下，用假彩色方案把 8cf8b4e078a9 显示出来 麻烦尽快 |
| 161 | heldout_pos_extract_water_mask_161 | extract_water_mask | 嗨，那个，a8261ed33301 做水体提取，掩膜给我，今天要 |
| 170 | heldout_pos_calculate_spectral_index_170 | calculate_spectral_index | 急用，对 1a05c267f428 来个 建筑指数 NDBI 的结果 越快越好 |
| 172 | heldout_pos_cloud_shadow_mask_172 | cloud_shadow_mask | cccd4f0abd3f 好像有云，先把云和阴影圈出来质检下 |
| 176 | heldout_pos_segment_landcover_176 | segment_landcover | 麻烦了，把 2c13247c03d5 按地类切成一块块的 越快越好 |
| 187 | heldout_pos_detect_objects_187 | detect_objects | 嗨，那个，扫一下 14d28b9db2df 看看桥在哪 谢谢啦 |
| 188 | heldout_pos_segment_landcover_188 | segment_landcover | f42eacadd952 整景做地物分类分割 谢谢啦 |
| 209 | heldout_pos_extract_water_mask_209 | extract_water_mask | 嗨，那个，6163b6d60d27 哪里是水，出个水体掩模，先这样 |
| 216 | heldout_pos_raster_inspect_216 | raster_inspect | 嗨，那个，查询影象 9249a72c33a3 的 profile 信息 谢谢啦 |
| 222 | heldout_pos_clip_reproject_raster_222 | clip_reproject_raster | 麻烦了，d94f1fdb6faa 现在的投影不对，统一到 EPSG:32650，今天要 |
| 229 | heldout_pos_calculate_ndvi_229 | calculate_ndvi | 在吗？想请教下，评估下 52cf1015ef67 的植被覆盖，用 NDVI 就行，今天要 |
| 231 | heldout_pos_render_band_composite_231 | render_band_composite | 真彩色合成图来一张，用 c5d5732ba7db，拜托拜托 |
| 238 | heldout_pos_parse_document_238 | parse_document | 把 b436a0f0-7674-19ea-b275-6c1be9cfe7e8 里的章节要点列一列，拜托拜托 |
| 246 | heldout_pos_clip_reproject_raster_246 | clip_reproject_raster | 辛苦帮个忙，重头影：3e76751490e5 转 EPSG:32649，谢谢，拜托拜托 |
| 250 | heldout_pos_parse_document_250 | parse_document | 对了，帮我读文档 5a206cee-fbfd-8d79-2fd5-7d979ebd79ce，给个摘要，拜托拜托 |
| 261 | heldout_pos_ocr_recognize_261 | ocr_recognize | 6b3e8ab750c5 里印的文字内容提取一下，拜托拜托 |
| 266 | heldout_pos_calculate_spectral_index_266 | calculate_spectral_index | 急用，出一份 43cb36b0135b 的 水分指数 NDMI 图，今天要 |
| 267 | heldout_pos_render_band_composite_267 | render_band_composite | 对了，a109cb3dedd5 出个假彩色预览，拜托拜托 |
| 273 | heldout_pos_ocr_recognize_273 | ocr_recognize | 对了，认一下 9c5a43365fe8 上面标注的地名文字，今天要 |
| 283 | heldout_pos_detect_objects_283 | detect_objects | 辛苦帮个忙，45510c0138f4 里有没有飞机，帮我框出来 越快越好 |
| 332 | heldout_pos_segment_landcover_332 | segment_landcover | 嗨，那个，我要 7824a6a0d8ed 的 landcover 分割结果，拜托拜托 |
| 340 | heldout_pos_cloud_shadow_mask_340 | cloud_shadow_mask | 在吗？想请教下，fb7e4c67729e 的云量情况出个掩膜评估下 越快越好 |
| 341 | heldout_pos_extract_water_mask_341 | extract_water_mask | 急用，我要 ab350a003c56 的水域边界图层，今天要 |
| 345 | heldout_pos_ocr_recognize_345 | ocr_recognize | 对了，5fb623c4d884 这张扫描图上的字帮我读出来 越快越好 |
| 348 | heldout_pos_raster_inspect_348 | raster_inspect | 嗨，那个，上传的 2871da21370c 是多少波段的？顺便看下 CRS，先这样 |
| 350 | heldout_neg_negation_000 | none | 我现在不需要你跑 NDVI，只想听原理 |
| 351 | heldout_neg_concept_001 | none | 在吗？想请教下，为什么大家都用 近红外波段，优缺点呢 谢谢啦 |
| 390 | heldout_neg_general_040 | none | 麻烦了，帮我润色一段答辩稿 |
| 405 | heldout_neg_concept_055 | none | 近红外波段 和普通照片处理的区别是啥 越快越好 |
| 406 | heldout_neg_missing_id_056 | calculate_ndvi | 麻烦了，对刚才传的那个直接做 NDVI 越快越好 |
| 409 | heldout_neg_contradiction_059 | none | 麻烦了，用 NDVI 这个算法看看 ea5c750dd2a0 里有几条船，拜托拜托 |
| 414 | heldout_neg_general_064 | none | 急用，Excel 怎么做数据透视表 |
| 437 | heldout_neg_non_owner_087 | none | 对了，用 15d02bf6be02 跑 NDVI，先这样 |
| 446 | heldout_neg_negation_096 | none | 嗨，那个，先别动手算，就跟我讲讲 目标检测 是怎么回事，拜托拜托 |
| 449 | heldout_neg_non_owner_099 | none | 辛苦帮个忙，麻烦处理 b0fb87d2dfb5 的地物分割 越快越好 |
| 450 | heldout_neg_general_100 | none | 急用，用 python 写个二分查找 越快越好 |
| 466 | heldout_neg_missing_id_116 | none | 麻烦了，对刚才传的那个直接做 NDVI，今天要 |
| 478 | heldout_neg_missing_id_128 | calculate_ndvi | 辛苦帮个忙，那张图的 NDVI 安排一下 谢谢啦 |
| 481 | heldout_neg_contradiction_131 | none | 麻烦了，拿云掩膜工具把文档 02a71eea-6ebb-7f69-0c76-47f89787caea 总结一下，先这样 |
| 494 | heldout_neg_negation_144 | none | 我现在不需要你跑 云掩膜，只想听原理 |
| 501 | heldout_neg_concept_151 | none | 辛苦帮个忙，近红外波段 在遥感里到底意味着什么 麻烦尽快 |
| 503 | heldout_neg_non_owner_153 | none | 麻烦处理 58238e987913 的水体掩膜 谢谢啦 |
| 516 | heldout_neg_general_166 | none | 麻烦了，用 python 写个二分查找 谢谢啦 |
| 530 | heldout_neg_negation_180 | none | 在吗？想请教下，我现在不需要你跑 NDVI，只想听原理 |
| 534 | heldout_neg_general_184 | none | 嗨，那个，给我写段项目周报开头 越快越好 |
| 535 | heldout_neg_contradiction_185 | none | 对了，用 NDVI 这个算法看看 a6ebfb4c8158 里有几条船 麻烦尽快 |
| 559 | heldout_neg_contradiction_209 | none | 辛苦帮个忙，用 OCR 帮我判断 59f23ad27c53 的植被覆盖多少 |
| 569 | heldout_neg_non_owner_219 | none | 在吗？想请教下，用 0d3f1dbe7497 跑 水体掩膜，先这样 |
| 575 | heldout_neg_non_owner_225 | none | 嗨，那个，38646e49c5f7，任务是重投影，开始吧 |
| 580 | heldout_neg_missing_id_230 | none | 麻烦了，把刚说的那张图做个 水体掩膜，先这样 |
| 585 | heldout_neg_concept_235 | none | 辛苦帮个忙，想了解下 NBR 这个概念，别给我跑数据 谢谢啦 |
| 590 | heldout_neg_negation_240 | none | 在吗？想请教下，我现在不需要你跑 地物分割，只想听原理，拜托拜托 |
| 592 | heldout_neg_missing_id_242 | none | 嗨，那个，上面那景影像帮我跑 NDVI，对了我还没给你 ID |
| 595 | heldout_neg_contradiction_245 | none | 辛苦帮个忙，用水体提取工具识别 b0a0053dbe34 里的飞机，拜托拜托 |
| 596 | heldout_neg_negation_246 | none | 麻烦了，先不要执行 目标检测，说说它适合什么场景，先这样 |
| 597 | heldout_neg_concept_247 | none | 辛苦帮个忙，为什么大家都用 云阴影，优缺点呢 麻烦尽快 |
| 612 | heldout_neg_general_262 | none | 算下 3721 加 8964 等于几 麻烦尽快 |
| 640 | heldout_neg_missing_id_290 | none | 在吗？想请教下，处理一下我那张图的 水体掩膜，先这样 |
| 645 | heldout_neg_concept_295 | none | 麻烦了，科普一下 NDVI 呗 |
| 647 | heldout_neg_non_owner_297 | none | 辛苦帮个忙，麻烦处理 4afba833d60e 的地物分割，今天要 |
| 649 | heldout_neg_contradiction_299 | none | 用 NDVI 这个算法看看 91f2301e9cc6 里有几条船 麻烦尽快 |
| 658 | heldout_bnd_ocr_not_detect_008 | ocr_recognize | 在吗？想请教下，认字！7d24a1ed856a 里印的地名，不是检测车辆 麻烦尽快 |
| 673 | heldout_bnd_ocr_not_parse_023 | ocr_recognize | 对了，识别 7e5c9e5cbaa9 图面文字，我没有要传 PDF，先这样 |
| 716 | heldout_bnd_water_not_index_066 | extract_water_mask | 辛苦帮个忙，把 ebe5f61fb887 的水体边界提出来，别只给 NDWI 数值，拜托拜托 |
| 719 | heldout_bnd_detect_not_segment_069 | detect_objects | 嗨，那个，只找 bc5e110ddc18 里的船，不用整图分类 谢谢啦 |
| 720 | heldout_bnd_parse_not_ocr_070 | parse_document | 帮我梳理文档 aa6f2993-0ce0-b1ac-0005-80414f81737e 的结构，这不是扫描图识字 |
| 740 | heldout_bnd_water_not_index_090 | extract_water_mask | 嗨，那个，我要 2991c10c4871 水域的范围掩膜，不是算什么指数，拜托拜托 |
| 741 | heldout_bnd_index_not_water_091 | calculate_spectral_index | 嗨，那个，11d3530439b3 算个 NDWI 就行，别做水域提取，今天要 |
| 760 | heldout_bnd_parse_not_ocr_110 | parse_document | 辛苦帮个忙，bacd18a6-906b-5301-7bc8-548ed7285613 是个 PDF，提炼内容，不用 OCR 影像 |
| 765 | heldout_bnd_index_not_water_115 | calculate_spectral_index | 麻烦了，dbfd4d961b4e 我要的是水体指数分布，不是范围圈定，先这样 |
| 766 | heldout_bnd_segment_not_detect_116 | segment_landcover | 急用，对 1aa979dde1a2 做整图地物分割，不要目标框 越快越好 |
| 767 | heldout_bnd_detect_not_segment_117 | detect_objects | 在吗？想请教下，6ccd15cd54f6 找车，别跑分割 麻烦尽快 |
| 768 | heldout_bnd_parse_not_ocr_118 | parse_document | 在吗？想请教下，帮我梳理文档 3daa6ea3-f7b4-4b2a-7bc8-48d719aad6a2 的结构，这不是扫描图识字 越快越好 |
| 770 | heldout_bnd_ocr_not_detect_120 | ocr_recognize | 急用，f46bb3d758d5 上的文字给我读出来，不是让你找飞机 麻烦尽快 |
| 779 | heldout_bnd_detect_not_ocr_129 | detect_objects | 55da571c5005 里把船找出来，我不要图上的文字 |
| 787 | heldout_bnd_detect_not_ocr_137 | detect_objects | 框出 e0ada1526c11 中的油罐，文字识别就免了 谢谢啦 |
| 793 | heldout_bnd_ocr_not_parse_143 | ocr_recognize | 麻烦了，这景 10871db07805 的地图标注文字提取下，不是文档解析 越快越好 |
| 795 | heldout_bnd_detect_not_ocr_145 | detect_objects | 急用，0260d84c3d83 里把船找出来，我不要图上的文字，今天要 |
| 798 | heldout_bnd_segment_not_detect_148 | segment_landcover | 麻烦了，把 5d0986697152 的建筑植被水体分区，不是数飞机 谢谢啦 |
| 801 | heldout_bnd_ocr_not_parse_151 | ocr_recognize | 对了，78854731af41 上的注记认出来就行，别走文档总结，先这样 |
| 806 | heldout_bnd_segment_not_detect_156 | segment_landcover | 辛苦帮个忙，把 85c96ccc565a 的建筑植被水体分区，不是数飞机，今天要 |
| 823 | heldout_bnd_detect_not_segment_173 | detect_objects | 在吗？想请教下，只找 60a455322886 里的船，不用整图分类 麻烦尽快 |
| 828 | heldout_bnd_water_not_index_178 | extract_water_mask | bd88ccd08173 圈水域，要掩膜结果不要指数图，拜托拜托 |
| 842 | heldout_bnd_ocr_not_detect_192 | ocr_recognize | 认字！9f0c137a5b9e 里印的地名，不是检测车辆，先这样 |
| 845 | heldout_bnd_index_not_water_195 | calculate_spectral_index | 麻烦了，f92968553a1d 我要的是水体指数分布，不是范围圈定 谢谢啦 |
| 855 | heldout_cmp_web_005 | web_search | 明天去南京出差，天气怎样？再查下高铁晚点情况 谢谢啦 |
| 858 | heldout_cmp_web_008 | web_search | 在吗？想请教下，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格，先这样 |
| 878 | heldout_cmp_web_028 | web_search | 麻烦了，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格，今天要 |
| 881 | heldout_cmp_web_031 | web_search | 嗨，那个，下周末杭州天气怎么样，再帮我查下当地民宿价格行情 越快越好 |
| 890 | heldout_cmp_multi_007 | none | 辛苦帮个忙，b20bc4ab53f1 重投影完顺手把船和飞机都检测了 越快越好 |
| 892 | heldout_cmp_multi_009 | none | 一口气把 931497c3439e 的文字读出来再算个 NBR 越快越好 |
| 894 | heldout_cmp_multi_011 | none | 急用，一口气把 7cd01ac66011 的文字读出来再算个 NBR，今天要 |
| 897 | heldout_cmp_multi_014 | none | 麻烦了，0d7657f525f1 既要真彩色预览也要目标检测，一起出 越快越好 |
| 899 | heldout_cmp_multi_016 | none | 急用，先给 4379e47f66ff 去云再马上做地物分割，先这样 |
| 913 | heldout_cmp_multi_030 | none | 在吗？想请教下，6d282085e3e4 重投影完顺手把船和飞机都检测了 谢谢啦 |
| 938 | heldout_cmp_multi_055 | none | 嗨，那个，56914ed334e2 先查元数据，接着直接分割，一条龙，先这样 |
| 943 | heldout_cmp_multi_060 | none | 辛苦帮个忙，71b9afb535a4 先查元数据，接着直接分割，一条龙 谢谢啦 |
| 953 | heldout_noise_dirty_003 | calculate_ndvi | 麻烦了，给 727b6f3f9674 算下植被指数 NDVI，看看绿化情况 嗯嗯嗯嗯嗯嗯嗯嗯 |
| 960 | heldout_noise_dirty_010 | detect_objects | 麻烦了，数一数 f22219a8d1bd 里有多少车 嗯嗯嗯嗯嗯嗯 |
| 970 | heldout_noise_dirty_020 | raster_inspect | 对了 帮我确认 20b9665099cc 的投影和覆盖范围对不对 拜托拜托 |
| 979 | heldout_noise_badid_004 | segment_landcover | 嗨，那个，对 41f42458 做地物分割，应该是这个 ID 吧，今天要 |
| 981 | heldout_noise_badid_006 | calculate_ndvi | 在吗？想请教下，3927d4 做个NDVI，记错了的话你帮我看下清单，先这样 |
| 987 | heldout_noise_badid_012 | calculate_ndvi | 急用，好像是 0ad027？给它做NDVI，先这样 |

## 人工结论

- [ ] 抽检通过，冻结生效
- [ ] 发现错标（列出 case_id，废弃数据集换 seed 重生成）
