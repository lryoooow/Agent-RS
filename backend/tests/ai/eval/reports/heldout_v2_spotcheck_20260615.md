# heldout-v2 人工抽检报告（分层抽样，每 category 12.5%）

- dataset_hash: `6496bcd6c5441d5a65eb35500bc9257cfc530ee519b88fee7c3c91b75c9a4678`
- seed: 20260620  case_count: 1000  sampled: 126
- 抽样：按 category 分层、seed 确定性随机，每子类至少 1 条——任何子类都不会成为盲区。
- 检查点：①表达无歧义 ②场景合理 ③label 与场景一致。
- 纪律：发现错标不许单条改题；整体废弃本数据集（删除冻结目录——它尚未运行），换新 seed 重新生成冻结。

| # | case_id | expected | query |
| --- | --- | --- | --- |
| 15 | heldout_pos_render_band_composite_015 | render_band_composite | 对了，fb3768df8e3b 渲染成真彩色发我，先这样 |
| 23 | heldout_pos_web_search_023 | web_search | 这两天哪里有台风预警，查一下 麻烦尽快 |
| 30 | heldout_pos_clip_reproject_raster_030 | clip_reproject_raster | 重投影：cbd85f121b83 转 EPSG:32650，谢谢 |
| 34 | heldout_pos_parse_document_034 | parse_document | 急用，我传的那份文挡 f81fc42b-794f-e01d-5298-a3bdb38b291f，帮我把要点捋一捋，先这样 |
| 40 | heldout_pos_cloud_shadow_mask_040 | cloud_shadow_mask | 辛苦帮个忙，对 140f42679351 做去云前的云检测，先这样 |
| 41 | heldout_pos_extract_water_mask_041 | extract_water_mask | 辛苦帮个忙，把 f989c56410be 的河湖水域提取一下 |
| 69 | heldout_pos_ocr_recognize_069 | ocr_recognize | 对了，33589c30e049 的图廓注记帮我转成文本，先这样 |
| 70 | heldout_pos_parse_document_070 | parse_document | a75b65bb-f327-1b9d-87d5-9f743ba5baf6 内容整理成几条要点 越快越好 |
| 76 | heldout_pos_cloud_shadow_mask_076 | cloud_shadow_mask | 辛苦帮个忙，查下 cda8bb29b696 哪些区域被云污染了 谢谢啦 |
| 80 | heldout_pos_segment_landcover_080 | segment_landcover | 嗨，那个，给 7e9dee4554fb 跑语义分割，分地物类型 谢谢啦 |
| 91 | heldout_pos_detect_objects_091 | detect_objects | 急用，2b1cf311decc 目标排查：重点是油罐 麻烦尽快 |
| 97 | heldout_pos_calculate_ndvi_097 | calculate_ndvi | 在吗？想请教下，看下 b47c92b3fe8e 里植被健康度，先出 NDVI，拜托拜托 |
| 107 | heldout_pos_web_search_107 | web_search | 对了，今年自然资源部有没有出新的遥感监测政策，先这样 |
| 123 | heldout_pos_render_band_composite_123 | render_band_composite | 在吗？想请教下，fc8fe222f544 渲染成真彩色发我 麻烦尽快 |
| 125 | heldout_pos_extract_water_mask_125 | extract_water_mask | 嗨，那个，5f18af1c94ca 哪里是水，出个水体掩膜，先这样 |
| 126 | heldout_pos_clip_reproject_raster_126 | clip_reproject_raster | 在吗？想请教下，重投影：21a8938cdb93 转 EPSG:32650，谢谢 麻烦尽快 |
| 133 | heldout_pos_calculate_ndvi_133 | calculate_ndvi | 急用，5e69156ad6bd 这块地的植被长势咋样，跑个 NDVI 看看 越快越好 |
| 144 | heldout_pos_raster_inspect_144 | raster_inspect | 急用，ee9b8c450b61 的元数据帮我拉出来看看 |
| 160 | heldout_pos_cloud_shadow_mask_160 | cloud_shadow_mask | 嗨，那个，eb020a2a4625 的云量情况出个掩膜评估下，拜托拜托 |
| 165 | heldout_pos_ocr_recognize_165 | ocr_recognize | 嗨，那个，读取 5e942510261c 中的文字标注信息 谢谢啦 |
| 168 | heldout_pos_raster_inspect_168 | raster_inspect | 辛苦帮个忙，先核对一下 3128f8c7cdaf 的影像参数再说别的，先这样 |
| 187 | heldout_pos_detect_objects_187 | detect_objects | 辛苦帮个忙，帮我定位 b20d0c87e3e3 中的桥 谢谢啦 |
| 191 | heldout_pos_web_search_191 | web_search | 在吗？想请教下，搜下最新的 Landsat 数据下载渠道变化 谢谢啦 |
| 211 | heldout_pos_detect_objects_211 | detect_objects | 数一数 cf96f82adebd 里有多少油罐，拜托拜托 |
| 219 | heldout_pos_render_band_composite_219 | render_band_composite | 在吗？想请教下，给 b6b69d42da20 做真彩色显示，今天要 |
| 233 | heldout_pos_extract_water_mask_233 | extract_water_mask | 急用，b991b4353ded 做水体提取，掩膜给我，今天要 |
| 246 | heldout_pos_clip_reproject_raster_246 | clip_reproject_raster | 嗨，那个，729b3416f09f 现在的投影不对，统一到 EPSG:3857，今天要 |
| 248 | heldout_pos_segment_landcover_248 | segment_landcover | 急用，698369d146cb 给我分一下地表类别，哪块是建筑哪块是植被，先这样 |
| 251 | heldout_pos_web_search_251 | web_search | 在吗？想请教下，查查 2026 年新发布的开源遥感数据集有哪些 谢谢啦 |
| 266 | heldout_pos_calculate_spectral_index_266 | calculate_spectral_index | 麻烦了，算 水分指数 NDMI 吧，影像是 ce4ae3cdc6dd 谢谢啦 |
| 267 | heldout_pos_render_band_composite_267 | render_band_composite | 在吗？想请教下，2830115e4413 渲染成真彩色发我 越快越好 |
| 277 | heldout_pos_calculate_ndvi_277 | calculate_ndvi | 麻烦了，看下 0e7d411635ed 里植被健康度，先出 NDVI，先这样 |
| 284 | heldout_pos_segment_landcover_284 | segment_landcover | abf4c27e99d2 给我分一下地表类别，哪块是建筑哪块是植被，拜托拜托 |
| 286 | heldout_pos_parse_document_286 | parse_document | 嗨，那个，帮我读文挡 1066bb15-9815-592a-870e-056c7d75db25，给个摘要，今天要 |
| 288 | heldout_pos_raster_inspect_288 | raster_inspect | 对了，帮我确认 576438d15fc4 的投影和覆盖范围对不对，拜托拜托 |
| 290 | heldout_pos_calculate_spectral_index_290 | calculate_spectral_index | dcf82568631e 我想看 建筑指数 NDBI，麻烦算一下 |
| 292 | heldout_pos_cloud_shadow_mask_292 | cloud_shadow_mask | 在吗？想请教下，给 ea9e9cf6550f 跑一遍云阴影检测 麻烦尽快 |
| 307 | heldout_pos_detect_objects_307 | detect_objects | 麻烦了，ba19f52f4eac 这景找船，标出来 麻烦尽快 |
| 309 | heldout_pos_ocr_recognize_309 | ocr_recognize | 麻烦了，读取 84ad1526143d 中的文字标注信息，先这样 |
| 313 | heldout_pos_calculate_ndvi_313 | calculate_ndvi | 嗨，那个，看下 76e2dfc239e3 里植被健康度，先出 NDVI 越快越好 |
| 314 | heldout_pos_calculate_spectral_index_314 | calculate_spectral_index | 在吗？想请教下，帮我把 bc576c2cf679 的 水体指数 NDWI 跑出来 麻烦尽快 |
| 318 | heldout_pos_clip_reproject_raster_318 | clip_reproject_raster | 急用，bcac1251a9bf 帮我换到 EPSG:3857 这个坐标系，拜托拜托 |
| 322 | heldout_pos_parse_document_322 | parse_document | 文档 cf722132-cfc4-aa0f-4440-90d34a100323 的核心内容提炼出来 谢谢啦 |
| 338 | heldout_pos_calculate_spectral_index_338 | calculate_spectral_index | 急用，1d874c6c3de4 需要做 火烧迹地指数 NBR 分析 |
| 341 | heldout_pos_extract_water_mask_341 | extract_water_mask | 急用，提取 82dcdf220869 的水体分布，今天要 |
| 344 | heldout_pos_segment_landcover_344 | segment_landcover | ce73e37ee95d 的地表覆盖类型图做一份，今天要 |
| 345 | heldout_pos_ocr_recognize_345 | ocr_recognize | 嗨，那个，读取 223439a29f01 中的文字标注信息，今天要 |
| 348 | heldout_pos_raster_inspect_348 | raster_inspect | 急用，查询影像 a2a1cb8a4107 的 profile 信息 |
| 353 | heldout_neg_non_owner_003 | none | 麻烦了，用 f5da8b2f0c49 跑 水体掩膜，今天要 |
| 368 | heldout_neg_negation_018 | none | 辛苦帮个忙，目标检测 别处理，解释清楚概念就行，先这样 |
| 387 | heldout_neg_concept_037 | none | 辛苦帮个忙，科普一下 假彩色 呗，先这样 |
| 390 | heldout_neg_general_040 | none | 麻烦了，算下 3721 加 8964 等于几 麻烦尽快 |
| 393 | heldout_neg_concept_043 | none | 麻烦了，NBR 和普通照片处理的区别是啥，先这样 |
| 402 | heldout_neg_general_052 | none | Excel 怎么做数据透视表，今天要 |
| 413 | heldout_neg_non_owner_063 | none | 嗨，那个，影像 a487f00a413d 帮我算个 重投影 麻烦尽快 |
| 419 | heldout_neg_non_owner_069 | none | 对了，3a878b8454fc，任务是水体掩膜，开始吧，今天要 |
| 429 | heldout_neg_concept_079 | none | 急用，云阴影 和普通照片处理的区别是啥 |
| 440 | heldout_neg_negation_090 | none | 对了，水体提取 别处理，解释清楚概念就行，今天要 |
| 444 | heldout_neg_general_094 | none | 麻烦了，讲讲什么是过拟合 谢谢啦 |
| 463 | heldout_neg_contradiction_113 | none | 嗨，那个，靠重投影功能数一数 1c3f4eab3251 里的车 麻烦尽快 |
| 475 | heldout_neg_contradiction_125 | none | 嗨，那个，拿云掩膜工具把文档 52b82c97-e6e0-d6d4-b7aa-166f2416c952 总结一下，先这样 |
| 477 | heldout_neg_concept_127 | none | 辛苦帮个忙，科普一下 云阴影 呗 谢谢啦 |
| 493 | heldout_neg_contradiction_143 | none | 嗨，那个，靠重投影功能数一数 299ecdefeafa 里的车 |
| 494 | heldout_neg_negation_144 | none | 对了，我现在不需要你跑 水体提取，只想听原理 越快越好 |
| 506 | heldout_neg_negation_156 | none | 先不要执行 NDVI，说说它适合什么场景，今天要 |
| 514 | heldout_neg_missing_id_164 | none | 那张图的 地物分割 安排一下，今天要 |
| 516 | heldout_neg_general_166 | none | 对了，讲讲什么是过拟合 越快越好 |
| 523 | heldout_neg_contradiction_173 | none | 嗨，那个，用水体提取工具识别 46f4a36d107b 里的飞机，先这样 |
| 538 | heldout_neg_missing_id_188 | none | 辛苦帮个忙，对刚才传的那个直接做 地物分割 谢谢啦 |
| 549 | heldout_neg_concept_199 | none | 嗨，那个，假彩色 的取值范围一般是多少，怎么解读，今天要 |
| 550 | heldout_neg_missing_id_200 | segment_landcover | 在吗？想请教下，那张图的 地物分割 安排一下，拜托拜托 |
| 556 | heldout_neg_missing_id_206 | none | 在吗？想请教下，上面那景影像帮我跑 地物分割，对了我还没给你 ID，今天要 |
| 560 | heldout_neg_negation_210 | none | 麻烦了，我现在不需要你跑 地物分割，只想听原理，今天要 |
| 587 | heldout_neg_non_owner_237 | none | 用 a2aefca86213 跑 NDVI |
| 588 | heldout_neg_general_238 | none | 辛苦帮个忙，算下 3721 加 8964 等于几 |
| 589 | heldout_neg_contradiction_239 | none | 在吗？想请教下，用 NDVI 这个算法看看 bec03af4ca31 里有几条船，先这样 |
| 590 | heldout_neg_negation_240 | none | 停，NDVI 这步先不做，原理是什么 谢谢啦 |
| 592 | heldout_neg_missing_id_242 | none | 急用，把刚说的那张图做个 地物分割 麻烦尽快 |
| 601 | heldout_neg_contradiction_251 | none | 拿波段合成功能翻译文档 f7a5298d-a11b-7569-b5a1-0ae0573a3741 麻烦尽快 |
| 612 | heldout_neg_general_262 | none | 嗨，那个，把 land cover 翻译成中文 麻烦尽快 |
| 617 | heldout_neg_non_owner_267 | none | 急用，d5906d9a9bad，任务是水体掩膜，开始吧 越快越好 |
| 621 | heldout_neg_concept_271 | none | NBR 的取值范围一般是多少，怎么解读 谢谢啦 |
| 628 | heldout_neg_missing_id_278 | none | 对了，上面那景影像帮我跑 云检测，对了我还没给你 ID 麻烦尽快 |
| 629 | heldout_neg_non_owner_279 | none | 麻烦了，影像 4202869c9fb5 帮我算个 NDVI 谢谢啦 |
| 653 | heldout_bnd_index_not_water_003 | calculate_spectral_index | 辛苦帮个忙，aef0f525000d 算个 NDWI 就行，别做水域提取，先这样 |
| 662 | heldout_bnd_segment_not_detect_012 | segment_landcover | 在吗？想请教下，c5aaa616fb01 整幅按地类分块，不是找单个目标，今天要 |
| 669 | heldout_bnd_index_not_water_019 | calculate_spectral_index | 辛苦帮个忙，给 1368f62f334f 出 NDWI 指数图，水体掩膜不需要 |
| 682 | heldout_bnd_ocr_not_detect_032 | ocr_recognize | 急用，5004bff195f9 上的文字给我读出来，不是让你找飞机，先这样 |
| 687 | heldout_bnd_detect_not_segment_037 | detect_objects | 急用，只找 abc6dd1273df 里的船，不用整图分类 越快越好 |
| 690 | heldout_bnd_ocr_not_detect_040 | ocr_recognize | 对了，9bac70cdb8d2 这图我只关心上面写了啥字，目标别管 |
| 700 | heldout_bnd_water_not_index_050 | extract_water_mask | 在吗？想请教下，提取 e0e29d358838 实际的水面分布，不是指数计算 麻烦尽快 |
| 735 | heldout_bnd_detect_not_segment_085 | detect_objects | 在吗？想请教下，ebf950c6ca88 找车，别跑分割 |
| 739 | heldout_bnd_detect_not_ocr_089 | detect_objects | 对了，框出 2d5d2a014ee0 中的油罐，文字识别就免了，今天要 |
| 744 | heldout_bnd_parse_not_ocr_094 | parse_document | 帮我梳理文档 028744eb-d0bd-b5e9-615c-64760f306ef0 的结构，这不是扫描图识字，今天要 |
| 757 | heldout_bnd_index_not_water_107 | calculate_spectral_index | 在吗？想请教下，f4f4a29ac4df 算个 NDWI 就行，别做水域提取，今天要 |
| 760 | heldout_bnd_parse_not_ocr_110 | parse_document | 对了，8a933d91-d07a-c43c-4045-e74e72b76e31 是个 PDF，提炼内容，不用 OCR 影像，拜托拜托 |
| 767 | heldout_bnd_detect_not_segment_117 | detect_objects | 嗨，那个，只找 c091655081b4 里的船，不用整图分类 谢谢啦 |
| 779 | heldout_bnd_detect_not_ocr_129 | detect_objects | 麻烦了，框出 44c8297f369e 中的油罐，文字识别就免了 |
| 785 | heldout_bnd_ocr_not_parse_135 | ocr_recognize | 在吗？想请教下，a78d4843754f 上的注记认出来就行，别走文档总结 麻烦尽快 |
| 787 | heldout_bnd_detect_not_ocr_137 | detect_objects | 对了，dca48a2b80a2 里把船找出来，我不要图上的文字，今天要 |
| 796 | heldout_bnd_water_not_index_146 | extract_water_mask | 辛苦帮个忙，8fecd18819ba 圈水域，要掩膜结果不要指数图，拜托拜托 |
| 802 | heldout_bnd_ocr_not_detect_152 | ocr_recognize | 对了，f6dcb99ad854 上的文字给我读出来，不是让你找飞机 麻烦尽快 |
| 809 | heldout_bnd_ocr_not_parse_159 | ocr_recognize | 对了，9367dcc028ec 上的注记认出来就行，别走文档总结 麻烦尽快 |
| 812 | heldout_bnd_water_not_index_162 | extract_water_mask | 麻烦了，5c20a7e268c4 圈水域，要掩膜结果不要指数图 越快越好 |
| 830 | heldout_bnd_segment_not_detect_180 | segment_landcover | 3405f1a3d509 整幅按地类分块，不是找单个目标 谢谢啦 |
| 846 | heldout_bnd_segment_not_detect_196 | segment_landcover | 嗨，那个，对 4dc7bec88e40 做整图地物分割，不要目标框，拜托拜托 |
| 848 | heldout_bnd_parse_not_ocr_198 | parse_document | 在吗？想请教下，帮我梳理文档 97415d04-f303-9012-096a-2b8a43da3714 的结构，这不是扫描图识字，先这样 |
| 849 | heldout_bnd_ocr_not_parse_199 | ocr_recognize | 麻烦了，这景 86a2fc110f66 的地图标注文字提取下，不是文档解析，先这样 |
| 854 | heldout_cmp_web_004 | web_search | 麻烦了，看下这周末上海限行规定，以及天气适不适合外拍，拜托拜托 |
| 858 | heldout_cmp_web_008 | web_search | 搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格 谢谢啦 |
| 868 | heldout_cmp_web_018 | web_search | 看下这周末上海限行规定，以及天气适不适合外拍，今天要 |
| 874 | heldout_cmp_web_024 | web_search | 麻烦了，下周末杭州天气怎么样，再帮我查下当地民宿价格行情 |
| 883 | heldout_cmp_multi_000 | none | 把 ade9c75cb70a 的云掩膜和水体掩膜一次性都做了 越快越好 |
| 884 | heldout_cmp_multi_001 | none | 嗨，那个，把 0169b9fa7271 的云掩膜和水体掩膜一次性都做了 谢谢啦 |
| 900 | heldout_cmp_multi_017 | none | 急用，17f9db2537b5 先查元数据，接着直接分割，一条龙 |
| 901 | heldout_cmp_multi_018 | none | 辛苦帮个忙，5047908f3058 帮我同时算 NDVI 又提水体 |
| 928 | heldout_cmp_multi_045 | none | 在吗？想请教下，197b5b0ead5b 重投影完顺手把船和飞机都检测了 |
| 929 | heldout_cmp_multi_046 | none | 102ed4576e26 先查元数据，接着直接分割，一条龙 麻烦尽快 |
| 938 | heldout_cmp_multi_055 | none | 对了，bd46cfafff43 先查元数据，接着直接分割，一条龙 越快越好 |
| 946 | heldout_cmp_multi_063 | none | 在吗？想请教下，6ac93039996d 重投影完顺手把船和飞机都检测了，拜托拜托 |
| 953 | heldout_noise_dirty_003 | calculate_ndvi | 麻烦了 评估下 45584da87729 的植被覆盖 用 NDVI 就行 嗯嗯嗯嗯嗯嗯 |
| 955 | heldout_noise_dirty_005 | raster_inspect | 麻烦了，帮我确认 03e0ba17ceca 的投影和覆盖范围对不对 麻烦尽快 嗯嗯嗯 |
| 963 | heldout_noise_dirty_013 | detect_objects | 检出 6eff38ef239d 中所有车的位置，今天要 嗯嗯嗯嗯嗯嗯嗯嗯 |
| 976 | heldout_noise_badid_001 | extract_water_mask | 对了，a3f9e5 这景帮我做水体掩膜，ID 我记不全了，拜托拜托 |
| 996 | heldout_noise_badid_021 | calculate_ndvi | 影像 cdd34352 的NDVI跑一下 麻烦尽快 |
| 998 | heldout_noise_badid_023 | segment_landcover | 在吗？想请教下，对 83f5fbaf 做地物分割，应该是这个 ID 吧 |

## 人工结论

- [ ] 抽检通过，冻结生效
- [ ] 发现错标（列出 case_id，废弃数据集换 seed 重生成）
