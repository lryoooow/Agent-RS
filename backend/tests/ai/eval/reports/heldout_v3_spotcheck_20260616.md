# heldout-v3 人工抽检报告（分层抽样，每 category 12.5%）

- dataset_hash: `04f171f9bf1f7c7337bcdb3dc25e5e700e4224ec08c1f921db90a9135342b28f`
- seed: 20260616  case_count: 1000  sampled: 126
- 抽样：按 category 分层、seed 确定性随机，每子类至少 1 条——任何子类都不会成为盲区。
- 检查点：①表达无歧义 ②场景合理 ③label 与场景一致。
- 纪律：发现错标不许单条改题；整体废弃本数据集（删除冻结目录——它尚未运行），换新 seed 重新生成冻结。

| # | case_id | expected | query |
| --- | --- | --- | --- |
| 2 | heldout_pos_calculate_spectral_index_002 | calculate_spectral_index | 对了，帮我把 6ef335cdace1 的 土壤调节植被 SAVI 跑出来 谢谢啦 |
| 37 | heldout_pos_calculate_ndvi_037 | calculate_ndvi | 麻烦了，我要 0ba57276103a 的 NDVI 结果图 麻烦尽快 |
| 39 | heldout_pos_render_band_composite_039 | render_band_composite | 对了，acacd7a3e704 渲染成真彩色发我 |
| 43 | heldout_pos_detect_objects_043 | detect_objects | 急用，5dab8800fec6 里有没有油罐，帮我框出来 越快越好 |
| 45 | heldout_pos_ocr_recognize_045 | ocr_recognize | 嗨，那个，读取 034b9abfe2ba 中的文字标注信息 麻烦尽快 |
| 54 | heldout_pos_clip_reproject_raster_054 | clip_reproject_raster | b89a7b1d417f 现在的投影不对，统一到 EPSG:4326 |
| 56 | heldout_pos_segment_landcover_056 | segment_landcover | 在吗？想请教下，对 432de9521a52 做土地覆盖分区 越快越好 |
| 63 | heldout_pos_render_band_composite_063 | render_band_composite | 嗨，那个，用真彩色方案把 2f6e7641853c 显示出来 |
| 77 | heldout_pos_extract_water_mask_077 | extract_water_mask | 麻烦了，圈一下 413b952ff579 里的湖泊河流范围 越快越好 |
| 80 | heldout_pos_segment_landcover_080 | segment_landcover | 在吗？想请教下，3dcb0b5c51b8 整景做地物分类分割，先这样 |
| 84 | heldout_pos_raster_inspect_084 | raster_inspect | 麻烦了，f9e7d79f71c6 这景图的基本属性查一下，宽高波段那些 越快越好 |
| 88 | heldout_pos_cloud_shadow_mask_088 | cloud_shadow_mask | 麻烦了，对 f89c365dbcc9 做去云前的云检测 谢谢啦 |
| 93 | heldout_pos_ocr_recognize_093 | ocr_recognize | 在吗？想请教下，973d26c4d006 里印的文字内容提取一下，今天要 |
| 111 | heldout_pos_render_band_composite_111 | render_band_composite | 嗨，那个，给 d97d3c94b8f3 做假彩色显示，拜托拜托 |
| 115 | heldout_pos_detect_objects_115 | detect_objects | 急用，帮我定位 3a0af1810d07 中的车 |
| 117 | heldout_pos_ocr_recognize_117 | ocr_recognize | 对了，6d5ed14f94da 上写了什么字？OCR 一下 谢谢啦 |
| 127 | heldout_pos_detect_objects_127 | detect_objects | 在吗？想请教下，f51b68dd7aa7 目标排查：重点是桥 麻烦尽快 |
| 133 | heldout_pos_calculate_ndvi_133 | calculate_ndvi | cd4df1bf6baa 的 ndvi 跑一下呗，急等，先这样 |
| 134 | heldout_pos_calculate_spectral_index_134 | calculate_spectral_index | 对了，帮我把 6cb6ff42b0c5 的 水分指数 NDMI 跑出来 |
| 136 | heldout_pos_cloud_shadow_mask_136 | cloud_shadow_mask | 给 4688a81d66f3 跑一遍云阴影检测，先这样 |
| 157 | heldout_pos_calculate_ndvi_157 | calculate_ndvi | 嗨，那个，麻烦对 1bf2e12f8d6d 执行 NDVI 计祘 越快越好 |
| 162 | heldout_pos_clip_reproject_raster_162 | clip_reproject_raster | 在吗？想请教下，需要把 91c3e70dba0d 的坐标系改成 EPSG:32649，今天要 |
| 179 | heldout_pos_web_search_179 | web_search | 麻烦了，帮我查今天北京的空气质量指数，今天要 |
| 180 | heldout_pos_raster_inspect_180 | raster_inspect | 辛苦帮个忙，这景 a5194d5995be 到底几个波段、什么投影，给我看下基本信息 |
| 182 | heldout_pos_calculate_spectral_index_182 | calculate_spectral_index | 辛苦帮个忙，算 水分指数 NDMI 吧，影象是 89b25f744c8e，今天要 |
| 186 | heldout_pos_clip_reproject_raster_186 | clip_reproject_raster | 在吗？想请教下，把 7103225b95f4 重投到 EPSG:4326 谢谢啦 |
| 191 | heldout_pos_web_search_191 | web_search | 急用，下周成都的天气趋势帮我查下，拜托拜托 |
| 193 | heldout_pos_calculate_ndvi_193 | calculate_ndvi | 在吗？想请教下，我要 5ce0f4b980a2 的 NDVI 结果图，先这样 |
| 203 | heldout_pos_web_search_203 | web_search | 麻烦了，最近高分卫星影像的官方采购价格是多少 越快越好 |
| 204 | heldout_pos_raster_inspect_204 | raster_inspect | 嗨，那个，e53fefb9668f 这景图的基本属性查一下，宽高波段那些 谢谢啦 |
| 206 | heldout_pos_calculate_spectral_index_206 | calculate_spectral_index | ea3e359f7041 需要做 建筑指数 NDBI 分析 越快越好 |
| 209 | heldout_pos_extract_water_mask_209 | extract_water_mask | 急用，我要 a7bf2ab95ecf 的水域边界图层，今天要 |
| 210 | heldout_pos_clip_reproject_raster_210 | clip_reproject_raster | 辛苦帮个忙，对 30c91f25a0dc 做投影转换，目标 EPSG:32650，今天要 |
| 214 | heldout_pos_parse_document_214 | parse_document | 辛苦帮个忙，总结一下文档 01d72d75-9540-249f-d88c-9664002deeab 讲了什么 谢谢啦 |
| 221 | heldout_pos_extract_water_mask_221 | extract_water_mask | 对了，我要 1373ff1b0b6e 的水域边界图层 谢谢啦 |
| 223 | heldout_pos_detect_objects_223 | detect_objects | 辛苦帮个忙，640b7b454075 里有没有桥，帮我框出来 麻烦尽快 |
| 227 | heldout_pos_web_search_227 | web_search | 对了，后天广州会不会下暴雨，出门要不要带伞 麻烦尽快 |
| 228 | heldout_pos_raster_inspect_228 | raster_inspect | 在吗？想请教下，查询影像 534a874a0ea8 的 profile 信息 越快越好 |
| 249 | heldout_pos_ocr_recognize_249 | ocr_recognize | 麻烦了，a7380d49d0ce 这张扫描图上的字帮我读出来，先这样 |
| 250 | heldout_pos_parse_document_250 | parse_document | 对了，我传的那份文档 1f5d4f7f-b5ba-2888-0efa-3fa785fabdcc，帮我把要点捋一捋，拜托拜托 |
| 267 | heldout_pos_render_band_composite_267 | render_band_composite | 对了，用真彩色方案把 8e0cd1eaf13e 显示出来，今天要 |
| 268 | heldout_pos_cloud_shadow_mask_268 | cloud_shadow_mask | 辛苦帮个忙，b6d7caea2f2d 需要云和云影的质检掩膜 谢谢啦 |
| 272 | heldout_pos_segment_landcover_272 | segment_landcover | 对了，我要 bfec1b3ae85f 的 landcover 分割结果，拜托拜托 |
| 292 | heldout_pos_cloud_shadow_mask_292 | cloud_shadow_mask | 辛苦帮个忙，想确认 70e5e775973e 是不是被云挡了，做个掩膜 谢谢啦 |
| 310 | heldout_pos_parse_document_310 | parse_document | 辛苦帮个忙，我传的那份文档 f93dae7b-60c1-45c2-b8cc-2f39dd4ba026，帮我把要点捋一捋，拜托拜托 |
| 329 | heldout_pos_extract_water_mask_329 | extract_water_mask | 急用，我要 4b57c81e1b73 的水域边界图层 谢谢啦 |
| 334 | heldout_pos_parse_document_334 | parse_document | 急用，cc18fa8b-19d0-3c38-3b08-45bd8eeeea9d 内容整理成几条要点，先这样 |
| 344 | heldout_pos_segment_landcover_344 | segment_landcover | 辛苦帮个忙，ba6ec3acc187 给我分一下地表类别，哪块是建筑哪块是植被 越快越好 |
| 350 | heldout_neg_negation_000 | none | 嗨，那个，停，NDVI 这步先不做，原理是什么 麻烦尽快 |
| 352 | heldout_neg_missing_id_002 | none | 对了，把刚说的那张图做个 地物分割，今天要 |
| 363 | heldout_neg_concept_013 | none | 辛苦帮个忙，云阴影 在遥感里到底意味着什么，今天要 |
| 371 | heldout_neg_non_owner_021 | none | 麻烦处理 62802c628dcc 的水体掩膜 麻烦尽快 |
| 377 | heldout_neg_non_owner_027 | none | 辛苦帮个忙，用 f75aab6d9fdf 跑 重投影 麻烦尽快 |
| 378 | heldout_neg_general_028 | none | 辛苦帮个忙，把 land cover 翻译成中文 越快越好 |
| 395 | heldout_neg_non_owner_045 | none | 急用，87673f28bf56 这景做一下 云检测，今天要 |
| 399 | heldout_neg_concept_049 | none | 嗨，那个，为什么大家都用 近红外波段，优缺点呢，拜托拜托 |
| 409 | heldout_neg_contradiction_059 | none | 辛苦帮个忙，靠重投影功能数一数 36647164b0fc 里的车 麻烦尽快 |
| 412 | heldout_neg_missing_id_062 | none | 对了，把刚说的那张图做个 地物分割，先这样 |
| 414 | heldout_neg_general_064 | none | 嗨，那个，帮我润色一段答辩稿 麻烦尽快 |
| 416 | heldout_neg_negation_066 | none | 急用，停，水体提取 这步先不做，原理是什么 麻烦尽快 |
| 423 | heldout_neg_concept_073 | none | 嗨，那个，想了解下 近红外波段 这个概念，别给我跑数据 越快越好 |
| 428 | heldout_neg_negation_078 | none | 我现在不需要你跑 目标检测，只想听原理 谢谢啦 |
| 437 | heldout_neg_non_owner_087 | none | 对了，00da6ab9e70b 这景做一下 NDVI，拜托拜托 |
| 458 | heldout_neg_negation_108 | none | 辛苦帮个忙，先不要执行 地物分割，说说它适合什么场景 谢谢啦 |
| 463 | heldout_neg_contradiction_113 | none | 辛苦帮个忙，用水体提取工具识别 a386fe1d95d2 里的飞机，拜托拜托 |
| 479 | heldout_neg_non_owner_129 | none | 在吗？想请教下，影像 01e4e8debf83 帮我算个 云检测 麻烦尽快 |
| 482 | heldout_neg_negation_132 | none | 辛苦帮个忙，不用调用什么工具，云掩膜 的思路给我讲讲 |
| 495 | heldout_neg_concept_145 | none | 麻烦了，想了解下 NBR 这个概念，别给我跑数据 |
| 504 | heldout_neg_general_154 | none | 辛苦帮个忙，帮我润色一段答辩稿 麻烦尽快 |
| 505 | heldout_neg_contradiction_155 | none | 嗨，那个，用 NDVI 这个算法看看 45d51381055d 里有几条船，拜托拜托 |
| 508 | heldout_neg_missing_id_158 | none | 嗨，那个，上面那景影像帮我跑 水体掩膜，对了我还没给你 ID |
| 522 | heldout_neg_general_172 | none | 麻烦了，把 land cover 翻译成中文 |
| 525 | heldout_neg_concept_175 | none | 辛苦帮个忙，NDVI 的取值范围一般是多少，怎么解读 谢谢啦 |
| 535 | heldout_neg_contradiction_185 | none | 嗨，那个，用 OCR 帮我判断 9eba01906d01 的植被覆盖多少 |
| 561 | heldout_neg_concept_211 | none | 辛苦帮个忙，想了解下 假彩色 这个概念，别给我跑数据 谢谢啦 |
| 563 | heldout_neg_non_owner_213 | none | 对了，用 992ff6929386 跑 地物分割，今天要 |
| 564 | heldout_neg_general_214 | none | 辛苦帮个忙，讲讲什么是过拟合 |
| 594 | heldout_neg_general_244 | none | 麻烦了，讲讲什么是过拟合 |
| 595 | heldout_neg_contradiction_245 | none | 急用，拿云掩膜工具把文档 a7e93f5a-5411-b69c-ea89-638f5db84c38 总结一下，拜托拜托 |
| 598 | heldout_neg_missing_id_248 | calculate_ndvi | 就这张图，跑 NDVI |
| 610 | heldout_neg_missing_id_260 | none | 嗨，那个，对刚才传的那个直接做 云检测，拜托拜托 |
| 626 | heldout_neg_negation_276 | none | 急用，停，目标检测 这步先不做，原理是什么 |
| 637 | heldout_neg_contradiction_287 | none | 嗨，那个，用 OCR 帮我判断 8c402e8e30ce 的植被覆盖多少 麻烦尽快 |
| 646 | heldout_neg_missing_id_296 | extract_water_mask | 就这张图，跑 水体掩膜 越快越好 |
| 651 | heldout_bnd_detect_not_ocr_001 | detect_objects | 41b1fc1a4332 里把船找出来，我不要图上的文字 麻烦尽快 |
| 665 | heldout_bnd_ocr_not_parse_015 | ocr_recognize | 在吗？想请教下，这景 a40f0aff74b8 的地图标注文字提取下，不是文档解析，拜托拜托 |
| 667 | heldout_bnd_detect_not_ocr_017 | detect_objects | 对了，框出 e212e53190a0 中的油罐，文字识别就免了，拜托拜托 |
| 668 | heldout_bnd_water_not_index_018 | extract_water_mask | 在吗？想请教下，我要 9ac6eb156591 水域的范围掩模，不是算什么指数，先这样 |
| 669 | heldout_bnd_index_not_water_019 | calculate_spectral_index | 在吗？想请教下，给 e3c67db9d880 出 NDWI 指数图，水体掩膜不需要，拜托拜托 |
| 676 | heldout_bnd_water_not_index_026 | extract_water_mask | 嗨，那个，我要 5fbdf4bedc01 水域的范围掩膜，不是算什么指数，今天要 |
| 682 | heldout_bnd_ocr_not_detect_032 | ocr_recognize | 麻烦了，认字！e5a491da1b2e 里印的地名，不是检测车辆 麻烦尽快 |
| 685 | heldout_bnd_index_not_water_035 | calculate_spectral_index | 麻烦了，给 4a086ef24026 出 NDWI 指数图，水体掩模不需要 越快越好 |
| 695 | heldout_bnd_detect_not_segment_045 | detect_objects | 嗨，那个，eaf599edbb5b 检侧桥梁就好，地物分割先不做，先这样 |
| 699 | heldout_bnd_detect_not_ocr_049 | detect_objects | 辛苦帮个忙，框出 b0e557a643ad 中的油罐，文字识别就免了 麻烦尽快 |
| 703 | heldout_bnd_detect_not_segment_053 | detect_objects | 6b776e606286 检测桥梁就好，地物分割先不做，今天要 |
| 712 | heldout_bnd_parse_not_ocr_062 | parse_document | 在吗？想请教下，ae5ff149-339e-20b9-47d4-fed89ff91aa7 文档解析走起，要章节摘要，先这样 |
| 720 | heldout_bnd_parse_not_ocr_070 | parse_document | 辛苦帮个忙，fa80752b-1e00-2f86-5cdc-abae5fd4714a 文档解析走起，要章节摘要 |
| 724 | heldout_bnd_water_not_index_074 | extract_water_mask | 对了，我要 08e7ca1eb990 水域的范围掩膜，不是算什么指数 |
| 730 | heldout_bnd_ocr_not_detect_080 | ocr_recognize | 在吗？想请教下，756d1c07633e 上的文字给我读出来，不是让你找飞机，先这样 |
| 737 | heldout_bnd_ocr_not_parse_087 | ocr_recognize | 急用，0cf1b817dfa8 是张扫描地图，读上面的字，不是解析什么文档，今天要 |
| 767 | heldout_bnd_detect_not_segment_117 | detect_objects | 辛苦帮个忙，只找 f73ea9e585cd 里的船，不用整图分类 越快越好 |
| 790 | heldout_bnd_segment_not_detect_140 | segment_landcover | 嗨，那个，把 66d6f9c8f437 的建筑植被水体分区，不是数飞机，先这样 |
| 800 | heldout_bnd_parse_not_ocr_150 | parse_document | 麻烦了，1bd366ac-f934-eb4d-f89d-c61f0d669608 文挡解析走起，要章节摘要 谢谢啦 |
| 806 | heldout_bnd_segment_not_detect_156 | segment_landcover | 918373e3adb6 我要地表分类图，别给我检测结果 |
| 810 | heldout_bnd_ocr_not_detect_160 | ocr_recognize | 对了，41a8da96d22e 这图我只关心上面写了啥字，目标别管 谢谢啦 |
| 813 | heldout_bnd_index_not_water_163 | calculate_spectral_index | 急用，只要 38e40e163b21 的 NDWI 指数，不用提取水体矢量 越快越好 |
| 822 | heldout_bnd_segment_not_detect_172 | segment_landcover | 在吗？想请教下，对 77fec798ccbf 做整图地物分割，不要目标框，先这样 |
| 833 | heldout_bnd_ocr_not_parse_183 | ocr_recognize | 麻烦了，6df0ba621726 上的注记认出来就行，别走文档总结 |
| 853 | heldout_cmp_web_003 | web_search | 急用，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格 |
| 861 | heldout_cmp_web_011 | web_search | 辛苦帮个忙，帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接 越快越好 |
| 862 | heldout_cmp_web_012 | web_search | 嗨，那个，下周末杭州天气怎么样，再帮我查下当地民宿价格行情，先这样 |
| 867 | heldout_cmp_web_017 | web_search | 下周末杭州天气怎么样，再帮我查下当地民宿价格行情，今天要 |
| 884 | heldout_cmp_multi_001 | none | 嗨，那个，把 a38171021605 的云掩膜和水体掩膜一次性都做了 谢谢啦 |
| 888 | heldout_cmp_multi_005 | none | 麻烦了，cbde805bae6b 帮我同时算 NDVI 又提水体 谢谢啦 |
| 894 | heldout_cmp_multi_011 | none | 在吗？想请教下，一口气把 3c85a3334915 的文字读出来再算个 NBR 麻烦尽快 |
| 899 | heldout_cmp_multi_016 | none | 嗨，那个，896e2412a31e 先查元数据，接着直接分割，一条龙，今天要 |
| 916 | heldout_cmp_multi_033 | none | 麻烦了，一口气把 d96929b2612b 的文字读出来再算个 NBR，先这样 |
| 919 | heldout_cmp_multi_036 | none | 麻烦了，b122685cdbd3 既要真彩色预览也要目标检测，一起出 谢谢啦 |
| 931 | heldout_cmp_multi_048 | none | 嗨，那个，8d51fc636e48 先查元数据，接着直接分割，一条龙 麻烦尽快 |
| 945 | heldout_cmp_multi_062 | none | 对了，23d88af2b85a 先查元数据，接着直接分割，一条龙，今天要 |
| 950 | heldout_noise_dirty_000 | calculate_ndvi | 对了 c708cdd97bfa 的 ndvi 跑一下呗 急等 麻烦尽快 嗯嗯嗯嗯嗯嗯嗯嗯 |
| 951 | heldout_noise_dirty_001 | detect_objects | e12555d9581c 目标排查：重点是飞机 越快越好 |
| 973 | heldout_noise_dirty_023 | raster_inspect | 麻烦了，帮我确认 9e2ff8a73a7d 的投影和覆盖范围对不对 麻烦尽快 |
| 985 | heldout_noise_badid_010 | calculate_ndvi | 在吗？想请教下，556d37 做个NDVI，记错了的话你帮我看下清单，今天要 |
| 987 | heldout_noise_badid_012 | extract_water_mask | 在吗？想请教下，1f9186 这景帮我做水体掩膜，ID 我记不全了 越快越好 |
| 993 | heldout_noise_badid_018 | cloud_shadow_mask | 影像 4fb92d 的云检测跑一下 越快越好 |

## 人工结论

- [ ] 抽检通过，冻结生效
- [ ] 发现错标（列出 case_id，废弃数据集换 seed 重生成）
