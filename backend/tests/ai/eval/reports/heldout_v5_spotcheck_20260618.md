# heldout-v5 人工抽检报告（分层抽样，每 category 12.5%）

- dataset_hash: `ea263b50a8e732e519a8f1d717fc5b8c3f20e94a803637f35b7400af98f4842d`
- seed: 20260618  case_count: 1000  sampled: 126
- 抽样：按 category 分层、seed 确定性随机，每子类至少 1 条——任何子类都不会成为盲区。
- 检查点：①表达无歧义 ②场景合理 ③label 与场景一致。
- 纪律：发现错标不许单条改题；整体废弃本数据集（删除冻结目录——它尚未运行），换新 seed 重新生成冻结。

| # | case_id | expected | query |
| --- | --- | --- | --- |
| 10 | heldout_pos_generate_report_010 | generate_report | 急用，把前面跑出来的结果整理成一份分析报告给我 麻烦尽快 |
| 16 | heldout_pos_generate_report_016 | generate_report | 急用，帮我把刚才的分析写成报告文档，先这样 |
| 19 | heldout_pos_detect_objects_019 | detect_objects | 麻烦了，扫一下 593c7a9cec66 看看桥在哪，拜托拜托 |
| 26 | heldout_pos_calculate_spectral_index_026 | calculate_spectral_index | 对了，对 217334a592ee 来个 火烧迹地指数 NBR 的结果 麻烦尽快 |
| 47 | heldout_pos_web_search_047 | web_search | 对了，搜下最新的 Landsat 数据下载渠道变化 麻烦尽快 |
| 49 | heldout_pos_calculate_ndvi_049 | calculate_ndvi | 麻烦了，cf36210105a2 的 ndvi 跑一下呗，急等，先这样 |
| 51 | heldout_pos_render_band_composite_051 | render_band_composite | 嗨，那个，假彩色合成图来一张，用 390d5936a575 麻烦尽快 |
| 52 | heldout_pos_cloud_shadow_mask_052 | cloud_shadow_mask | 嗨，那个，给 663142b6dc38 跑一遍云阴影检测，拜托拜托 |
| 58 | heldout_pos_parse_document_058 | parse_document | 辛苦帮个忙，总结一下文档 03e25f65-707f-ced8-b9b9-a72fada2864c 讲了什么，拜托拜托 |
| 79 | heldout_pos_detect_objects_079 | detect_objects | 在吗？想请教下，检出 d1b6ac561e92 中所有车的位置 麻烦尽快 |
| 89 | heldout_pos_extract_water_mask_089 | extract_water_mask | 把 c6f266a05197 的河湖水域提取一下，拜托拜托 |
| 93 | heldout_pos_ocr_recognize_093 | ocr_recognize | 嗨，那个，6ef8d2afbc21 这张扫描图上的字帮我读出来 谢谢啦 |
| 94 | heldout_pos_parse_document_094 | parse_document | 在吗？想请教下，总结一下文档 cbc12e1b-9476-2908-3278-3f61ad4b1652 讲了什么 麻烦尽快 |
| 95 | heldout_pos_web_search_095 | web_search | 嗨，那个，帮我查今天北京的空气质量指数，今天要 |
| 105 | heldout_pos_ocr_recognize_105 | ocr_recognize | 在吗？想请教下，认一下 2a67c7a29a44 上面标注的地名文字 |
| 113 | heldout_pos_extract_water_mask_113 | extract_water_mask | 急用，84a665afb658 哪里是水，出个水体掩模 谢谢啦 |
| 138 | heldout_pos_clip_reproject_raster_138 | clip_reproject_raster | 辛苦帮个忙，重投影：3065aad40f44 转 EPSG:32649，谢谢 谢谢啦 |
| 144 | heldout_pos_raster_inspect_144 | raster_inspect | 在吗？想请教下，我想先摸清 0114f0156e7a 的底细，分辨率、范围、坐标系都报一下 谢谢啦 |
| 150 | heldout_pos_clip_reproject_raster_150 | clip_reproject_raster | 辛苦帮个忙，295835030dc3 转成 EPSG:32650 的投影 麻烦尽快 |
| 152 | heldout_pos_segment_landcover_152 | segment_landcover | 把 dd6f916207f3 按地类切成一块块的 麻烦尽快 |
| 155 | heldout_pos_web_search_155 | web_search | 辛苦帮个忙，下周成都的天气趋势帮我查下 麻烦尽快 |
| 170 | heldout_pos_calculate_spectral_index_170 | calculate_spectral_index | 对了，56d977f578dc 需要做 水体指数 NDWI 分析 |
| 188 | heldout_pos_segment_landcover_188 | segment_landcover | 对了，把 efa369b3104e 按地类切成一块块的 |
| 190 | heldout_pos_parse_document_190 | parse_document | 麻烦了，文档 296c1659-a528-04a8-03cb-943358245474 的核心内容提炼出来，今天要 |
| 191 | heldout_pos_web_search_191 | web_search | 这两天哪里有台风预警，查一下，拜托拜托 |
| 192 | heldout_pos_raster_inspect_192 | raster_inspect | 辛苦帮个忙，帮我确认 dbcff7aec61f 的投影和覆盖范围对不对 越快越好 |
| 199 | heldout_pos_detect_objects_199 | detect_objects | 急用，66c6cc09ef95 里有没有飞机，帮我框出来 越快越好 |
| 200 | heldout_pos_segment_landcover_200 | segment_landcover | 嗨，那个，7863a509d8d9 的地表覆盖类型图做一份 |
| 201 | heldout_pos_ocr_recognize_201 | ocr_recognize | 麻烦了，b066e31eff36 上写了什么字？OCR 一下，拜托拜托 |
| 217 | heldout_pos_calculate_ndvi_217 | calculate_ndvi | 急用，麻烦对 f082c4e6b3c1 执行 NDVI 计算 谢谢啦 |
| 222 | heldout_pos_clip_reproject_raster_222 | clip_reproject_raster | 在吗？想请教下，重投影：a58e17dfc7a1 转 EPSG:3857，谢谢，先这样 |
| 224 | heldout_pos_segment_landcover_224 | segment_landcover | 给 4ac01ce9d886 跑语义分割，分地物类型，拜托拜托 |
| 276 | heldout_pos_raster_inspect_276 | raster_inspect | 嗨，那个，这景 c5646d9d0ba6 到底几个波段、什么投影，给我看下基本信息 越快越好 |
| 278 | heldout_pos_calculate_spectral_index_278 | calculate_spectral_index | 麻烦了，算 建筑指数 NDBI 吧，影象是 4f0f3bbc767b，今天要 |
| 279 | heldout_pos_render_band_composite_279 | render_band_composite | 对了，把 656bafd295da 弄成真彩色图我瞅瞅，先这样 |
| 285 | heldout_pos_ocr_recognize_285 | ocr_recognize | 麻烦了，读取 1771d11ec891 中的文字标注信息，今天要 |
| 289 | heldout_pos_calculate_ndvi_289 | calculate_ndvi | 在吗？想请教下，给 ff420adf708a 算下植被指数 NDVI，看看绿化情况 谢谢啦 |
| 300 | heldout_pos_raster_inspect_300 | raster_inspect | 急用，这景 cc9d9d8e33e6 到底几个波段、什么投影，给我看下基本信息 |
| 301 | heldout_pos_calculate_ndvi_301 | calculate_ndvi | 辛苦帮个忙，评估下 61755e6eff0f 的植被覆盖，用 NDVI 就行，今天要 |
| 315 | heldout_pos_render_band_composite_315 | render_band_composite | 给 ce3caa08efc3 做假彩色显示 越快越好 |
| 319 | heldout_pos_detect_objects_319 | detect_objects | 对了，扫一下 b4f26534b7e7 看看车在哪，先这样 |
| 328 | heldout_pos_cloud_shadow_mask_328 | cloud_shadow_mask | 嗨，那个，想确认 f88387b9a810 是不是被云挡了，做个掩膜 麻烦尽快 |
| 329 | heldout_pos_extract_water_mask_329 | extract_water_mask | 麻烦了，db8a4737b7a0 做水体提取，掩膜给我 |
| 330 | heldout_pos_clip_reproject_raster_330 | clip_reproject_raster | 在吗？想请教下，需要把 97f38824a153 的坐标系改成 EPSG:4326 麻烦尽快 |
| 340 | heldout_pos_cloud_shadow_mask_340 | cloud_shadow_mask | 嗨，那个，对 779a96fe2b3c 做去云前的云检测，拜托拜托 |
| 346 | heldout_pos_parse_document_346 | parse_document | 嗨，那个，帮我读文档 a6ff2461-4b15-a1cb-63cc-1384d02f5a5c，给个摘要 越快越好 |
| 352 | heldout_neg_report_no_analysis_002 | none | 辛苦帮个忙，生成一份分析报告给我下载 谢谢啦 |
| 361 | heldout_neg_report_no_analysis_011 | none | 辛苦帮个忙，帮我写一份遥感报告，内容你看着来 谢谢啦 |
| 365 | heldout_neg_non_owner_015 | none | 在吗？想请教下，8d4a34487056，任务是重投影，开始吧 麻烦尽快 |
| 368 | heldout_neg_negation_018 | none | 辛苦帮个忙，我现在不需要你跑 地物分割，只想听原理，先这样 |
| 381 | heldout_neg_concept_031 | none | 急用，想了解下 假彩色 这个概念，别给我跑数据，先这样 |
| 388 | heldout_neg_missing_id_038 | none | 急用，处理一下我那张图的 云检测，今天要 |
| 412 | heldout_neg_missing_id_062 | none | 麻烦了，上面那景影像帮我跑 地物分割，对了我还没给你 ID 越快越好 |
| 418 | heldout_neg_missing_id_068 | none | 在吗？想请教下，对刚才传的那个直接做 地物分割，先这样 |
| 430 | heldout_neg_missing_id_080 | segment_landcover | 对了，那张图的 地物分割 安排一下，拜托拜托 |
| 432 | heldout_neg_general_082 | none | 嗨，那个，帮我润色一段答辩稿 |
| 435 | heldout_neg_concept_085 | none | 急用，想了解下 云阴影 这个概念，别给我跑数据 |
| 445 | heldout_neg_contradiction_095 | none | 在吗？想请教下，拿波段合成功能翻译文档 24e9c91c-6ff9-089f-38f3-79555e1efa72，先这样 |
| 446 | heldout_neg_negation_096 | none | 辛苦帮个忙，不用调用什么工具，NDVI 的思路给我讲讲 谢谢啦 |
| 477 | heldout_neg_concept_127 | none | 在吗？想请教下，科普一下 云阴影 呗 越快越好 |
| 485 | heldout_neg_non_owner_135 | none | 嗨，那个，用 5be2873b189e 跑 云检测 麻烦尽快 |
| 493 | heldout_neg_contradiction_143 | none | 在吗？想请教下，用 NDVI 这个算法看看 7fcadec60889 里有几条船 越快越好 |
| 497 | heldout_neg_non_owner_147 | none | 嗨，那个，麻烦处理 47b4a7768295 的云检测 |
| 499 | heldout_neg_contradiction_149 | none | 辛苦帮个忙，用 NDVI 这个算法看看 47bed19fda81 里有几条船 越快越好 |
| 502 | heldout_neg_missing_id_152 | calculate_ndvi | 辛苦帮个忙，就这张图，跑 NDVI |
| 517 | heldout_neg_contradiction_167 | none | 辛苦帮个忙，拿云掩膜工具把文档 5fb5fb3f-a912-ac0b-30b0-b5648878b16e 总结一下 麻烦尽快 |
| 536 | heldout_neg_negation_186 | none | 嗨，那个，我现在不需要你跑 地物分割，只想听原理 麻烦尽快 |
| 548 | heldout_neg_negation_198 | none | 急用，先别动手算，就跟我讲讲 目标检测 是怎么回事 谢谢啦 |
| 552 | heldout_neg_general_202 | none | 嗨，那个，给我写段项目周报开头 |
| 555 | heldout_neg_concept_205 | none | 辛苦帮个忙，为什么大家都用 假彩色，优缺点呢 麻烦尽快 |
| 558 | heldout_neg_general_208 | none | 麻烦了，把 land cover 翻译成中文，拜托拜托 |
| 572 | heldout_neg_negation_222 | none | 在吗？想请教下，不用调用什么工具，目标检测 的思路给我讲讲 越快越好 |
| 573 | heldout_neg_concept_223 | none | 嗨，那个，NBR 的取值范围一般是多少，怎么解读 麻烦尽快 |
| 588 | heldout_neg_general_238 | none | 对了，Excel 怎么做数据透视表 谢谢啦 |
| 599 | heldout_neg_non_owner_249 | none | 在吗？想请教下，麻烦处理 8707f54993f5 的NDVI，今天要 |
| 607 | heldout_neg_contradiction_257 | none | 嗨，那个，靠重投影功能数一数 22e018e7e348 里的车 麻烦尽快 |
| 617 | heldout_neg_non_owner_267 | none | 急用，影像 650f17603b59 帮我算个 重投影，今天要 |
| 620 | heldout_neg_negation_270 | none | 我现在不需要你跑 云掩膜，只想听原理 |
| 625 | heldout_neg_contradiction_275 | none | 拿云掩膜工具把文档 913844ec-fcca-1c3f-cb92-21fcf53bc74d 总结一下，拜托拜托 |
| 636 | heldout_neg_general_286 | none | 麻烦了，讲讲什么是过拟合 |
| 640 | heldout_neg_missing_id_290 | none | 在吗？想请教下，处理一下我那张图的 水体掩膜，先这样 |
| 641 | heldout_neg_non_owner_291 | none | 在吗？想请教下，影像 ab41ff065bc0 帮我算个 NDVI，拜托拜托 |
| 642 | heldout_neg_general_292 | none | 对了，把 land cover 翻译成中文 越快越好 |
| 645 | heldout_neg_concept_295 | none | 麻烦了，假彩色 的取值范围一般是多少，怎么解读，先这样 |
| 672 | heldout_bnd_parse_not_ocr_022 | parse_document | 文档 8fdc019a-6c8c-c318-3c4d-54659c26dd05 给我总结要点，不是图片认字，先这样 |
| 679 | heldout_bnd_detect_not_segment_029 | detect_objects | 嗨，那个，定位 fe21e8deaa9e 中的飞机，不需要 landcover 麻烦尽快 |
| 681 | heldout_bnd_ocr_not_parse_031 | ocr_recognize | 嗨，那个，dd285ef572c9 是张扫描地图，读上面的字，不是解析什么文档 越快越好 |
| 684 | heldout_bnd_water_not_index_034 | extract_water_mask | 嗨，那个，b63e677680d2 圈水域，要掩膜结果不要指数图，拜托拜托 |
| 692 | heldout_bnd_water_not_index_042 | extract_water_mask | 对了，705e57d31602 圈水域，要掩膜结果不要指数图 麻烦尽快 |
| 696 | heldout_bnd_parse_not_ocr_046 | parse_document | 麻烦了，552e37c0-e3cf-610f-20ae-ee5a2397799a 文档解析走起，要章节摘要，先这样 |
| 701 | heldout_bnd_index_not_water_051 | calculate_spectral_index | 麻烦了，40ac88ca3060 算个 NDWI 就行，别做水域提取，拜托拜托 |
| 708 | heldout_bnd_water_not_index_058 | extract_water_mask | 麻烦了，提取 2c346e6c65c8 实际的水面分布，不是指数计祘 越快越好 |
| 735 | heldout_bnd_detect_not_segment_085 | detect_objects | 定位 86b7e552e15c 中的飞机，不需要 landcover 越快越好 |
| 739 | heldout_bnd_detect_not_ocr_089 | detect_objects | 在吗？想请教下，efa743098835 找目标：车辆，别给我做 OCR 麻烦尽快 |
| 745 | heldout_bnd_ocr_not_parse_095 | ocr_recognize | 嗨，那个，bf1b43c3056a 上的注记认出来就行，别走文档总结，先这样 |
| 746 | heldout_bnd_ocr_not_detect_096 | ocr_recognize | 在吗？想请教下，32d26f7af314 上的文字给我读出来，不是让你找飞机 越快越好 |
| 787 | heldout_bnd_detect_not_ocr_137 | detect_objects | 对了，bff14f5ef694 里把船找出来，我不要图上的文字，先这样 |
| 794 | heldout_bnd_ocr_not_detect_144 | ocr_recognize | 嗨，那个，我要 f63f2b224220 的图面注记内容，别做目标检侧，拜托拜托 |
| 797 | heldout_bnd_index_not_water_147 | calculate_spectral_index | 麻烦了，只要 363277e6b69f 的 NDWI 指数，不用提取水体矢量 麻烦尽快 |
| 798 | heldout_bnd_segment_not_detect_148 | segment_landcover | 对了，把 31bda6e88373 的建筑植被水体分区，不是数飞机 麻烦尽快 |
| 800 | heldout_bnd_parse_not_ocr_150 | parse_document | 对了，文档 880476c9-94e2-0e01-24f8-c1322de6dcf4 给我总结要点，不是图片认字 谢谢啦 |
| 806 | heldout_bnd_segment_not_detect_156 | segment_landcover | 急用，74c82070e650 整幅按地类分块，不是找单个目标 |
| 813 | heldout_bnd_index_not_water_163 | calculate_spectral_index | 嗨，那个，0e76093150de 算个 NDWI 就行，别做水域提取，先这样 |
| 826 | heldout_bnd_ocr_not_detect_176 | ocr_recognize | 28edf0e44dae 这图我只关心上面写了啥字，目标别管 谢谢啦 |
| 827 | heldout_bnd_detect_not_ocr_177 | detect_objects | 在吗？想请教下，5e6c47601b81 找目标：车辆，别给我做 OCR，先这样 |
| 830 | heldout_bnd_segment_not_detect_180 | segment_landcover | 急用，777c509216c6 我要地表分类图，别给我检测结果 越快越好 |
| 833 | heldout_bnd_ocr_not_parse_183 | ocr_recognize | 麻烦了，dc3b51a8b6a7 上的注记认出来就行，别走文档总结 谢谢啦 |
| 847 | heldout_bnd_detect_not_segment_197 | detect_objects | 嗨，那个，只找 b72b5f6b1d17 里的船，不用整图分类 谢谢啦 |
| 856 | heldout_cmp_web_006 | web_search | 急用，看下这周末上海限行规定，以及天气适不适合外拍，今天要 |
| 869 | heldout_cmp_web_019 | web_search | 辛苦帮个忙，帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接，今天要 |
| 871 | heldout_cmp_web_021 | web_search | 急用，帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接，先这样 |
| 873 | heldout_cmp_web_023 | web_search | 在吗？想请教下，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格，今天要 |
| 897 | heldout_cmp_multi_014 | none | 嗨，那个，把 6b46b2545fc5 的云掩膜和水体掩膜一次性都做了，拜托拜托 |
| 901 | heldout_cmp_multi_018 | none | 嗨，那个，一口气把 ce4ea7cd6121 的文字读出来再算个 NBR |
| 907 | heldout_cmp_multi_024 | none | 对了，a71f604017e0 既要真彩色预览也要目标检测，一起出 |
| 909 | heldout_cmp_multi_026 | none | 6c0f55b335b7 先查元数据，接着直接分割，一条龙，拜托拜托 |
| 913 | heldout_cmp_multi_030 | none | 在吗？想请教下，把 ee26ce8f45a8 的云掩膜和水体掩膜一次性都做了 麻烦尽快 |
| 917 | heldout_cmp_multi_034 | none | 急用，一口气把 e2711fcebc12 的文字读出来再算个 NBR，今天要 |
| 925 | heldout_cmp_multi_042 | none | 在吗？想请教下，先给 ac34eb9d193e 去云再马上做地物分割，今天要 |
| 949 | heldout_cmp_multi_066 | none | 麻烦了，9a470a1e5f3e 重投影完顺手把船和飞机都检测了，先这样 |
| 954 | heldout_noise_dirty_004 | detect_objects | 嗨 那个 805acfc65daf 目标排查：重点是飞机 越快越好 嗯嗯嗯嗯嗯嗯嗯 |
| 955 | heldout_noise_dirty_005 | raster_inspect | 急用，上传的 0028fb1966f1 是多少波段的？顺便看下 CRS，拜托拜托 |
| 971 | heldout_noise_dirty_021 | calculate_ndvi | 麻烦了 给 a9e9d0ddfa81 算下植被指数 NDVI 看看绿化情况 麻烦尽快 |
| 982 | heldout_noise_badid_007 | cloud_shadow_mask | 嗨，那个，4718c4ef 做个云检测，记错了的话你帮我看下清单 |
| 992 | heldout_noise_badid_017 | segment_landcover | 辛苦帮个忙，0d753a22 做个地物分割，记错了的话你帮我看下清单，今天要 |
| 999 | heldout_noise_badid_024 | cloud_shadow_mask | 辛苦帮个忙，对 5180fac1 做云检测，应该是这个 ID 吧，拜托拜托 |

## 人工结论

- [ ] 抽检通过，冻结生效
- [ ] 发现错标（列出 case_id，废弃数据集换 seed 重生成）
