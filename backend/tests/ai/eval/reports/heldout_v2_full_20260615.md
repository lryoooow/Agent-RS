# heldout-v2 完整样本（全 1000 条，供人工通览审查）

- dataset_hash: `6496bcd6c5441d5a65eb35500bc9257cfc530ee519b88fee7c3c91b75c9a4678`
- seed: 20260620  case_count: 1000
- 字段：# / case_id / expected_action / capability / 清单形态(自有图数,含非属主标注) / scoring / query
- 清单形态：0图=空清单，N图=N张自有图，+他=含非属主诱饵。多图+指代/损坏ID 是修正口径重点。
- 检查点：①表达无歧义 ②场景合理 ③label 与场景一致（尤其多图 call/none 分流）。

| # | case_id | action | capability | 清单 | scoring | query |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | heldout_pos_raster_inspect_000 | call | raster_inspect | 1图 | main | 上传的 d5bc909a8456 是多少波段的？顺便看下 CRS 麻烦尽快 |
| 1 | heldout_pos_calculate_ndvi_001 | call | calculate_ndvi | 1图 | main | 对了，评估下 6d091a16dd66 的植被覆盖，用 NDVI 就行 谢谢啦 |
| 2 | heldout_pos_calculate_spectral_index_002 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，1009187f7a18 我想看 建筑指数 NDBI，麻烦算一下，拜托拜托 |
| 3 | heldout_pos_render_band_composite_003 | call | render_band_composite | 1图 | main | 嗨，那个，真彩色合成图来一张，用 223cb9455bd9 谢谢啦 |
| 4 | heldout_pos_cloud_shadow_mask_004 | call | cloud_shadow_mask | 1图 | main | 8a086ec6d39d 的云量情况出个掩模评估下，今天要 |
| 5 | heldout_pos_extract_water_mask_005 | call | extract_water_mask | 1图 | main | 在吗？想请教下，32dce73e9254 哪里是水，出个水体掩模，今天要 |
| 6 | heldout_pos_clip_reproject_raster_006 | call | clip_reproject_raster | 1图 | main | 在吗？想请教下，重头影：728467931813 转 EPSG:32649，谢谢，今天要 |
| 7 | heldout_pos_detect_objects_007 | call | detect_objects | 1图 | main | 嗨，那个，扫一下 ba7ebcd25bb4 看看车在哪 |
| 8 | heldout_pos_segment_landcover_008 | call | segment_landcover | 1图 | main | 辛苦帮个忙，对 6c89af3c7800 做土地覆盖分区 谢谢啦 |
| 9 | heldout_pos_ocr_recognize_009 | call | ocr_recognize | 1图 | main | 嗨，那个，e5f47aab02e5 上写了什么字？OCR 一下 麻烦尽快 |
| 10 | heldout_pos_parse_document_010 | call | parse_document | 0图 | main | 嗨，那个，总结一下文档 8d923c51-3c73-1f2d-80a5-8bce3320dad1 讲了什么 麻烦尽快 |
| 11 | heldout_pos_web_search_011 | call | web_search | 0图 | main | 对了，最近高分卫星影像的官方采购价格是多少 |
| 12 | heldout_pos_raster_inspect_012 | call | raster_inspect | 1图 | main | 在吗？想请教下，我想先摸清 3133a1a22f2a 的底细，分辨率、范围、坐标系都报一下，先这样 |
| 13 | heldout_pos_calculate_ndvi_013 | call | calculate_ndvi | 1图 | main | 麻烦了，给 0a578e3b1385 算下植被指数 NDVI，看看绿化情况 |
| 14 | heldout_pos_calculate_spectral_index_014 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，算 增强植被指数 EVI 吧，影象是 3fe59726f199 越快越好 |
| 15 | heldout_pos_render_band_composite_015 | call | render_band_composite | 1图 | main | 对了，fb3768df8e3b 渲染成真彩色发我，先这样 |
| 16 | heldout_pos_cloud_shadow_mask_016 | call | cloud_shadow_mask | 1图 | main | 嗨，那个，给 c728c8110c04 跑一遍云阴影检侧，今天要 |
| 17 | heldout_pos_extract_water_mask_017 | call | extract_water_mask | 1图 | main | 2d38bd40fb41 做水体提取，掩模给我 麻烦尽快 |
| 18 | heldout_pos_clip_reproject_raster_018 | call | clip_reproject_raster | 1图 | main | 对了，6bc731f2794d 转成 EPSG:4326 的投影，拜托拜托 |
| 19 | heldout_pos_detect_objects_019 | call | detect_objects | 1图 | main | 嗨，那个，检出 063600783ed8 中所有车的位置 越快越好 |
| 20 | heldout_pos_segment_landcover_020 | call | segment_landcover | 1图 | main | 辛苦帮个忙，给 a752e26e456e 跑语义分割，分地物类型 |
| 21 | heldout_pos_ocr_recognize_021 | call | ocr_recognize | 1图 | main | 在吗？想请教下，6434d2db1643 里印的文字内容提取一下 |
| 22 | heldout_pos_parse_document_022 | call | parse_document | 0图 | main | 在吗？想请教下，帮我读文档 1f4077b2-18b7-dd37-1c38-3dfb13f97001，给个摘要 |
| 23 | heldout_pos_web_search_023 | call | web_search | 0图 | main | 这两天哪里有台风预警，查一下 麻烦尽快 |
| 24 | heldout_pos_raster_inspect_024 | call | raster_inspect | 1图 | main | 麻烦了，帮我确认 8556637f5c48 的投影和覆盖范围对不对，今天要 |
| 25 | heldout_pos_calculate_ndvi_025 | call | calculate_ndvi | 1图 | main | 对了，d44eef3c89f2 这块地的植被长势咋样，跑个 NDVI 看看，先这样 |
| 26 | heldout_pos_calculate_spectral_index_026 | call | calculate_spectral_index | 1图 | main | b46158f188cd 我想看 土壤调节植被 SAVI，麻烦算一下，拜托拜托 |
| 27 | heldout_pos_render_band_composite_027 | call | render_band_composite | 1图 | main | 在吗？想请教下，把 7c59f8bb657a 弄成真彩色图我瞅瞅，拜托拜托 |
| 28 | heldout_pos_cloud_shadow_mask_028 | call | cloud_shadow_mask | 1图 | main | 麻烦了，想确认 d6145f7700dd 是不是被云挡了，做个掩膜 越快越好 |
| 29 | heldout_pos_extract_water_mask_029 | call | extract_water_mask | 1图 | main | 把 a13acbde73e7 的河湖水域提取一下 谢谢啦 |
| 30 | heldout_pos_clip_reproject_raster_030 | call | clip_reproject_raster | 1图 | main | 重投影：cbd85f121b83 转 EPSG:32650，谢谢 |
| 31 | heldout_pos_detect_objects_031 | call | detect_objects | 1图 | main | 在吗？想请教下，3af817daf99d 目标排查：重点是油罐 |
| 32 | heldout_pos_segment_landcover_032 | call | segment_landcover | 1图 | main | 急用，1690c1d88834 整景做地物分类分割，先这样 |
| 33 | heldout_pos_ocr_recognize_033 | call | ocr_recognize | 1图 | main | 嗨，那个，e74e2593a469 的图廓注记帮我转成文本 麻烦尽快 |
| 34 | heldout_pos_parse_document_034 | call | parse_document | 0图 | main | 急用，我传的那份文挡 f81fc42b-794f-e01d-5298-a3bdb38b291f，帮我把要点捋一捋，先这样 |
| 35 | heldout_pos_web_search_035 | call | web_search | 0图 | main | 辛苦帮个忙，后天广州会不会下暴雨，出门要不要带伞，先这样 |
| 36 | heldout_pos_raster_inspect_036 | call | raster_inspect | 1图 | main | 急用，这景 044c877de993 到底几个波段、什么投影，给我看下基本信息，拜托拜托 |
| 37 | heldout_pos_calculate_ndvi_037 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，c8f706006054 这块地的植被长势咋样，跑个 NDVI 看看 谢谢啦 |
| 38 | heldout_pos_calculate_spectral_index_038 | call | calculate_spectral_index | 1图 | main | 麻烦了，90e39d8c1df1 我想看 水分指数 NDMI，麻烦算一下 |
| 39 | heldout_pos_render_band_composite_039 | call | render_band_composite | 1图 | main | 嗨，那个，34564cabb798 出个假彩色预览，拜托拜托 |
| 40 | heldout_pos_cloud_shadow_mask_040 | call | cloud_shadow_mask | 1图 | main | 辛苦帮个忙，对 140f42679351 做去云前的云检测，先这样 |
| 41 | heldout_pos_extract_water_mask_041 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，把 f989c56410be 的河湖水域提取一下 |
| 42 | heldout_pos_clip_reproject_raster_042 | call | clip_reproject_raster | 1图 | main | 急用，99455fb75646 现在的投影不对，统一到 EPSG:32649 |
| 43 | heldout_pos_detect_objects_043 | call | detect_objects | 1图 | main | 11739dfda993 目标排查：重点是油罐，先这样 |
| 44 | heldout_pos_segment_landcover_044 | call | segment_landcover | 1图 | main | 24f15cdbbbca 整景做地物分类分割，今天要 |
| 45 | heldout_pos_ocr_recognize_045 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，把 fac6e3ec70ee 图面上的注记识别出来 谢谢啦 |
| 46 | heldout_pos_parse_document_046 | call | parse_document | 0图 | main | 嗨，那个，我传的那份文档 dba255ae-a940-cfce-5522-4c72b913d0d1，帮我把要点捋一捋 谢谢啦 |
| 47 | heldout_pos_web_search_047 | call | web_search | 0图 | main | 急用，后天广州会不会下暴雨，出门要不要带伞，今天要 |
| 48 | heldout_pos_raster_inspect_048 | call | raster_inspect | 1图 | main | 麻烦了，帮我确认 b3b369177427 的投影和覆盖范围对不对，拜托拜托 |
| 49 | heldout_pos_calculate_ndvi_049 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，评估下 7bbb6ff25f15 的植被覆盖，用 NDVI 就行，先这样 |
| 50 | heldout_pos_calculate_spectral_index_050 | call | calculate_spectral_index | 1图 | main | 0e8b19840aed 需要做 增强植被指数 EVI 分析 谢谢啦 |
| 51 | heldout_pos_render_band_composite_051 | call | render_band_composite | 1图 | main | 嗨，那个，353344bfcc36 渲染成假彩色发我，今天要 |
| 52 | heldout_pos_cloud_shadow_mask_052 | call | cloud_shadow_mask | 1图 | main | 9a209a3444b6 需要云和云影的质检掩膜 麻烦尽快 |
| 53 | heldout_pos_extract_water_mask_053 | call | extract_water_mask | 1图 | main | 急用，fb8964bb019a 做水体提取，掩膜给我 谢谢啦 |
| 54 | heldout_pos_clip_reproject_raster_054 | call | clip_reproject_raster | 1图 | main | 在吗？想请教下，acd165c14391 转成 EPSG:32649 的投影 |
| 55 | heldout_pos_detect_objects_055 | call | detect_objects | 1图 | main | 麻烦了，73c1ea1bc101 这景找飞机，标出来，拜托拜托 |
| 56 | heldout_pos_segment_landcover_056 | call | segment_landcover | 1图 | main | 急用，对 7c0d8f6a4a63 做土地覆盖分区 |
| 57 | heldout_pos_ocr_recognize_057 | call | ocr_recognize | 1图 | main | 嗨，那个，读取 ec91e3f51fba 中的文字标注信息，拜托拜托 |
| 58 | heldout_pos_parse_document_058 | call | parse_document | 0图 | main | 对了，总结一下文档 db9a5b52-89db-2ce5-7214-abbd7137cf4f 讲了什么，今天要 |
| 59 | heldout_pos_web_search_059 | call | web_search | 0图 | main | 嗨，那个，今年自然资源部有没有出新的遥感监测政策，拜托拜托 |
| 60 | heldout_pos_raster_inspect_060 | call | raster_inspect | 1图 | main | 麻烦了，帮我确认 a7ca726816a0 的投影和覆盖范围对不对 谢谢啦 |
| 61 | heldout_pos_calculate_ndvi_061 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，看下 c7a0d9304cee 里植被健康度，先出 NDVI，先这样 |
| 62 | heldout_pos_calculate_spectral_index_062 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，1d80cc77e5ec 这景，水体指数 NDWI 安排上，先这样 |
| 63 | heldout_pos_render_band_composite_063 | call | render_band_composite | 1图 | main | 急用，把 008a55f4961c 弄成假彩色图我瞅瞅 越快越好 |
| 64 | heldout_pos_cloud_shadow_mask_064 | call | cloud_shadow_mask | 1图 | main | 急用，给 d2bf604a2dd9 跑一遍云阴影检测，先这样 |
| 65 | heldout_pos_extract_water_mask_065 | call | extract_water_mask | 1图 | main | 急用，e2e476bdc475 做水体提取，掩膜给我，先这样 |
| 66 | heldout_pos_clip_reproject_raster_066 | call | clip_reproject_raster | 1图 | main | 对了，需要把 8ef70998d221 的坐标系改成 EPSG:32649，今天要 |
| 67 | heldout_pos_detect_objects_067 | call | detect_objects | 1图 | main | 在吗？想请教下，帮我定位 e01a7583d846 中的飞机 |
| 68 | heldout_pos_segment_landcover_068 | call | segment_landcover | 1图 | main | 麻烦了，987fff013235 的地表覆盖类型图做一份 谢谢啦 |
| 69 | heldout_pos_ocr_recognize_069 | call | ocr_recognize | 1图 | main | 对了，33589c30e049 的图廓注记帮我转成文本，先这样 |
| 70 | heldout_pos_parse_document_070 | call | parse_document | 0图 | main | a75b65bb-f327-1b9d-87d5-9f743ba5baf6 内容整理成几条要点 越快越好 |
| 71 | heldout_pos_web_search_071 | call | web_search | 0图 | main | 麻烦了，帮我查今天北京的空气质量指数 |
| 72 | heldout_pos_raster_inspect_072 | call | raster_inspect | 1图 | main | 对了，我想先摸清 83e59e8f8647 的底细，分辨率、范围、坐标系都报一下 |
| 73 | heldout_pos_calculate_ndvi_073 | call | calculate_ndvi | 1图 | main | 辛苦帮个忙，麻烦对 b5aaad0ecd10 执行 NDVI 计算 谢谢啦 |
| 74 | heldout_pos_calculate_spectral_index_074 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，出一份 945045857893 的 增强植被指数 EVI 图，拜托拜托 |
| 75 | heldout_pos_render_band_composite_075 | call | render_band_composite | 1图 | main | 急用，70b475a33c51 出个真彩色预览，拜托拜托 |
| 76 | heldout_pos_cloud_shadow_mask_076 | call | cloud_shadow_mask | 1图 | main | 辛苦帮个忙，查下 cda8bb29b696 哪些区域被云污染了 谢谢啦 |
| 77 | heldout_pos_extract_water_mask_077 | call | extract_water_mask | 1图 | main | 麻烦了，提取 889c4b791790 的水体分布 |
| 78 | heldout_pos_clip_reproject_raster_078 | call | clip_reproject_raster | 1图 | main | 嗨，那个，对 fa53d9e13b5b 做投影转换，目标 EPSG:32649 |
| 79 | heldout_pos_detect_objects_079 | call | detect_objects | 1图 | main | 嗨，那个，6bb7d4ac0815 里有没有桥，帮我框出来 越快越好 |
| 80 | heldout_pos_segment_landcover_080 | call | segment_landcover | 1图 | main | 嗨，那个，给 7e9dee4554fb 跑语义分割，分地物类型 谢谢啦 |
| 81 | heldout_pos_ocr_recognize_081 | call | ocr_recognize | 1图 | main | 急用，读取 44ee04c05966 中的文字标注信息 越快越好 |
| 82 | heldout_pos_parse_document_082 | call | parse_document | 0图 | main | 嗨，那个，我传的那份文档 dae327b8-5706-8875-d665-168d6ca634d4，帮我把要点捋一捋，先这样 |
| 83 | heldout_pos_web_search_083 | call | web_search | 0图 | main | 在吗？想请教下，这两天哪里有台风预警，查一下，拜托拜托 |
| 84 | heldout_pos_raster_inspect_084 | call | raster_inspect | 1图 | main | 对了，这景 27ce32c11590 到底几个波段、什么投影，给我看下基本信息，拜托拜托 |
| 85 | heldout_pos_calculate_ndvi_085 | call | calculate_ndvi | 1图 | main | 麻烦了，看下 34e2990376a8 里植被健康度，先出 NDVI，拜托拜托 |
| 86 | heldout_pos_calculate_spectral_index_086 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，318e4c4e81b8 我想看 火烧迹地指数 NBR，麻烦算一下 谢谢啦 |
| 87 | heldout_pos_render_band_composite_087 | call | render_band_composite | 1图 | main | 在吗？想请教下，我想看 e880f927d513 的假彩色效果 越快越好 |
| 88 | heldout_pos_cloud_shadow_mask_088 | call | cloud_shadow_mask | 1图 | main | 嗨，那个，08d92d035433 的云量情况出个掩膜评估下 谢谢啦 |
| 89 | heldout_pos_extract_water_mask_089 | call | extract_water_mask | 1图 | main | 提取 3cd17c6fcbf8 的水体分布，今天要 |
| 90 | heldout_pos_clip_reproject_raster_090 | call | clip_reproject_raster | 1图 | main | 对了，aa64aeb6bad1 帮我换到 EPSG:32650 这个坐标系，今天要 |
| 91 | heldout_pos_detect_objects_091 | call | detect_objects | 1图 | main | 急用，2b1cf311decc 目标排查：重点是油罐 麻烦尽快 |
| 92 | heldout_pos_segment_landcover_092 | call | segment_landcover | 1图 | main | 麻烦了，给 d842f390dea8 跑语义分割，分地物类型，先这样 |
| 93 | heldout_pos_ocr_recognize_093 | call | ocr_recognize | 1图 | main | 对了，读取 c8506b06c7ec 中的文字标注信息，先这样 |
| 94 | heldout_pos_parse_document_094 | call | parse_document | 0图 | main | 对了，文挡 1c9b4e18-743c-1dc3-2ab6-6e6acc480541 的核心内容提炼出来，今天要 |
| 95 | heldout_pos_web_search_095 | call | web_search | 0图 | main | 辛苦帮个忙，今年自然资源部有没有出新的遥感监测政策 麻烦尽快 |
| 96 | heldout_pos_raster_inspect_096 | call | raster_inspect | 1图 | main | 对了，这景 19e6de47a0c5 到底几个波段、什么投影，给我看下基本信息，先这样 |
| 97 | heldout_pos_calculate_ndvi_097 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，看下 b47c92b3fe8e 里植被健康度，先出 NDVI，拜托拜托 |
| 98 | heldout_pos_calculate_spectral_index_098 | call | calculate_spectral_index | 1图 | main | 嗨，那个，出一份 e94a151f1e20 的 增强植被指数 EVI 图 |
| 99 | heldout_pos_render_band_composite_099 | call | render_band_composite | 1图 | main | 给 fdc156e07d3a 做真彩色显示，先这样 |
| 100 | heldout_pos_cloud_shadow_mask_100 | call | cloud_shadow_mask | 1图 | main | 在吗？想请教下，对 29baa99be743 做去云前的云检测，拜托拜托 |
| 101 | heldout_pos_extract_water_mask_101 | call | extract_water_mask | 1图 | main | 对了，把 202562fe1b87 的河湖水域提取一下，拜托拜托 |
| 102 | heldout_pos_clip_reproject_raster_102 | call | clip_reproject_raster | 1图 | main | 辛苦帮个忙，226bfaf2d8ce 现在的投影不对，统一到 EPSG:32650，今天要 |
| 103 | heldout_pos_detect_objects_103 | call | detect_objects | 1图 | main | 054b88111608 这景找桥，标出来，先这样 |
| 104 | heldout_pos_segment_landcover_104 | call | segment_landcover | 1图 | main | 在吗？想请教下，11a5c67af939 整景做地物分类分割 谢谢啦 |
| 105 | heldout_pos_ocr_recognize_105 | call | ocr_recognize | 1图 | main | 对了，读取 dc20420ccd39 中的文字标注信息，今天要 |
| 106 | heldout_pos_parse_document_106 | call | parse_document | 0图 | main | 急用，文档 32b0687e-3a12-c593-e4cb-e6b3e7b59684 的核心内容提炼出来，先这样 |
| 107 | heldout_pos_web_search_107 | call | web_search | 0图 | main | 对了，今年自然资源部有没有出新的遥感监测政策，先这样 |
| 108 | heldout_pos_raster_inspect_108 | call | raster_inspect | 1图 | main | 急用，上传的 27f619cc6fce 是多少波段的？顺便看下 CRS 谢谢啦 |
| 109 | heldout_pos_calculate_ndvi_109 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，accef13b0136 这块地的植被长势咋样，跑个 NDVI 看看 谢谢啦 |
| 110 | heldout_pos_calculate_spectral_index_110 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，帮我把 be4ae8af1438 的 增强植被指数 EVI 跑出来，今天要 |
| 111 | heldout_pos_render_band_composite_111 | call | render_band_composite | 1图 | main | 把 d4c9bb0e67f6 弄成假彩色图我瞅瞅，今天要 |
| 112 | heldout_pos_cloud_shadow_mask_112 | call | cloud_shadow_mask | 1图 | main | 在吗？想请教下，17728ac8a62f 的云量情况出个掩膜评估下 |
| 113 | heldout_pos_extract_water_mask_113 | call | extract_water_mask | 1图 | main | 急用，a3330ca0d20c 里的水面范围帮我勾出来 越快越好 |
| 114 | heldout_pos_clip_reproject_raster_114 | call | clip_reproject_raster | 1图 | main | 对了，390095046549 帮我换到 EPSG:3857 这个坐标系，今天要 |
| 115 | heldout_pos_detect_objects_115 | call | detect_objects | 1图 | main | 对了，扫一下 3868bcc218c3 看看桥在哪 麻烦尽快 |
| 116 | heldout_pos_segment_landcover_116 | call | segment_landcover | 1图 | main | 在吗？想请教下，5ee3208a0ecd 给我分一下地表类别，哪块是建筑哪块是植被 谢谢啦 |
| 117 | heldout_pos_ocr_recognize_117 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，ad947059fc76 的图廓注记帮我转成文本，先这样 |
| 118 | heldout_pos_parse_document_118 | call | parse_document | 0图 | main | 急用，帮我读文档 f8a15abc-e9ea-9628-4149-d05d02269faa，给个摘要 麻烦尽快 |
| 119 | heldout_pos_web_search_119 | call | web_search | 0图 | main | 辛苦帮个忙，后天广州会不会下暴雨，出门要不要带伞，今天要 |
| 120 | heldout_pos_raster_inspect_120 | call | raster_inspect | 1图 | main | 麻烦了，我想先摸清 39e55e63f103 的底细，分辨率、范围、坐标系都报一下 谢谢啦 |
| 121 | heldout_pos_calculate_ndvi_121 | call | calculate_ndvi | 1图 | main | 急用，评估下 8a1e24fd4ac8 的植被覆盖，用 NDVI 就行，拜托拜托 |
| 122 | heldout_pos_calculate_spectral_index_122 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，帮我把 e5d82f4f5d8d 的 火烧迹地指数 NBR 跑出来 越快越好 |
| 123 | heldout_pos_render_band_composite_123 | call | render_band_composite | 1图 | main | 在吗？想请教下，fc8fe222f544 渲染成真彩色发我 麻烦尽快 |
| 124 | heldout_pos_cloud_shadow_mask_124 | call | cloud_shadow_mask | 1图 | main | 辛苦帮个忙，对 a52390dfaa01 做去云前的云检测 谢谢啦 |
| 125 | heldout_pos_extract_water_mask_125 | call | extract_water_mask | 1图 | main | 嗨，那个，5f18af1c94ca 哪里是水，出个水体掩膜，先这样 |
| 126 | heldout_pos_clip_reproject_raster_126 | call | clip_reproject_raster | 1图 | main | 在吗？想请教下，重投影：21a8938cdb93 转 EPSG:32650，谢谢 麻烦尽快 |
| 127 | heldout_pos_detect_objects_127 | call | detect_objects | 1图 | main | 麻烦了，3310b0a6f90d 里有没有桥，帮我框出来 |
| 128 | heldout_pos_segment_landcover_128 | call | segment_landcover | 1图 | main | 对 77727525adee 做土地覆盖分区 谢谢啦 |
| 129 | heldout_pos_ocr_recognize_129 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，读取 02f33cd84aac 中的文字标注信息 |
| 130 | heldout_pos_parse_document_130 | call | parse_document | 0图 | main | b5ddb00f-401d-0bb0-bf84-c57c03a2f0ed 这个文件太长了，概括下重点，拜托拜托 |
| 131 | heldout_pos_web_search_131 | call | web_search | 0图 | main | 对了，后天广州会不会下暴雨，出门要不要带伞 越快越好 |
| 132 | heldout_pos_raster_inspect_132 | call | raster_inspect | 1图 | main | 嗨，那个，74befd70ac1b 这景图的基本属性查一下，宽高波段那些 麻烦尽快 |
| 133 | heldout_pos_calculate_ndvi_133 | call | calculate_ndvi | 1图 | main | 急用，5e69156ad6bd 这块地的植被长势咋样，跑个 NDVI 看看 越快越好 |
| 134 | heldout_pos_calculate_spectral_index_134 | call | calculate_spectral_index | 1图 | main | 对了，帮我把 37155b8106f5 的 水分指数 NDMI 跑出来，拜托拜托 |
| 135 | heldout_pos_render_band_composite_135 | call | render_band_composite | 1图 | main | 麻烦了，真彩色合成图来一张，用 6ca5819b0440 谢谢啦 |
| 136 | heldout_pos_cloud_shadow_mask_136 | call | cloud_shadow_mask | 1图 | main | a2c01346f579 好像有云，先把云和阴影圈出来质检下 麻烦尽快 |
| 137 | heldout_pos_extract_water_mask_137 | call | extract_water_mask | 1图 | main | 在吗？想请教下，提取 8ee1c42b38e8 的水体分布 |
| 138 | heldout_pos_clip_reproject_raster_138 | call | clip_reproject_raster | 1图 | main | 麻烦了，需要把 dae68ed96972 的坐标系改成 EPSG:4326，拜托拜托 |
| 139 | heldout_pos_detect_objects_139 | call | detect_objects | 1图 | main | 辛苦帮个忙，数一数 c6f0a8f71437 里有多少车 麻烦尽快 |
| 140 | heldout_pos_segment_landcover_140 | call | segment_landcover | 1图 | main | f95bb22a7caf 整景做地物分类分割 越快越好 |
| 141 | heldout_pos_ocr_recognize_141 | call | ocr_recognize | 1图 | main | 嗨，那个，6bbc98918f0e 的图廓注记帮我转成文本 |
| 142 | heldout_pos_parse_document_142 | call | parse_document | 0图 | main | 对了，把 66deea5f-9bb9-1d68-2a2d-cd9e80fe8366 里的章节要点列一列，拜托拜托 |
| 143 | heldout_pos_web_search_143 | call | web_search | 0图 | main | 嗨，那个，搜下最新的 Landsat 数据下载渠道变化，先这样 |
| 144 | heldout_pos_raster_inspect_144 | call | raster_inspect | 1图 | main | 急用，ee9b8c450b61 的元数据帮我拉出来看看 |
| 145 | heldout_pos_calculate_ndvi_145 | call | calculate_ndvi | 1图 | main | 对了，看下 179762670b53 里植被健康度，先出 NDVI，今天要 |
| 146 | heldout_pos_calculate_spectral_index_146 | call | calculate_spectral_index | 1图 | main | 对了，出一份 0bc489d7b452 的 建筑指数 NDBI 图 |
| 147 | heldout_pos_render_band_composite_147 | call | render_band_composite | 1图 | main | 麻烦了，我想看 d477341652f9 的假彩色效果 |
| 148 | heldout_pos_cloud_shadow_mask_148 | call | cloud_shadow_mask | 1图 | main | 对了，查下 0687486d3a01 哪些区域被云污染了，今天要 |
| 149 | heldout_pos_extract_water_mask_149 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，241dceb0662a 里的水面范围帮我勾出来 |
| 150 | heldout_pos_clip_reproject_raster_150 | call | clip_reproject_raster | 1图 | main | 麻烦了，对 9be1eaa5f46b 做投影转换，目标 EPSG:32650，先这样 |
| 151 | heldout_pos_detect_objects_151 | call | detect_objects | 1图 | main | 急用，ebca647dc928 这景找飞机，标出来，今天要 |
| 152 | heldout_pos_segment_landcover_152 | call | segment_landcover | 1图 | main | 嗨，那个，2469641b177a 给我分一下地表类别，哪块是建筑哪块是植被 |
| 153 | heldout_pos_ocr_recognize_153 | call | ocr_recognize | 1图 | main | 麻烦了，c196ea26a64e 的图廓注记帮我转成文本，先这样 |
| 154 | heldout_pos_parse_document_154 | call | parse_document | 0图 | main | 嗨，那个，把 c6972283-d1b7-5394-32a2-93b19488dccc 里的章节要点列一列 越快越好 |
| 155 | heldout_pos_web_search_155 | call | web_search | 0图 | main | 麻烦了，后天广州会不会下暴雨，出门要不要带伞，拜托拜托 |
| 156 | heldout_pos_raster_inspect_156 | call | raster_inspect | 1图 | main | 对了，帮我确认 29684300ec90 的投影和覆盖范围对不对，先这样 |
| 157 | heldout_pos_calculate_ndvi_157 | call | calculate_ndvi | 1图 | main | 急用，帮忙出一下 76c6286a7f4d 的归一化植被指数 |
| 158 | heldout_pos_calculate_spectral_index_158 | call | calculate_spectral_index | 1图 | main | 嗨，那个，算 土壤调节植被 SAVI 吧，影像是 c769ab1965be 麻烦尽快 |
| 159 | heldout_pos_render_band_composite_159 | call | render_band_composite | 1图 | main | 把 81f927c815e1 弄成假彩色图我瞅瞅 麻烦尽快 |
| 160 | heldout_pos_cloud_shadow_mask_160 | call | cloud_shadow_mask | 1图 | main | 嗨，那个，eb020a2a4625 的云量情况出个掩膜评估下，拜托拜托 |
| 161 | heldout_pos_extract_water_mask_161 | call | extract_water_mask | 1图 | main | 急用，把 560385b43d8e 的河湖水域提取一下 |
| 162 | heldout_pos_clip_reproject_raster_162 | call | clip_reproject_raster | 1图 | main | 在吗？想请教下，6a9ec4afd93f 帮我换到 EPSG:32650 这个坐标系，拜托拜托 |
| 163 | heldout_pos_detect_objects_163 | call | detect_objects | 1图 | main | efcbee62edbf 目标排查：重点是油罐，先这样 |
| 164 | heldout_pos_segment_landcover_164 | call | segment_landcover | 1图 | main | 嗨，那个，eccd13a341c9 的地表覆盖类型图做一份 谢谢啦 |
| 165 | heldout_pos_ocr_recognize_165 | call | ocr_recognize | 1图 | main | 嗨，那个，读取 5e942510261c 中的文字标注信息 谢谢啦 |
| 166 | heldout_pos_parse_document_166 | call | parse_document | 0图 | main | 对了，把 a99cd2f8-d4b2-1b3d-0b21-f299fc741145 里的章节要点列一列 麻烦尽快 |
| 167 | heldout_pos_web_search_167 | call | web_search | 0图 | main | 嗨，那个，查查 2026 年新发布的开源遥感数据集有哪些，先这样 |
| 168 | heldout_pos_raster_inspect_168 | call | raster_inspect | 1图 | main | 辛苦帮个忙，先核对一下 3128f8c7cdaf 的影像参数再说别的，先这样 |
| 169 | heldout_pos_calculate_ndvi_169 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，麻烦对 0b5925d1f608 执行 NDVI 计祘 越快越好 |
| 170 | heldout_pos_calculate_spectral_index_170 | call | calculate_spectral_index | 1图 | main | 对了，出一份 e26f21fe6607 的 土壤调节植被 SAVI 图 越快越好 |
| 171 | heldout_pos_render_band_composite_171 | call | render_band_composite | 1图 | main | 辛苦帮个忙，我想看 3bf375525320 的假彩色效果，拜托拜托 |
| 172 | heldout_pos_cloud_shadow_mask_172 | call | cloud_shadow_mask | 1图 | main | 急用，想确认 d1e5a2114fe0 是不是被云挡了，做个掩膜，先这样 |
| 173 | heldout_pos_extract_water_mask_173 | call | extract_water_mask | 1图 | main | 对了，45692f7e732b 里的水面范围帮我勾出来 |
| 174 | heldout_pos_clip_reproject_raster_174 | call | clip_reproject_raster | 1图 | main | 辛苦帮个忙，需要把 2f478ab37180 的坐标系改成 EPSG:4326 |
| 175 | heldout_pos_detect_objects_175 | call | detect_objects | 1图 | main | 急用，扫一下 0f5690d0ff9b 看看油罐在哪，先这样 |
| 176 | heldout_pos_segment_landcover_176 | call | segment_landcover | 1图 | main | 对了，给 c07f8ad25cde 跑语义分割，分地物类型 越快越好 |
| 177 | heldout_pos_ocr_recognize_177 | call | ocr_recognize | 1图 | main | 对了，把 afd06b70e62e 图面上的注记识别出来 麻烦尽快 |
| 178 | heldout_pos_parse_document_178 | call | parse_document | 0图 | main | 急用，c8ca1a9a-2394-2348-0c6f-b61f10a49ff2 这个文件太长了，概括下重点 谢谢啦 |
| 179 | heldout_pos_web_search_179 | call | web_search | 0图 | main | 嗨，那个，最近高分卫星影像的官方采购价格是多少，拜托拜托 |
| 180 | heldout_pos_raster_inspect_180 | call | raster_inspect | 1图 | main | 急用，先核对一下 a0e714b933d8 的影像参数再说别的，先这样 |
| 181 | heldout_pos_calculate_ndvi_181 | call | calculate_ndvi | 1图 | main | 嗨，那个，给 1f372e404485 算下植被指数 NDVI，看看绿化情况，先这样 |
| 182 | heldout_pos_calculate_spectral_index_182 | call | calculate_spectral_index | 1图 | main | 麻烦了，出一份 fc1fa3b47960 的 水分指数 NDMI 图 越快越好 |
| 183 | heldout_pos_render_band_composite_183 | call | render_band_composite | 1图 | main | 急用，c85165757112 出个假彩色预览，先这样 |
| 184 | heldout_pos_cloud_shadow_mask_184 | call | cloud_shadow_mask | 1图 | main | 急用，189fc62e1081 的云量情况出个掩膜评估下，今天要 |
| 185 | heldout_pos_extract_water_mask_185 | call | extract_water_mask | 1图 | main | 麻烦了，1c6216ad5509 哪里是水，出个水体掩膜，今天要 |
| 186 | heldout_pos_clip_reproject_raster_186 | call | clip_reproject_raster | 1图 | main | 急用，f604777a90c9 现在的投影不对，统一到 EPSG:32650 越快越好 |
| 187 | heldout_pos_detect_objects_187 | call | detect_objects | 1图 | main | 辛苦帮个忙，帮我定位 b20d0c87e3e3 中的桥 谢谢啦 |
| 188 | heldout_pos_segment_landcover_188 | call | segment_landcover | 1图 | main | 麻烦了，给 ba8a2fd9bcc6 跑语义分割，分地物类型 麻烦尽快 |
| 189 | heldout_pos_ocr_recognize_189 | call | ocr_recognize | 1图 | main | 麻烦了，758459f01ee8 上写了什么字？OCR 一下，拜托拜托 |
| 190 | heldout_pos_parse_document_190 | call | parse_document | 0图 | main | 嗨，那个，把 4e68e070-f7e1-a688-b66e-a8c2a69d3983 里的章节要点列一列，今天要 |
| 191 | heldout_pos_web_search_191 | call | web_search | 0图 | main | 在吗？想请教下，搜下最新的 Landsat 数据下载渠道变化 谢谢啦 |
| 192 | heldout_pos_raster_inspect_192 | call | raster_inspect | 1图 | main | 对了，e686a18993c1 这景图的基本属性查一下，宽高波段那些 谢谢啦 |
| 193 | heldout_pos_calculate_ndvi_193 | call | calculate_ndvi | 1图 | main | 嗨，那个，我要 a3627737d170 的 NDVI 结果图，拜托拜托 |
| 194 | heldout_pos_calculate_spectral_index_194 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，出一份 1817021eed6a 的 土壤调节植被 SAVI 图 越快越好 |
| 195 | heldout_pos_render_band_composite_195 | call | render_band_composite | 1图 | main | fa6b1ee9442e 渲染成真彩色发我，拜托拜托 |
| 196 | heldout_pos_cloud_shadow_mask_196 | call | cloud_shadow_mask | 1图 | main | 2477040588c5 好像有云，先把云和阴影圈出来质检下 越快越好 |
| 197 | heldout_pos_extract_water_mask_197 | call | extract_water_mask | 1图 | main | 麻烦了，把 03aaccc4f447 的河湖水域提取一下，先这样 |
| 198 | heldout_pos_clip_reproject_raster_198 | call | clip_reproject_raster | 1图 | main | 需要把 060fd8b4d83b 的坐标系改成 EPSG:32649 |
| 199 | heldout_pos_detect_objects_199 | call | detect_objects | 1图 | main | 辛苦帮个忙，帮我定位 b9774891450d 中的车，先这样 |
| 200 | heldout_pos_segment_landcover_200 | call | segment_landcover | 1图 | main | 急用，我要 ad5e04836b00 的 landcover 分割结果，今天要 |
| 201 | heldout_pos_ocr_recognize_201 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，把 ee0e02852f33 图面上的注记识别出来 谢谢啦 |
| 202 | heldout_pos_parse_document_202 | call | parse_document | 0图 | main | 在吗？想请教下，总结一下文档 852644ce-af82-8ba1-b2fd-e9bdf25b234c 讲了什么，先这样 |
| 203 | heldout_pos_web_search_203 | call | web_search | 0图 | main | 急用，帮我查今天北京的空气质量指数 |
| 204 | heldout_pos_raster_inspect_204 | call | raster_inspect | 1图 | main | 在吗？想请教下，aa5eee7e579a 这景图的基本属性查一下，宽高波段那些 越快越好 |
| 205 | heldout_pos_calculate_ndvi_205 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，帮忙出一下 563abf036b09 的归一化植被指数，先这样 |
| 206 | heldout_pos_calculate_spectral_index_206 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，对 32410e004094 来个 建筑指数 NDBI 的结果 |
| 207 | heldout_pos_render_band_composite_207 | call | render_band_composite | 1图 | main | 把 866bf2cb3bcc 弄成真彩色图我瞅瞅，今天要 |
| 208 | heldout_pos_cloud_shadow_mask_208 | call | cloud_shadow_mask | 1图 | main | 急用，c0364e926a9f 需要云和云影的质检掩膜 谢谢啦 |
| 209 | heldout_pos_extract_water_mask_209 | call | extract_water_mask | 1图 | main | 在吗？想请教下，提取 4a0e6ddf607d 的水体分布 |
| 210 | heldout_pos_clip_reproject_raster_210 | call | clip_reproject_raster | 1图 | main | 辛苦帮个忙，重投影：ba59b5c88e21 转 EPSG:32649，谢谢 越快越好 |
| 211 | heldout_pos_detect_objects_211 | call | detect_objects | 1图 | main | 数一数 cf96f82adebd 里有多少油罐，拜托拜托 |
| 212 | heldout_pos_segment_landcover_212 | call | segment_landcover | 1图 | main | 嗨，那个，f361cc57dbfc 给我分一下地表类别，哪块是建筑哪块是植被 越快越好 |
| 213 | heldout_pos_ocr_recognize_213 | call | ocr_recognize | 1图 | main | 麻烦了，读取 d078dea8f19c 中的文字标注信息，先这样 |
| 214 | heldout_pos_parse_document_214 | call | parse_document | 0图 | main | 嗨，那个，我传的那份文档 2ceee1dd-94de-b69f-795b-fa88bbb7d88e，帮我把要点捋一捋 |
| 215 | heldout_pos_web_search_215 | call | web_search | 0图 | main | 急用，查查 2026 年新发布的开源遥感数据集有哪些，今天要 |
| 216 | heldout_pos_raster_inspect_216 | call | raster_inspect | 1图 | main | 在吗？想请教下，查询影像 be193c3941b6 的 profile 信息 麻烦尽快 |
| 217 | heldout_pos_calculate_ndvi_217 | call | calculate_ndvi | 1图 | main | 急用，看下 f3618ea71ef1 里植被健康度，先出 NDVI，先这样 |
| 218 | heldout_pos_calculate_spectral_index_218 | call | calculate_spectral_index | 1图 | main | 麻烦了，b80505240a62 需要做 水分指数 NDMI 分析 越快越好 |
| 219 | heldout_pos_render_band_composite_219 | call | render_band_composite | 1图 | main | 在吗？想请教下，给 b6b69d42da20 做真彩色显示，今天要 |
| 220 | heldout_pos_cloud_shadow_mask_220 | call | cloud_shadow_mask | 1图 | main | 给 0000aa61b67b 跑一遍云阴影检测，先这样 |
| 221 | heldout_pos_extract_water_mask_221 | call | extract_water_mask | 1图 | main | 嗨，那个，9d0ecdba8cf3 里的水面范围帮我勾出来，拜托拜托 |
| 222 | heldout_pos_clip_reproject_raster_222 | call | clip_reproject_raster | 1图 | main | 对了，对 16f8700805d4 做投影转换，目标 EPSG:32650 麻烦尽快 |
| 223 | heldout_pos_detect_objects_223 | call | detect_objects | 1图 | main | 麻烦了，扫一下 7d09f7d78b2e 看看车在哪 麻烦尽快 |
| 224 | heldout_pos_segment_landcover_224 | call | segment_landcover | 1图 | main | 在吗？想请教下，把 400b1c99b149 按地类切成一块块的 越快越好 |
| 225 | heldout_pos_ocr_recognize_225 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，b9c318624f35 里印的文字内容提取一下 谢谢啦 |
| 226 | heldout_pos_parse_document_226 | call | parse_document | 0图 | main | 在吗？想请教下，89455f49-b5b6-b143-3202-1992999d9e5e 内容整理成几条要点 麻烦尽快 |
| 227 | heldout_pos_web_search_227 | call | web_search | 0图 | main | 嗨，那个，今年自然资源部有没有出新的遥感监测政策，先这样 |
| 228 | heldout_pos_raster_inspect_228 | call | raster_inspect | 1图 | main | 麻烦了，上传的 4511f3b038c9 是多少波段的？顺便看下 CRS 越快越好 |
| 229 | heldout_pos_calculate_ndvi_229 | call | calculate_ndvi | 1图 | main | 辛苦帮个忙，5d8d02469a4f 的 ndvi 跑一下呗，急等 谢谢啦 |
| 230 | heldout_pos_calculate_spectral_index_230 | call | calculate_spectral_index | 1图 | main | 对了，fd282afb0eaa 需要做 土壤调节植被 SAVI 分析 越快越好 |
| 231 | heldout_pos_render_band_composite_231 | call | render_band_composite | 1图 | main | 麻烦了，35d90eacd205 渲染成假彩色发我 |
| 232 | heldout_pos_cloud_shadow_mask_232 | call | cloud_shadow_mask | 1图 | main | 对了，d57c2231132a 的云量情况出个掩膜评估下 谢谢啦 |
| 233 | heldout_pos_extract_water_mask_233 | call | extract_water_mask | 1图 | main | 急用，b991b4353ded 做水体提取，掩膜给我，今天要 |
| 234 | heldout_pos_clip_reproject_raster_234 | call | clip_reproject_raster | 1图 | main | 麻烦了，对 f2410dd4c158 做投影转换，目标 EPSG:32649，拜托拜托 |
| 235 | heldout_pos_detect_objects_235 | call | detect_objects | 1图 | main | 急用，a2653a775b25 目标排查：重点是飞机，拜托拜托 |
| 236 | heldout_pos_segment_landcover_236 | call | segment_landcover | 1图 | main | 辛苦帮个忙，e935253584f8 整景做地物分类分割 麻烦尽快 |
| 237 | heldout_pos_ocr_recognize_237 | call | ocr_recognize | 1图 | main | 对了，把 ab185979e313 图面上的注记识别出来，拜托拜托 |
| 238 | heldout_pos_parse_document_238 | call | parse_document | 0图 | main | b4cfec4f-c10b-b941-da98-ce70cd999d96 这个文件太长了，概括下重点 麻烦尽快 |
| 239 | heldout_pos_web_search_239 | call | web_search | 0图 | main | 在吗？想请教下，帮我查今天北京的空气质量指数，先这样 |
| 240 | heldout_pos_raster_inspect_240 | call | raster_inspect | 1图 | main | 先核对一下 159b83bb04a0 的影像参数再说别的 谢谢啦 |
| 241 | heldout_pos_calculate_ndvi_241 | call | calculate_ndvi | 1图 | main | 嗨，那个，f40e2b3c5272 这块地的植被长势咋样，跑个 NDVI 看看，今天要 |
| 242 | heldout_pos_calculate_spectral_index_242 | call | calculate_spectral_index | 1图 | main | 麻烦了，算 建筑指数 NDBI 吧，影像是 5f325bf38380 越快越好 |
| 243 | heldout_pos_render_band_composite_243 | call | render_band_composite | 1图 | main | 急用，660cd2ee56e7 出个假彩色预览，拜托拜托 |
| 244 | heldout_pos_cloud_shadow_mask_244 | call | cloud_shadow_mask | 1图 | main | 嗨，那个，ca4b3d27e492 需要云和云影的质检掩模，今天要 |
| 245 | heldout_pos_extract_water_mask_245 | call | extract_water_mask | 1图 | main | 急用，cc870e31ddce 做水体提取，掩膜给我 麻烦尽快 |
| 246 | heldout_pos_clip_reproject_raster_246 | call | clip_reproject_raster | 1图 | main | 嗨，那个，729b3416f09f 现在的投影不对，统一到 EPSG:3857，今天要 |
| 247 | heldout_pos_detect_objects_247 | call | detect_objects | 1图 | main | 在吗？想请教下，fc566dc2a6f8 这景找车，标出来 麻烦尽快 |
| 248 | heldout_pos_segment_landcover_248 | call | segment_landcover | 1图 | main | 急用，698369d146cb 给我分一下地表类别，哪块是建筑哪块是植被，先这样 |
| 249 | heldout_pos_ocr_recognize_249 | call | ocr_recognize | 1图 | main | 急用，读取 a8e4a272f40f 中的文字标注信息，先这样 |
| 250 | heldout_pos_parse_document_250 | call | parse_document | 0图 | main | 急用，文档 f39b2f6d-587a-af2e-59d5-5d5a19272c22 的核心内容提炼出来 |
| 251 | heldout_pos_web_search_251 | call | web_search | 0图 | main | 在吗？想请教下，查查 2026 年新发布的开源遥感数据集有哪些 谢谢啦 |
| 252 | heldout_pos_raster_inspect_252 | call | raster_inspect | 1图 | main | 急用，帮我确认 84b9d81cdfdd 的投影和覆盖范围对不对，今天要 |
| 253 | heldout_pos_calculate_ndvi_253 | call | calculate_ndvi | 1图 | main | 麻烦了，我要 98f4e591aa5e 的 NDVI 结果图 谢谢啦 |
| 254 | heldout_pos_calculate_spectral_index_254 | call | calculate_spectral_index | 1图 | main | 急用，算 土壤调节植被 SAVI 吧，影像是 b35448619825 越快越好 |
| 255 | heldout_pos_render_band_composite_255 | call | render_band_composite | 1图 | main | f9621242bf9d 出个真彩色预览，先这样 |
| 256 | heldout_pos_cloud_shadow_mask_256 | call | cloud_shadow_mask | 1图 | main | 在吗？想请教下，查下 ee104a2d18f1 哪些区域被云污染了，拜托拜托 |
| 257 | heldout_pos_extract_water_mask_257 | call | extract_water_mask | 1图 | main | 对了，e625cf52f4e3 做水体提取，掩模给我，拜托拜托 |
| 258 | heldout_pos_clip_reproject_raster_258 | call | clip_reproject_raster | 1图 | main | 对了，a52f426b8384 现在的投影不对，统一到 EPSG:32650，拜托拜托 |
| 259 | heldout_pos_detect_objects_259 | call | detect_objects | 1图 | main | 急用，数一数 08fc76aecf5d 里有多少飞机 麻烦尽快 |
| 260 | heldout_pos_segment_landcover_260 | call | segment_landcover | 1图 | main | 嗨，那个，8eb4e824a536 整景做地物分类分割，今天要 |
| 261 | heldout_pos_ocr_recognize_261 | call | ocr_recognize | 1图 | main | 对了，认一下 cefc97761690 上面标注的地名文字 谢谢啦 |
| 262 | heldout_pos_parse_document_262 | call | parse_document | 0图 | main | 在吗？想请教下，531040cd-250a-a8ea-1b3a-ce57d5232d42 这个文件太长了，概括下重点，今天要 |
| 263 | heldout_pos_web_search_263 | call | web_search | 0图 | main | 急用，后天广州会不会下暴雨，出门要不要带伞 谢谢啦 |
| 264 | heldout_pos_raster_inspect_264 | call | raster_inspect | 1图 | main | 嗨，那个，ea9244235ec6 的元数据帮我拉出来看看 麻烦尽快 |
| 265 | heldout_pos_calculate_ndvi_265 | call | calculate_ndvi | 1图 | main | 急用，我要 8ad70d6b9621 的 NDVI 结果图 谢谢啦 |
| 266 | heldout_pos_calculate_spectral_index_266 | call | calculate_spectral_index | 1图 | main | 麻烦了，算 水分指数 NDMI 吧，影像是 ce4ae3cdc6dd 谢谢啦 |
| 267 | heldout_pos_render_band_composite_267 | call | render_band_composite | 1图 | main | 在吗？想请教下，2830115e4413 渲染成真彩色发我 越快越好 |
| 268 | heldout_pos_cloud_shadow_mask_268 | call | cloud_shadow_mask | 1图 | main | 急用，67f84db9f9d2 的云量情况出个掩模评估下 谢谢啦 |
| 269 | heldout_pos_extract_water_mask_269 | call | extract_water_mask | 1图 | main | 麻烦了，圈一下 f0642265283e 里的湖泊河流范围 谢谢啦 |
| 270 | heldout_pos_clip_reproject_raster_270 | call | clip_reproject_raster | 1图 | main | 在吗？想请教下，5ecf68da8827 帮我换到 EPSG:4326 这个坐标系 麻烦尽快 |
| 271 | heldout_pos_detect_objects_271 | call | detect_objects | 1图 | main | 嗨，那个，00b0b83b8b47 目标排查：重点是桥，今天要 |
| 272 | heldout_pos_segment_landcover_272 | call | segment_landcover | 1图 | main | 对了，806c4f23b13d 给我分一下地表类别，哪块是建筑哪块是植被 越快越好 |
| 273 | heldout_pos_ocr_recognize_273 | call | ocr_recognize | 1图 | main | 嗨，那个，认一下 e863e684d855 上面标注的地名文字 越快越好 |
| 274 | heldout_pos_parse_document_274 | call | parse_document | 0图 | main | 麻烦了，帮我读文档 87776faa-d009-42f1-b0de-6513d074bd87，给个摘要，先这样 |
| 275 | heldout_pos_web_search_275 | call | web_search | 0图 | main | 在吗？想请教下，下周成都的天气趋势帮我查下 越快越好 |
| 276 | heldout_pos_raster_inspect_276 | call | raster_inspect | 1图 | main | 急用，这景 c9bf80c339f7 到底几个波段、什么投影，给我看下基本信息，今天要 |
| 277 | heldout_pos_calculate_ndvi_277 | call | calculate_ndvi | 1图 | main | 麻烦了，看下 0e7d411635ed 里植被健康度，先出 NDVI，先这样 |
| 278 | heldout_pos_calculate_spectral_index_278 | call | calculate_spectral_index | 1图 | main | 49e62a784368 我想看 增强植被指数 EVI，麻烦算一下 越快越好 |
| 279 | heldout_pos_render_band_composite_279 | call | render_band_composite | 1图 | main | 急用，假彩色合成图来一张，用 2c90738107bf，拜托拜托 |
| 280 | heldout_pos_cloud_shadow_mask_280 | call | cloud_shadow_mask | 1图 | main | 辛苦帮个忙，13b9863b78c7 好像有云，先把云和阴影圈出来质检下，先这样 |
| 281 | heldout_pos_extract_water_mask_281 | call | extract_water_mask | 1图 | main | 对了，圈一下 59ad70595db3 里的湖泊河流范围 麻烦尽快 |
| 282 | heldout_pos_clip_reproject_raster_282 | call | clip_reproject_raster | 1图 | main | 嗨，那个，把 2c22b7eb56df 重投到 EPSG:32649，拜托拜托 |
| 283 | heldout_pos_detect_objects_283 | call | detect_objects | 1图 | main | 急用，数一数 c6584fd937d9 里有多少车 |
| 284 | heldout_pos_segment_landcover_284 | call | segment_landcover | 1图 | main | abf4c27e99d2 给我分一下地表类别，哪块是建筑哪块是植被，拜托拜托 |
| 285 | heldout_pos_ocr_recognize_285 | call | ocr_recognize | 1图 | main | 嗨，那个，认一下 8009f51d46c3 上面标注的地名文字 麻烦尽快 |
| 286 | heldout_pos_parse_document_286 | call | parse_document | 0图 | main | 嗨，那个，帮我读文挡 1066bb15-9815-592a-870e-056c7d75db25，给个摘要，今天要 |
| 287 | heldout_pos_web_search_287 | call | web_search | 0图 | main | 下周成都的天气趋势帮我查下 谢谢啦 |
| 288 | heldout_pos_raster_inspect_288 | call | raster_inspect | 1图 | main | 对了，帮我确认 576438d15fc4 的投影和覆盖范围对不对，拜托拜托 |
| 289 | heldout_pos_calculate_ndvi_289 | call | calculate_ndvi | 1图 | main | 麻烦了，看下 46c7af033198 里植被健康度，先出 NDVI 麻烦尽快 |
| 290 | heldout_pos_calculate_spectral_index_290 | call | calculate_spectral_index | 1图 | main | dcf82568631e 我想看 建筑指数 NDBI，麻烦算一下 |
| 291 | heldout_pos_render_band_composite_291 | call | render_band_composite | 1图 | main | 在吗？想请教下，给 28f262dc541f 做真彩色显示 麻烦尽快 |
| 292 | heldout_pos_cloud_shadow_mask_292 | call | cloud_shadow_mask | 1图 | main | 在吗？想请教下，给 ea9e9cf6550f 跑一遍云阴影检测 麻烦尽快 |
| 293 | heldout_pos_extract_water_mask_293 | call | extract_water_mask | 1图 | main | 急用，a09b3a2b2c19 里的水面范围帮我勾出来 谢谢啦 |
| 294 | heldout_pos_clip_reproject_raster_294 | call | clip_reproject_raster | 1图 | main | 麻烦了，重投影：7c1d4ad3a8e8 转 EPSG:4326，谢谢 麻烦尽快 |
| 295 | heldout_pos_detect_objects_295 | call | detect_objects | 1图 | main | 麻烦了，f33df342b886 里有没有船，帮我框出来，先这样 |
| 296 | heldout_pos_segment_landcover_296 | call | segment_landcover | 1图 | main | 嗨，那个，把 55f32eae9d59 按地类切成一块块的 谢谢啦 |
| 297 | heldout_pos_ocr_recognize_297 | call | ocr_recognize | 1图 | main | 麻烦了，把 1d27f1e49204 图面上的注记识别出来，先这样 |
| 298 | heldout_pos_parse_document_298 | call | parse_document | 0图 | main | 在吗？想请教下，a46ca648-0e4f-ef19-c3f2-13221ae9972a 内容整理成几条要点 麻烦尽快 |
| 299 | heldout_pos_web_search_299 | call | web_search | 0图 | main | 最近高分卫星影象的官方采购价格是多少 麻烦尽快 |
| 300 | heldout_pos_raster_inspect_300 | call | raster_inspect | 1图 | main | 嗨，那个，这景 4497ac64c67d 到底几个波段、什么投影，给我看下基本信息，拜托拜托 |
| 301 | heldout_pos_calculate_ndvi_301 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，我要 9350dc32ed18 的 NDVI 结果图 麻烦尽快 |
| 302 | heldout_pos_calculate_spectral_index_302 | call | calculate_spectral_index | 1图 | main | 急用，帮我把 c4a26a95ba73 的 水分指数 NDMI 跑出来 麻烦尽快 |
| 303 | heldout_pos_render_band_composite_303 | call | render_band_composite | 1图 | main | 麻烦了，把 96521d1f7413 弄成假彩色图我瞅瞅 |
| 304 | heldout_pos_cloud_shadow_mask_304 | call | cloud_shadow_mask | 1图 | main | 辛苦帮个忙，对 4b5182576ca9 做去云前的云检测 谢谢啦 |
| 305 | heldout_pos_extract_water_mask_305 | call | extract_water_mask | 1图 | main | 麻烦了，2b91fc85605c 里的水面范围帮我勾出来，先这样 |
| 306 | heldout_pos_clip_reproject_raster_306 | call | clip_reproject_raster | 1图 | main | 麻烦了，0add853f443c 现在的投影不对，统一到 EPSG:4326，拜托拜托 |
| 307 | heldout_pos_detect_objects_307 | call | detect_objects | 1图 | main | 麻烦了，ba19f52f4eac 这景找船，标出来 麻烦尽快 |
| 308 | heldout_pos_segment_landcover_308 | call | segment_landcover | 1图 | main | 辛苦帮个忙，对 3e7c4f634a81 做土地覆盖分区 麻烦尽快 |
| 309 | heldout_pos_ocr_recognize_309 | call | ocr_recognize | 1图 | main | 麻烦了，读取 84ad1526143d 中的文字标注信息，先这样 |
| 310 | heldout_pos_parse_document_310 | call | parse_document | 0图 | main | 在吗？想请教下，文档 91716873-d8b9-9bcc-1914-74190007dafd 的核心内容提炼出来，先这样 |
| 311 | heldout_pos_web_search_311 | call | web_search | 0图 | main | 对了，后天广州会不会下暴雨，出门要不要带伞，拜托拜托 |
| 312 | heldout_pos_raster_inspect_312 | call | raster_inspect | 1图 | main | 麻烦了，我想先摸清 5d0882c733e1 的底细，分辨率、范围、坐标系都报一下 越快越好 |
| 313 | heldout_pos_calculate_ndvi_313 | call | calculate_ndvi | 1图 | main | 嗨，那个，看下 76e2dfc239e3 里植被健康度，先出 NDVI 越快越好 |
| 314 | heldout_pos_calculate_spectral_index_314 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，帮我把 bc576c2cf679 的 水体指数 NDWI 跑出来 麻烦尽快 |
| 315 | heldout_pos_render_band_composite_315 | call | render_band_composite | 1图 | main | 对了，f91b1e345a23 出个假彩色预览 |
| 316 | heldout_pos_cloud_shadow_mask_316 | call | cloud_shadow_mask | 1图 | main | 嗨，那个，给 65db3e718238 跑一遍云阴影检侧，今天要 |
| 317 | heldout_pos_extract_water_mask_317 | call | extract_water_mask | 1图 | main | 38e1f872fd20 哪里是水，出个水体掩膜 麻烦尽快 |
| 318 | heldout_pos_clip_reproject_raster_318 | call | clip_reproject_raster | 1图 | main | 急用，bcac1251a9bf 帮我换到 EPSG:3857 这个坐标系，拜托拜托 |
| 319 | heldout_pos_detect_objects_319 | call | detect_objects | 1图 | main | 麻烦了，检出 0ce4b372756f 中所有油罐的位置 麻烦尽快 |
| 320 | heldout_pos_segment_landcover_320 | call | segment_landcover | 1图 | main | 在吗？想请教下，0362aecf6bc0 给我分一下地表类别，哪块是建筑哪块是植被 |
| 321 | heldout_pos_ocr_recognize_321 | call | ocr_recognize | 1图 | main | 对了，eea28b6650f4 里印的文字内容提取一下，今天要 |
| 322 | heldout_pos_parse_document_322 | call | parse_document | 0图 | main | 文档 cf722132-cfc4-aa0f-4440-90d34a100323 的核心内容提炼出来 谢谢啦 |
| 323 | heldout_pos_web_search_323 | call | web_search | 0图 | main | 对了，今年自然资源部有没有出新的遥感监测政策，今天要 |
| 324 | heldout_pos_raster_inspect_324 | call | raster_inspect | 1图 | main | 上传的 540512ccda7e 是多少波段的？顺便看下 CRS，拜托拜托 |
| 325 | heldout_pos_calculate_ndvi_325 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，给 ede4fbf3d7a0 算下植被指数 NDVI，看看绿化情况 |
| 326 | heldout_pos_calculate_spectral_index_326 | call | calculate_spectral_index | 1图 | main | 对了，07a2772c91e4 需要做 火烧迹地指数 NBR 分析 麻烦尽快 |
| 327 | heldout_pos_render_band_composite_327 | call | render_band_composite | 1图 | main | 嗨，那个，我想看 76f0af9eaf9e 的假彩色效果，先这样 |
| 328 | heldout_pos_cloud_shadow_mask_328 | call | cloud_shadow_mask | 1图 | main | 对了，34765f08be4f 需要云和云影的质检掩膜 越快越好 |
| 329 | heldout_pos_extract_water_mask_329 | call | extract_water_mask | 1图 | main | 在吗？想请教下，提取 f3b110ffab13 的水体分布 |
| 330 | heldout_pos_clip_reproject_raster_330 | call | clip_reproject_raster | 1图 | main | 嗨，那个，0061177f29aa 帮我换到 EPSG:3857 这个坐标系 谢谢啦 |
| 331 | heldout_pos_detect_objects_331 | call | detect_objects | 1图 | main | 嗨，那个，扫一下 a183c233d436 看看桥在哪 麻烦尽快 |
| 332 | heldout_pos_segment_landcover_332 | call | segment_landcover | 1图 | main | 急用，38078158d70a 的地表覆盖类型图做一份 |
| 333 | heldout_pos_ocr_recognize_333 | call | ocr_recognize | 1图 | main | 麻烦了，60540c1e339c 上写了什么字？OCR 一下，拜托拜托 |
| 334 | heldout_pos_parse_document_334 | call | parse_document | 0图 | main | 对了，把 56015e12-6613-c92f-92ff-9dfb1b36a7cf 里的章节要点列一列，拜托拜托 |
| 335 | heldout_pos_web_search_335 | call | web_search | 0图 | main | 在吗？想请教下，下周成都的天气趋势帮我查下 |
| 336 | heldout_pos_raster_inspect_336 | call | raster_inspect | 1图 | main | 在吗？想请教下，帮我确认 94e9a7c89dda 的投影和覆盖范围对不对 谢谢啦 |
| 337 | heldout_pos_calculate_ndvi_337 | call | calculate_ndvi | 1图 | main | 嗨，那个，3105df10f65f 这块地的植被长势咋样，跑个 NDVI 看看 越快越好 |
| 338 | heldout_pos_calculate_spectral_index_338 | call | calculate_spectral_index | 1图 | main | 急用，1d874c6c3de4 需要做 火烧迹地指数 NBR 分析 |
| 339 | heldout_pos_render_band_composite_339 | call | render_band_composite | 1图 | main | 麻烦了，我想看 250e185854d4 的真彩色效果，拜托拜托 |
| 340 | heldout_pos_cloud_shadow_mask_340 | call | cloud_shadow_mask | 1图 | main | 嗨，那个，想确认 078ef08f252c 是不是被云挡了，做个掩膜 麻烦尽快 |
| 341 | heldout_pos_extract_water_mask_341 | call | extract_water_mask | 1图 | main | 急用，提取 82dcdf220869 的水体分布，今天要 |
| 342 | heldout_pos_clip_reproject_raster_342 | call | clip_reproject_raster | 1图 | main | 在吗？想请教下，07aeea1a5e09 现在的投影不对，统一到 EPSG:32649 越快越好 |
| 343 | heldout_pos_detect_objects_343 | call | detect_objects | 1图 | main | 麻烦了，检出 3c6d1d0e13ec 中所有油罐的位置 麻烦尽快 |
| 344 | heldout_pos_segment_landcover_344 | call | segment_landcover | 1图 | main | ce73e37ee95d 的地表覆盖类型图做一份，今天要 |
| 345 | heldout_pos_ocr_recognize_345 | call | ocr_recognize | 1图 | main | 嗨，那个，读取 223439a29f01 中的文字标注信息，今天要 |
| 346 | heldout_pos_parse_document_346 | call | parse_document | 0图 | main | 总结一下文档 67c505c6-4643-f010-73fb-e03214aaba8d 讲了什么，先这样 |
| 347 | heldout_pos_web_search_347 | call | web_search | 0图 | main | 辛苦帮个忙，帮我查今天北京的空气质量指数 麻烦尽快 |
| 348 | heldout_pos_raster_inspect_348 | call | raster_inspect | 1图 | main | 急用，查询影像 a2a1cb8a4107 的 profile 信息 |
| 349 | heldout_pos_calculate_ndvi_349 | call | calculate_ndvi | 1图 | main | 麻烦了，0f078699b0d8 的 ndvi 跑一下呗，急等，先这样 |
| 350 | heldout_neg_negation_000 | none | - | 0图 | main | 在吗？想请教下，我现在不需要你跑 水体提取，只想听原理 |
| 351 | heldout_neg_concept_001 | none | - | 1图 | main | 急用，云阴影 的取值范围一般是多少，怎么解读，拜托拜托 |
| 352 | heldout_neg_missing_id_002 | none | - | 0图 | main | 辛苦帮个忙，上面那景影像帮我跑 水体掩膜，对了我还没给你 ID 越快越好 |
| 353 | heldout_neg_non_owner_003 | none | - | 0图+他1 | main | 麻烦了，用 f5da8b2f0c49 跑 水体掩膜，今天要 |
| 354 | heldout_neg_general_004 | none | - | 0图 | main | 麻烦了，Excel 怎么做数据透视表，今天要 |
| 355 | heldout_neg_contradiction_005 | none | - | 1图 | main | 麻烦了，靠重投影功能数一数 a71839b720f5 里的车，拜托拜托 |
| 356 | heldout_neg_negation_006 | none | - | 1图 | main | 对了，先不要执行 云掩膜，说说它适合什么场景 越快越好 |
| 357 | heldout_neg_concept_007 | none | - | 1图 | main | 在吗？想请教下，云阴影 的取值范围一般是多少，怎么解读 越快越好 |
| 358 | heldout_neg_missing_id_008 | call | calculate_ndvi | 1图 | main | 麻烦了，对刚才传的那个直接做 NDVI 越快越好 |
| 359 | heldout_neg_non_owner_009 | none | - | 0图+他1 | main | 嗨，那个，麻烦处理 fb1f7ee3d43e 的重投影 谢谢啦 |
| 360 | heldout_neg_general_010 | none | - | 0图 | main | 急用，用 python 写个二分查找，拜托拜托 |
| 361 | heldout_neg_contradiction_011 | none | - | 1图 | main | 在吗？想请教下，拿波段合成功能翻译文档 560b9477-d65f-e6ce-85c3-6af3aace3a1d，先这样 |
| 362 | heldout_neg_negation_012 | none | - | 0图 | main | 急用，我现在不需要你跑 地物分割，只想听原理 麻烦尽快 |
| 363 | heldout_neg_concept_013 | none | - | 1图 | main | 急用，假彩色 的取值范围一般是多少，怎么解读 |
| 364 | heldout_neg_missing_id_014 | none | - | 0图 | main | 急用，上面那景影像帮我跑 水体掩膜，对了我还没给你 ID，今天要 |
| 365 | heldout_neg_non_owner_015 | none | - | 0图+他1 | main | 在吗？想请教下，8786d4315d4c 这景做一下 云检测，拜托拜托 |
| 366 | heldout_neg_general_016 | none | - | 0图 | main | 对了，把 land cover 翻译成中文 |
| 367 | heldout_neg_contradiction_017 | none | - | 1图 | main | 在吗？想请教下，拿波段合成功能翻译文档 edb74f74-d691-cc2b-7594-1aa9215e7934 麻烦尽快 |
| 368 | heldout_neg_negation_018 | none | - | 1图 | main | 辛苦帮个忙，目标检测 别处理，解释清楚概念就行，先这样 |
| 369 | heldout_neg_concept_019 | none | - | 1图 | main | 急用，近红外波段 和普通照片处理的区别是啥，拜托拜托 |
| 370 | heldout_neg_missing_id_020 | none | - | 3图 | main | 就这张图，跑 云检测，今天要 |
| 371 | heldout_neg_non_owner_021 | none | - | 0图+他1 | main | 急用，麻烦处理 295cefb39607 的重投影，今天要 |
| 372 | heldout_neg_general_022 | none | - | 0图 | main | 在吗？想请教下，推荐几本科幻小说 越快越好 |
| 373 | heldout_neg_contradiction_023 | none | - | 1图 | main | 急用，拿云掩膜工具把文档 cbe4e43f-cac7-66b3-5485-15b3e3d0980a 总结一下，先这样 |
| 374 | heldout_neg_negation_024 | none | - | 0图 | main | 嗨，那个，不用调用什么工具，水体提取 的思路给我讲讲 越快越好 |
| 375 | heldout_neg_concept_025 | none | - | 1图 | main | NBR 和普通照片处理的区别是啥 越快越好 |
| 376 | heldout_neg_missing_id_026 | none | - | 0图 | main | 辛苦帮个忙，处理一下我那张图的 云检测 |
| 377 | heldout_neg_non_owner_027 | none | - | 0图+他1 | main | 麻烦了，麻烦处理 0aefcf784de8 的云检测，拜托拜托 |
| 378 | heldout_neg_general_028 | none | - | 0图 | main | 麻烦了，帮我润色一段答辩稿 越快越好 |
| 379 | heldout_neg_contradiction_029 | none | - | 1图 | main | 拿云掩膜工具把文档 755efc9f-ad08-9b20-0800-b3e8c1b9f841 总结一下 麻烦尽快 |
| 380 | heldout_neg_negation_030 | none | - | 1图 | main | 对了，我现在不需要你跑 云掩膜，只想听原理 越快越好 |
| 381 | heldout_neg_concept_031 | none | - | 1图 | main | 急用，科普一下 NDVI 呗，拜托拜托 |
| 382 | heldout_neg_missing_id_032 | call | segment_landcover | 1图 | main | 急用，那张图的 地物分割 安排一下，拜托拜托 |
| 383 | heldout_neg_non_owner_033 | none | - | 0图+他1 | main | 嗨，那个，2bd7abcfa2f6，任务是水体掩膜，开始吧 麻烦尽快 |
| 384 | heldout_neg_general_034 | none | - | 0图 | main | 麻烦了，给我写段项目周报开头 谢谢啦 |
| 385 | heldout_neg_contradiction_035 | none | - | 1图 | main | 对了，用 NDVI 这个算法看看 bf1bdf70334a 里有几条船，拜托拜托 |
| 386 | heldout_neg_negation_036 | none | - | 0图 | main | 辛苦帮个忙，停，地物分割 这步先不做，原理是什么，拜托拜托 |
| 387 | heldout_neg_concept_037 | none | - | 1图 | main | 辛苦帮个忙，科普一下 假彩色 呗，先这样 |
| 388 | heldout_neg_missing_id_038 | none | - | 0图 | main | 对了，处理一下我那张图的 云检测，今天要 |
| 389 | heldout_neg_non_owner_039 | none | - | 0图+他1 | main | 用 64d0440331a1 跑 云检测，先这样 |
| 390 | heldout_neg_general_040 | none | - | 0图 | main | 麻烦了，算下 3721 加 8964 等于几 麻烦尽快 |
| 391 | heldout_neg_contradiction_041 | none | - | 1图 | main | 辛苦帮个忙，用 OCR 帮我判断 9889a96784ea 的植被覆盖多少，今天要 |
| 392 | heldout_neg_negation_042 | none | - | 1图 | main | 在吗？想请教下，停，目标检测 这步先不做，原理是什么 谢谢啦 |
| 393 | heldout_neg_concept_043 | none | - | 1图 | main | 麻烦了，NBR 和普通照片处理的区别是啥，先这样 |
| 394 | heldout_neg_missing_id_044 | none | - | 3图 | main | 急用，那张图的 水体掩膜 安排一下，先这样 |
| 395 | heldout_neg_non_owner_045 | none | - | 0图+他1 | main | 影像 2ec93e402de6 帮我算个 NDVI，今天要 |
| 396 | heldout_neg_general_046 | none | - | 0图 | main | 在吗？想请教下，推荐几本科幻小说 谢谢啦 |
| 397 | heldout_neg_contradiction_047 | none | - | 1图 | main | 用 OCR 帮我判断 88518240a855 的植被覆盖多少 麻烦尽快 |
| 398 | heldout_neg_negation_048 | none | - | 0图 | main | 对了，不用调用什么工具，云掩膜 的思路给我讲讲，先这样 |
| 399 | heldout_neg_concept_049 | none | - | 1图 | main | 对了，云阴影 的取值范围一般是多少，怎么解读，今天要 |
| 400 | heldout_neg_missing_id_050 | none | - | 0图 | main | 在吗？想请教下，处理一下我那张图的 云检测，今天要 |
| 401 | heldout_neg_non_owner_051 | none | - | 0图+他1 | main | 辛苦帮个忙，麻烦处理 053f6c1a6d5f 的NDVI，先这样 |
| 402 | heldout_neg_general_052 | none | - | 0图 | main | Excel 怎么做数据透视表，今天要 |
| 403 | heldout_neg_contradiction_053 | none | - | 1图 | main | 急用，用 OCR 帮我判断 f648c336c2fd 的植被覆盖多少 麻烦尽快 |
| 404 | heldout_neg_negation_054 | none | - | 1图 | main | 麻烦了，我现在不需要你跑 地物分割，只想听原理，先这样 |
| 405 | heldout_neg_concept_055 | none | - | 1图 | main | 科普一下 云阴影 呗，拜托拜托 |
| 406 | heldout_neg_missing_id_056 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，对刚才传的那个直接做 NDVI 越快越好 |
| 407 | heldout_neg_non_owner_057 | none | - | 0图+他1 | main | 麻烦了，用 356c080730fa 跑 地物分割 越快越好 |
| 408 | heldout_neg_general_058 | none | - | 0图 | main | 急用，用 python 写个二分查找 越快越好 |
| 409 | heldout_neg_contradiction_059 | none | - | 1图 | main | 在吗？想请教下，用水体提取工具识别 3c7944ba3a21 里的飞机，今天要 |
| 410 | heldout_neg_negation_060 | none | - | 0图 | main | 嗨，那个，先不要执行 水体提取，说说它适合什么场景，今天要 |
| 411 | heldout_neg_concept_061 | none | - | 1图 | main | 在吗？想请教下，想了解下 NDVI 这个概念，别给我跑数据 谢谢啦 |
| 412 | heldout_neg_missing_id_062 | none | - | 0图 | main | 急用，上面那景影像帮我跑 云检测，对了我还没给你 ID，先这样 |
| 413 | heldout_neg_non_owner_063 | none | - | 0图+他1 | main | 嗨，那个，影像 a487f00a413d 帮我算个 重投影 麻烦尽快 |
| 414 | heldout_neg_general_064 | none | - | 0图 | main | 麻烦了，帮我润色一段答辩稿，今天要 |
| 415 | heldout_neg_contradiction_065 | none | - | 1图 | main | 对了，拿波段合成功能翻译文档 2e3b0149-c678-30a8-987c-6186c8040a20，先这样 |
| 416 | heldout_neg_negation_066 | none | - | 1图 | main | 在吗？想请教下，停，NDVI 这步先不做，原理是什么，先这样 |
| 417 | heldout_neg_concept_067 | none | - | 1图 | main | 科普一下 近红外波段 呗 越快越好 |
| 418 | heldout_neg_missing_id_068 | none | - | 3图 | main | 嗨，那个，就这张图，跑 云检测，先这样 |
| 419 | heldout_neg_non_owner_069 | none | - | 0图+他1 | main | 对了，3a878b8454fc，任务是水体掩膜，开始吧，今天要 |
| 420 | heldout_neg_general_070 | none | - | 0图 | main | 嗨，那个，用 python 写个二分查找，拜托拜托 |
| 421 | heldout_neg_contradiction_071 | none | - | 1图 | main | 嗨，那个，拿云掩膜工具把文档 81469c92-4904-c0aa-248c-1771d87f9c7a 总结一下 越快越好 |
| 422 | heldout_neg_negation_072 | none | - | 0图 | main | 急用，先不要执行 目标检测，说说它适合什么场景 |
| 423 | heldout_neg_concept_073 | none | - | 1图 | main | 急用，云阴影 在遥感里到底意味着什么，先这样 |
| 424 | heldout_neg_missing_id_074 | none | - | 0图 | main | 对了，上面那景影像帮我跑 NDVI，对了我还没给你 ID |
| 425 | heldout_neg_non_owner_075 | none | - | 0图+他1 | main | 麻烦了，影像 ddfc276ff28a 帮我算个 水体掩膜 |
| 426 | heldout_neg_general_076 | none | - | 0图 | main | 急用，讲讲什么是过拟合，先这样 |
| 427 | heldout_neg_contradiction_077 | none | - | 1图 | main | 嗨，那个，拿波段合成功能翻译文档 a5b08774-0549-c7bf-adb7-0d87f619dbfe |
| 428 | heldout_neg_negation_078 | none | - | 1图 | main | 辛苦帮个忙，目标检测 别处理，解释清楚概念就行，拜托拜托 |
| 429 | heldout_neg_concept_079 | none | - | 1图 | main | 急用，云阴影 和普通照片处理的区别是啥 |
| 430 | heldout_neg_missing_id_080 | call | segment_landcover | 1图 | main | 就这张图，跑 地物分割，先这样 |
| 431 | heldout_neg_non_owner_081 | none | - | 0图+他1 | main | 对了，麻烦处理 5442d138399f 的水体掩膜 越快越好 |
| 432 | heldout_neg_general_082 | none | - | 0图 | main | 对了，用 python 写个二分查找 麻烦尽快 |
| 433 | heldout_neg_contradiction_083 | none | - | 1图 | main | 在吗？想请教下，用 NDVI 这个算法看看 9bb51238ba17 里有几条船，今天要 |
| 434 | heldout_neg_negation_084 | none | - | 0图 | main | 急用，停，NDVI 这步先不做，原理是什么，先这样 |
| 435 | heldout_neg_concept_085 | none | - | 1图 | main | NBR 在遥感里到底意味着什么，拜托拜托 |
| 436 | heldout_neg_missing_id_086 | none | - | 0图 | main | 辛苦帮个忙，处理一下我那张图的 地物分割 谢谢啦 |
| 437 | heldout_neg_non_owner_087 | none | - | 0图+他1 | main | 对了，影像 2741f10f0cbf 帮我算个 水体掩膜 麻烦尽快 |
| 438 | heldout_neg_general_088 | none | - | 0图 | main | 用 python 写个二分查找 越快越好 |
| 439 | heldout_neg_contradiction_089 | none | - | 1图 | main | 急用，用水体提取工具识别 341b55b0c9ec 里的飞机，先这样 |
| 440 | heldout_neg_negation_090 | none | - | 1图 | main | 对了，水体提取 别处理，解释清楚概念就行，今天要 |
| 441 | heldout_neg_concept_091 | none | - | 1图 | main | 在吗？想请教下，想了解下 NBR 这个概念，别给我跑数据 谢谢啦 |
| 442 | heldout_neg_missing_id_092 | none | - | 3图 | main | 嗨，那个，那张图的 云检测 安排一下，先这样 |
| 443 | heldout_neg_non_owner_093 | none | - | 0图+他1 | main | 麻烦了，影像 134466f1649d 帮我算个 地物分割，今天要 |
| 444 | heldout_neg_general_094 | none | - | 0图 | main | 麻烦了，讲讲什么是过拟合 谢谢啦 |
| 445 | heldout_neg_contradiction_095 | none | - | 1图 | main | 麻烦了，拿云掩膜工具把文档 104cbcfd-84cd-27dd-f2c8-f6f350dd8d7f 总结一下 谢谢啦 |
| 446 | heldout_neg_negation_096 | none | - | 0图 | main | 急用，先别动手算，就跟我讲讲 目标检测 是怎么回事，拜托拜托 |
| 447 | heldout_neg_concept_097 | none | - | 1图 | main | 云阴影 和普通照片处理的区别是啥，先这样 |
| 448 | heldout_neg_missing_id_098 | none | - | 0图 | main | 对了，处理一下我那张图的 云检测 |
| 449 | heldout_neg_non_owner_099 | none | - | 0图+他1 | main | 麻烦了，麻烦处理 86d8650a60c1 的地物分割，拜托拜托 |
| 450 | heldout_neg_general_100 | none | - | 0图 | main | 嗨，那个，Excel 怎么做数据透视表，今天要 |
| 451 | heldout_neg_contradiction_101 | none | - | 1图 | main | 在吗？想请教下，拿波段合成功能翻译文档 8f7552bb-5004-4022-655b-97b9c98ada1b 麻烦尽快 |
| 452 | heldout_neg_negation_102 | none | - | 1图 | main | 在吗？想请教下，不用调用什么工具，水体提取 的思路给我讲讲 |
| 453 | heldout_neg_concept_103 | none | - | 1图 | main | 科普一下 近红外波段 呗 谢谢啦 |
| 454 | heldout_neg_missing_id_104 | call | calculate_ndvi | 1图 | main | 对刚才传的那个直接做 NDVI，拜托拜托 |
| 455 | heldout_neg_non_owner_105 | none | - | 0图+他1 | main | 急用，b4b1f12d0134 这景做一下 云检测，先这样 |
| 456 | heldout_neg_general_106 | none | - | 0图 | main | 急用，讲讲什么是过拟合 谢谢啦 |
| 457 | heldout_neg_contradiction_107 | none | - | 1图 | main | 靠重投影功能数一数 b64f197e11c2 里的车，先这样 |
| 458 | heldout_neg_negation_108 | none | - | 0图 | main | 不用调用什么工具，目标检测 的思路给我讲讲，先这样 |
| 459 | heldout_neg_concept_109 | none | - | 1图 | main | 嗨，那个，NDVI 和普通照片处理的区别是啥，今天要 |
| 460 | heldout_neg_missing_id_110 | none | - | 0图 | main | 对了，把刚说的那张图做个 NDVI 谢谢啦 |
| 461 | heldout_neg_non_owner_111 | none | - | 0图+他1 | main | 影像 4318f7e5362e 帮我算个 云检测，今天要 |
| 462 | heldout_neg_general_112 | none | - | 0图 | main | 辛苦帮个忙，用 python 写个二分查找 谢谢啦 |
| 463 | heldout_neg_contradiction_113 | none | - | 1图 | main | 嗨，那个，靠重投影功能数一数 1c3f4eab3251 里的车 麻烦尽快 |
| 464 | heldout_neg_negation_114 | none | - | 1图 | main | 对了，我现在不需要你跑 目标检测，只想听原理，先这样 |
| 465 | heldout_neg_concept_115 | none | - | 1图 | main | 麻烦了，NDVI 和普通照片处理的区别是啥 越快越好 |
| 466 | heldout_neg_missing_id_116 | none | - | 3图 | main | 急用，就这张图，跑 地物分割，先这样 |
| 467 | heldout_neg_non_owner_117 | none | - | 0图+他1 | main | 在吗？想请教下，a8aac4622c9c，任务是云检测，开始吧 |
| 468 | heldout_neg_general_118 | none | - | 0图 | main | 急用，推荐几本科幻小说 越快越好 |
| 469 | heldout_neg_contradiction_119 | none | - | 1图 | main | 急用，用水体提取工具识别 afa99faddbc1 里的飞机，拜托拜托 |
| 470 | heldout_neg_negation_120 | none | - | 0图 | main | 先别动手算，就跟我讲讲 云掩膜 是怎么回事，先这样 |
| 471 | heldout_neg_concept_121 | none | - | 1图 | main | 对了，科普一下 NBR 呗 越快越好 |
| 472 | heldout_neg_missing_id_122 | none | - | 0图 | main | 麻烦了，处理一下我那张图的 云检测 谢谢啦 |
| 473 | heldout_neg_non_owner_123 | none | - | 0图+他1 | main | 辛苦帮个忙，用 910202b42cd5 跑 水体掩膜 麻烦尽快 |
| 474 | heldout_neg_general_124 | none | - | 0图 | main | 对了，把 land cover 翻译成中文，先这样 |
| 475 | heldout_neg_contradiction_125 | none | - | 1图 | main | 嗨，那个，拿云掩膜工具把文档 52b82c97-e6e0-d6d4-b7aa-166f2416c952 总结一下，先这样 |
| 476 | heldout_neg_negation_126 | none | - | 1图 | main | 辛苦帮个忙，停，地物分割 这步先不做，原理是什么 麻烦尽快 |
| 477 | heldout_neg_concept_127 | none | - | 1图 | main | 辛苦帮个忙，科普一下 云阴影 呗 谢谢啦 |
| 478 | heldout_neg_missing_id_128 | call | segment_landcover | 1图 | main | 就这张图，跑 地物分割 麻烦尽快 |
| 479 | heldout_neg_non_owner_129 | none | - | 0图+他1 | main | 麻烦了，106b6e2edb43，任务是地物分割，开始吧 谢谢啦 |
| 480 | heldout_neg_general_130 | none | - | 0图 | main | 在吗？想请教下，讲讲什么是过拟合，先这样 |
| 481 | heldout_neg_contradiction_131 | none | - | 1图 | main | 嗨，那个，用 OCR 帮我判断 38a85fc3974c 的植被覆盖多少 |
| 482 | heldout_neg_negation_132 | none | - | 0图 | main | 嗨，那个，不用调用什么工具，NDVI 的思路给我讲讲 谢谢啦 |
| 483 | heldout_neg_concept_133 | none | - | 1图 | main | 为什么大家都用 近红外波段，优缺点呢，拜托拜托 |
| 484 | heldout_neg_missing_id_134 | none | - | 0图 | main | 在吗？想请教下，上面那景影像帮我跑 NDVI，对了我还没给你 ID 麻烦尽快 |
| 485 | heldout_neg_non_owner_135 | none | - | 0图+他1 | main | 急用，影像 b529d62812ca 帮我算个 重投影 |
| 486 | heldout_neg_general_136 | none | - | 0图 | main | 在吗？想请教下，Excel 怎么做数据透视表，拜托拜托 |
| 487 | heldout_neg_contradiction_137 | none | - | 1图 | main | 辛苦帮个忙，拿云掩膜工具把文档 a4a6fda9-4d61-bc20-334b-8e19adcc9657 总结一下，今天要 |
| 488 | heldout_neg_negation_138 | none | - | 1图 | main | 对了，停，地物分割 这步先不做，原理是什么，拜托拜托 |
| 489 | heldout_neg_concept_139 | none | - | 1图 | main | 辛苦帮个忙，想了解下 NDVI 这个概念，别给我跑数据 越快越好 |
| 490 | heldout_neg_missing_id_140 | none | - | 3图 | main | 嗨，那个，对刚才传的那个直接做 地物分割 麻烦尽快 |
| 491 | heldout_neg_non_owner_141 | none | - | 0图+他1 | main | 麻烦了，麻烦处理 8e87dd97db9b 的水体掩膜，先这样 |
| 492 | heldout_neg_general_142 | none | - | 0图 | main | 对了，推荐几本科幻小说，今天要 |
| 493 | heldout_neg_contradiction_143 | none | - | 1图 | main | 嗨，那个，靠重投影功能数一数 299ecdefeafa 里的车 |
| 494 | heldout_neg_negation_144 | none | - | 0图 | main | 对了，我现在不需要你跑 水体提取，只想听原理 越快越好 |
| 495 | heldout_neg_concept_145 | none | - | 1图 | main | 急用，假彩色 的取值范围一般是多少，怎么解读，先这样 |
| 496 | heldout_neg_missing_id_146 | none | - | 0图 | main | 嗨，那个，上面那景影像帮我跑 水体掩膜，对了我还没给你 ID 麻烦尽快 |
| 497 | heldout_neg_non_owner_147 | none | - | 0图+他1 | main | 5111ad1c1981，任务是地物分割，开始吧 越快越好 |
| 498 | heldout_neg_general_148 | none | - | 0图 | main | 把 land cover 翻译成中文 越快越好 |
| 499 | heldout_neg_contradiction_149 | none | - | 1图 | main | 在吗？想请教下，拿云掩膜工具把文档 07c9c503-8f99-c8bc-5dce-ca85c95019b4 总结一下，今天要 |
| 500 | heldout_neg_negation_150 | none | - | 1图 | main | 在吗？想请教下，先别动手算，就跟我讲讲 NDVI 是怎么回事 谢谢啦 |
| 501 | heldout_neg_concept_151 | none | - | 1图 | main | 对了，假彩色 的取值范围一般是多少，怎么解读 麻烦尽快 |
| 502 | heldout_neg_missing_id_152 | call | segment_landcover | 1图 | main | 在吗？想请教下，就这张图，跑 地物分割，先这样 |
| 503 | heldout_neg_non_owner_153 | none | - | 0图+他1 | main | 急用，264ad99906ee，任务是重投影，开始吧，拜托拜托 |
| 504 | heldout_neg_general_154 | none | - | 0图 | main | 嗨，那个，给我写段项目周报开头，先这样 |
| 505 | heldout_neg_contradiction_155 | none | - | 1图 | main | 辛苦帮个忙，拿云掩膜工具把文档 81b60c28-4de7-0dd2-dcef-420fd8dc9acd 总结一下 谢谢啦 |
| 506 | heldout_neg_negation_156 | none | - | 0图 | main | 先不要执行 NDVI，说说它适合什么场景，今天要 |
| 507 | heldout_neg_concept_157 | none | - | 1图 | main | 急用，NBR 和普通照片处理的区别是啥 |
| 508 | heldout_neg_missing_id_158 | none | - | 0图 | main | 辛苦帮个忙，上面那景影像帮我跑 NDVI，对了我还没给你 ID |
| 509 | heldout_neg_non_owner_159 | none | - | 0图+他1 | main | 辛苦帮个忙，麻烦处理 df9dc629478d 的水体掩膜，今天要 |
| 510 | heldout_neg_general_160 | none | - | 0图 | main | 麻烦了，Excel 怎么做数据透视表 麻烦尽快 |
| 511 | heldout_neg_contradiction_161 | none | - | 1图 | main | 急用，拿波段合成功能翻译文档 f48c3b2d-3bf8-4a5e-160b-ac11a1e504de 麻烦尽快 |
| 512 | heldout_neg_negation_162 | none | - | 1图 | main | 先别动手算，就跟我讲讲 云掩膜 是怎么回事，拜托拜托 |
| 513 | heldout_neg_concept_163 | none | - | 1图 | main | 对了，科普一下 NDVI 呗 谢谢啦 |
| 514 | heldout_neg_missing_id_164 | none | - | 3图 | main | 那张图的 地物分割 安排一下，今天要 |
| 515 | heldout_neg_non_owner_165 | none | - | 0图+他1 | main | 0a696f2348fa，任务是水体掩膜，开始吧 |
| 516 | heldout_neg_general_166 | none | - | 0图 | main | 对了，讲讲什么是过拟合 越快越好 |
| 517 | heldout_neg_contradiction_167 | none | - | 1图 | main | 辛苦帮个忙，用 OCR 帮我判断 90e6c423d4ec 的植被覆盖多少 越快越好 |
| 518 | heldout_neg_negation_168 | none | - | 0图 | main | 先不要执行 目标检测，说说它适合什么场景，先这样 |
| 519 | heldout_neg_concept_169 | none | - | 1图 | main | 对了，NDVI 在遥感里到底意味着什么 麻烦尽快 |
| 520 | heldout_neg_missing_id_170 | none | - | 0图 | main | 麻烦了，上面那景影像帮我跑 NDVI，对了我还没给你 ID，先这样 |
| 521 | heldout_neg_non_owner_171 | none | - | 0图+他1 | main | 嗨，那个，1e1ed0e2c048 这景做一下 云检测 |
| 522 | heldout_neg_general_172 | none | - | 0图 | main | 急用，讲讲什么是过拟合 |
| 523 | heldout_neg_contradiction_173 | none | - | 1图 | main | 嗨，那个，用水体提取工具识别 46f4a36d107b 里的飞机，先这样 |
| 524 | heldout_neg_negation_174 | none | - | 1图 | main | 在吗？想请教下，我现在不需要你跑 水体提取，只想听原理 越快越好 |
| 525 | heldout_neg_concept_175 | none | - | 1图 | main | 麻烦了，为什么大家都用 NBR，优缺点呢，拜托拜托 |
| 526 | heldout_neg_missing_id_176 | call | calculate_ndvi | 1图 | main | 对了，对刚才传的那个直接做 NDVI，拜托拜托 |
| 527 | heldout_neg_non_owner_177 | none | - | 0图+他1 | main | 嗨，那个，影像 d0fb68374c05 帮我算个 NDVI，先这样 |
| 528 | heldout_neg_general_178 | none | - | 0图 | main | 嗨，那个，推荐几本科幻小说 越快越好 |
| 529 | heldout_neg_contradiction_179 | none | - | 1图 | main | 用 NDVI 这个算法看看 b030dee60f4b 里有几条船 谢谢啦 |
| 530 | heldout_neg_negation_180 | none | - | 0图 | main | 麻烦了，先不要执行 NDVI，说说它适合什么场景，今天要 |
| 531 | heldout_neg_concept_181 | none | - | 1图 | main | 麻烦了，近红外波段 在遥感里到底意味着什么，拜托拜托 |
| 532 | heldout_neg_missing_id_182 | none | - | 0图 | main | 处理一下我那张图的 地物分割 麻烦尽快 |
| 533 | heldout_neg_non_owner_183 | none | - | 0图+他1 | main | 对了，99691a5beffe，任务是NDVI，开始吧，拜托拜托 |
| 534 | heldout_neg_general_184 | none | - | 0图 | main | 在吗？想请教下，讲讲什么是过拟合 越快越好 |
| 535 | heldout_neg_contradiction_185 | none | - | 1图 | main | 对了，拿云掩膜工具把文档 d08748d3-4d54-6727-c2d2-41ef4fe05c9b 总结一下，先这样 |
| 536 | heldout_neg_negation_186 | none | - | 1图 | main | 先不要执行 云掩膜，说说它适合什么场景，拜托拜托 |
| 537 | heldout_neg_concept_187 | none | - | 1图 | main | 辛苦帮个忙，为什么大家都用 云阴影，优缺点呢，先这样 |
| 538 | heldout_neg_missing_id_188 | none | - | 3图 | main | 辛苦帮个忙，对刚才传的那个直接做 地物分割 谢谢啦 |
| 539 | heldout_neg_non_owner_189 | none | - | 0图+他1 | main | 辛苦帮个忙，麻烦处理 7e9027257d7b 的NDVI 麻烦尽快 |
| 540 | heldout_neg_general_190 | none | - | 0图 | main | 嗨，那个，讲讲什么是过拟合，先这样 |
| 541 | heldout_neg_contradiction_191 | none | - | 1图 | main | 嗨，那个，拿波段合成功能翻译文档 356f93a1-42af-eef7-ef74-85a2edf89c4e |
| 542 | heldout_neg_negation_192 | none | - | 0图 | main | 先不要执行 水体提取，说说它适合什么场景 |
| 543 | heldout_neg_concept_193 | none | - | 1图 | main | 辛苦帮个忙，想了解下 云阴影 这个概念，别给我跑数据 谢谢啦 |
| 544 | heldout_neg_missing_id_194 | none | - | 0图 | main | 在吗？想请教下，上面那景影像帮我跑 水体掩膜，对了我还没给你 ID 越快越好 |
| 545 | heldout_neg_non_owner_195 | none | - | 0图+他1 | main | 影像 cc74e5dea828 帮我算个 NDVI 谢谢啦 |
| 546 | heldout_neg_general_196 | none | - | 0图 | main | 嗨，那个，推荐几本科幻小说 麻烦尽快 |
| 547 | heldout_neg_contradiction_197 | none | - | 1图 | main | 麻烦了，拿波段合成功能翻译文档 ddeb8d93-e66f-e900-6f24-679b400a790c 麻烦尽快 |
| 548 | heldout_neg_negation_198 | none | - | 1图 | main | 辛苦帮个忙，我现在不需要你跑 目标检测，只想听原理 越快越好 |
| 549 | heldout_neg_concept_199 | none | - | 1图 | main | 嗨，那个，假彩色 的取值范围一般是多少，怎么解读，今天要 |
| 550 | heldout_neg_missing_id_200 | call | segment_landcover | 1图 | main | 在吗？想请教下，那张图的 地物分割 安排一下，拜托拜托 |
| 551 | heldout_neg_non_owner_201 | none | - | 0图+他1 | main | 对了，d7f2e97fd293，任务是地物分割，开始吧 谢谢啦 |
| 552 | heldout_neg_general_202 | none | - | 0图 | main | 对了，帮我润色一段答辩稿 麻烦尽快 |
| 553 | heldout_neg_contradiction_203 | none | - | 1图 | main | 麻烦了，靠重投影功能数一数 b637b3f8d334 里的车 麻烦尽快 |
| 554 | heldout_neg_negation_204 | none | - | 0图 | main | 麻烦了，不用调用什么工具，云掩膜 的思路给我讲讲，今天要 |
| 555 | heldout_neg_concept_205 | none | - | 1图 | main | 辛苦帮个忙，近红外波段 的取值范围一般是多少，怎么解读，今天要 |
| 556 | heldout_neg_missing_id_206 | none | - | 0图 | main | 在吗？想请教下，上面那景影像帮我跑 地物分割，对了我还没给你 ID，今天要 |
| 557 | heldout_neg_non_owner_207 | none | - | 0图+他1 | main | 01e4943d7a7d 这景做一下 重投影 |
| 558 | heldout_neg_general_208 | none | - | 0图 | main | 辛苦帮个忙，用 python 写个二分查找，先这样 |
| 559 | heldout_neg_contradiction_209 | none | - | 1图 | main | 辛苦帮个忙，用 OCR 帮我判断 9157f297bd23 的植被覆盖多少，拜托拜托 |
| 560 | heldout_neg_negation_210 | none | - | 1图 | main | 麻烦了，我现在不需要你跑 地物分割，只想听原理，今天要 |
| 561 | heldout_neg_concept_211 | none | - | 1图 | main | 科普一下 NBR 呗，今天要 |
| 562 | heldout_neg_missing_id_212 | none | - | 3图 | main | 那张图的 云检测 安排一下，拜托拜托 |
| 563 | heldout_neg_non_owner_213 | none | - | 0图+他1 | main | 辛苦帮个忙，954e3f8423d2 这景做一下 云检测，拜托拜托 |
| 564 | heldout_neg_general_214 | none | - | 0图 | main | 急用，把 land cover 翻译成中文 越快越好 |
| 565 | heldout_neg_contradiction_215 | none | - | 1图 | main | 用 OCR 帮我判断 19b7218063df 的植被覆盖多少 |
| 566 | heldout_neg_negation_216 | none | - | 0图 | main | 嗨，那个，先不要执行 水体提取，说说它适合什么场景 越快越好 |
| 567 | heldout_neg_concept_217 | none | - | 1图 | main | 对了，想了解下 近红外波段 这个概念，别给我跑数据，今天要 |
| 568 | heldout_neg_missing_id_218 | none | - | 0图 | main | 上面那景影像帮我跑 云检测，对了我还没给你 ID 谢谢啦 |
| 569 | heldout_neg_non_owner_219 | none | - | 0图+他1 | main | 急用，b2291fc845f7，任务是水体掩膜，开始吧，先这样 |
| 570 | heldout_neg_general_220 | none | - | 0图 | main | 麻烦了，推荐几本科幻小说 麻烦尽快 |
| 571 | heldout_neg_contradiction_221 | none | - | 1图 | main | 对了，用水体提取工具识别 05a0af2709c9 里的飞机 谢谢啦 |
| 572 | heldout_neg_negation_222 | none | - | 1图 | main | 嗨，那个，不用调用什么工具，地物分割 的思路给我讲讲，先这样 |
| 573 | heldout_neg_concept_223 | none | - | 1图 | main | 对了，为什么大家都用 假彩色，优缺点呢，先这样 |
| 574 | heldout_neg_missing_id_224 | call | cloud_shadow_mask | 1图 | main | 那张图的 云检测 安排一下，先这样 |
| 575 | heldout_neg_non_owner_225 | none | - | 0图+他1 | main | 麻烦了，b5647f3ab968，任务是NDVI，开始吧，拜托拜托 |
| 576 | heldout_neg_general_226 | none | - | 0图 | main | 对了，给我写段项目周报开头，拜托拜托 |
| 577 | heldout_neg_contradiction_227 | none | - | 1图 | main | 对了，拿云掩膜工具把文档 53d84abf-a208-0448-b9b2-139cc2979298 总结一下 越快越好 |
| 578 | heldout_neg_negation_228 | none | - | 0图 | main | 麻烦了，停，NDVI 这步先不做，原理是什么 谢谢啦 |
| 579 | heldout_neg_concept_229 | none | - | 1图 | main | 想了解下 云阴影 这个概念，别给我跑数据，先这样 |
| 580 | heldout_neg_missing_id_230 | none | - | 0图 | main | 辛苦帮个忙，把刚说的那张图做个 地物分割，先这样 |
| 581 | heldout_neg_non_owner_231 | none | - | 0图+他1 | main | 嗨，那个，麻烦处理 71ff741441a4 的云检测 |
| 582 | heldout_neg_general_232 | none | - | 0图 | main | 对了，算下 3721 加 8964 等于几 谢谢啦 |
| 583 | heldout_neg_contradiction_233 | none | - | 1图 | main | 麻烦了，拿波段合成功能翻译文档 9c7c64d8-2efb-709e-6137-d73f1993ea4c 谢谢啦 |
| 584 | heldout_neg_negation_234 | none | - | 1图 | main | 嗨，那个，NDVI 别处理，解释清楚概念就行，先这样 |
| 585 | heldout_neg_concept_235 | none | - | 1图 | main | 云阴影 在遥感里到底意味着什么 越快越好 |
| 586 | heldout_neg_missing_id_236 | none | - | 3图 | main | 嗨，那个，就这张图，跑 NDVI 麻烦尽快 |
| 587 | heldout_neg_non_owner_237 | none | - | 0图+他1 | main | 用 a2aefca86213 跑 NDVI |
| 588 | heldout_neg_general_238 | none | - | 0图 | main | 辛苦帮个忙，算下 3721 加 8964 等于几 |
| 589 | heldout_neg_contradiction_239 | none | - | 1图 | main | 在吗？想请教下，用 NDVI 这个算法看看 bec03af4ca31 里有几条船，先这样 |
| 590 | heldout_neg_negation_240 | none | - | 0图 | main | 停，NDVI 这步先不做，原理是什么 谢谢啦 |
| 591 | heldout_neg_concept_241 | none | - | 1图 | main | 急用，为什么大家都用 假彩色，优缺点呢，先这样 |
| 592 | heldout_neg_missing_id_242 | none | - | 0图 | main | 急用，把刚说的那张图做个 地物分割 麻烦尽快 |
| 593 | heldout_neg_non_owner_243 | none | - | 0图+他1 | main | 对了，用 db69ee400e5f 跑 NDVI 麻烦尽快 |
| 594 | heldout_neg_general_244 | none | - | 0图 | main | 在吗？想请教下，把 land cover 翻译成中文 越快越好 |
| 595 | heldout_neg_contradiction_245 | none | - | 1图 | main | 在吗？想请教下，用 NDVI 这个算法看看 de6fe7aa2b0e 里有几条船 |
| 596 | heldout_neg_negation_246 | none | - | 1图 | main | 嗨，那个，不用调用什么工具，云掩膜 的思路给我讲讲 麻烦尽快 |
| 597 | heldout_neg_concept_247 | none | - | 1图 | main | 在吗？想请教下，科普一下 假彩色 呗 麻烦尽快 |
| 598 | heldout_neg_missing_id_248 | call | segment_landcover | 1图 | main | 急用，对刚才传的那个直接做 地物分割，拜托拜托 |
| 599 | heldout_neg_non_owner_249 | none | - | 0图+他1 | main | 辛苦帮个忙，麻烦处理 ed5f9af6d472 的重投影，今天要 |
| 600 | heldout_neg_general_250 | none | - | 0图 | main | 对了，推荐几本科幻小说 麻烦尽快 |
| 601 | heldout_neg_contradiction_251 | none | - | 1图 | main | 拿波段合成功能翻译文档 f7a5298d-a11b-7569-b5a1-0ae0573a3741 麻烦尽快 |
| 602 | heldout_neg_negation_252 | none | - | 0图 | main | 麻烦了，云掩膜 别处理，解释清楚概念就行，今天要 |
| 603 | heldout_neg_concept_253 | none | - | 1图 | main | 麻烦了，为什么大家都用 云阴影，优缺点呢 麻烦尽快 |
| 604 | heldout_neg_missing_id_254 | none | - | 0图 | main | 把刚说的那张图做个 地物分割，拜托拜托 |
| 605 | heldout_neg_non_owner_255 | none | - | 0图+他1 | main | 在吗？想请教下，e3d212caba0b 这景做一下 NDVI 越快越好 |
| 606 | heldout_neg_general_256 | none | - | 0图 | main | 辛苦帮个忙，帮我润色一段答辩稿，先这样 |
| 607 | heldout_neg_contradiction_257 | none | - | 1图 | main | 对了，靠重投影功能数一数 42ebe1d1594b 里的车 麻烦尽快 |
| 608 | heldout_neg_negation_258 | none | - | 1图 | main | 嗨，那个，NDVI 别处理，解释清楚概念就行 谢谢啦 |
| 609 | heldout_neg_concept_259 | none | - | 1图 | main | 对了，为什么大家都用 云阴影，优缺点呢，拜托拜托 |
| 610 | heldout_neg_missing_id_260 | none | - | 3图 | main | 急用，对刚才传的那个直接做 地物分割，今天要 |
| 611 | heldout_neg_non_owner_261 | none | - | 0图+他1 | main | 用 f78b22f4ca59 跑 水体掩膜，拜托拜托 |
| 612 | heldout_neg_general_262 | none | - | 0图 | main | 嗨，那个，把 land cover 翻译成中文 麻烦尽快 |
| 613 | heldout_neg_contradiction_263 | none | - | 1图 | main | 对了，拿云掩膜工具把文档 38de655e-9173-de40-6542-b18b12d3c4fc 总结一下，拜托拜托 |
| 614 | heldout_neg_negation_264 | none | - | 0图 | main | 辛苦帮个忙，先别动手算，就跟我讲讲 NDVI 是怎么回事 谢谢啦 |
| 615 | heldout_neg_concept_265 | none | - | 1图 | main | 麻烦了，假彩色 在遥感里到底意味着什么 越快越好 |
| 616 | heldout_neg_missing_id_266 | none | - | 0图 | main | 上面那景影像帮我跑 NDVI，对了我还没给你 ID 麻烦尽快 |
| 617 | heldout_neg_non_owner_267 | none | - | 0图+他1 | main | 急用，d5906d9a9bad，任务是水体掩膜，开始吧 越快越好 |
| 618 | heldout_neg_general_268 | none | - | 0图 | main | 对了，算下 3721 加 8964 等于几，先这样 |
| 619 | heldout_neg_contradiction_269 | none | - | 1图 | main | 对了，拿波段合成功能翻译文档 718fd1c0-8f6d-b8d5-7292-5070ecd952de，拜托拜托 |
| 620 | heldout_neg_negation_270 | none | - | 1图 | main | 不用调用什么工具，地物分割 的思路给我讲讲 谢谢啦 |
| 621 | heldout_neg_concept_271 | none | - | 1图 | main | NBR 的取值范围一般是多少，怎么解读 谢谢啦 |
| 622 | heldout_neg_missing_id_272 | call | segment_landcover | 1图 | main | 辛苦帮个忙，就这张图，跑 地物分割，拜托拜托 |
| 623 | heldout_neg_non_owner_273 | none | - | 0图+他1 | main | 嗨，那个，c860e337a206 这景做一下 地物分割，拜托拜托 |
| 624 | heldout_neg_general_274 | none | - | 0图 | main | 算下 3721 加 8964 等于几 谢谢啦 |
| 625 | heldout_neg_contradiction_275 | none | - | 1图 | main | 用水体提取工具识别 073cf2c6aab4 里的飞机，拜托拜托 |
| 626 | heldout_neg_negation_276 | none | - | 0图 | main | 麻烦了，先不要执行 NDVI，说说它适合什么场景 谢谢啦 |
| 627 | heldout_neg_concept_277 | none | - | 1图 | main | 在吗？想请教下，为什么大家都用 NBR，优缺点呢 越快越好 |
| 628 | heldout_neg_missing_id_278 | none | - | 0图 | main | 对了，上面那景影像帮我跑 云检测，对了我还没给你 ID 麻烦尽快 |
| 629 | heldout_neg_non_owner_279 | none | - | 0图+他1 | main | 麻烦了，影像 4202869c9fb5 帮我算个 NDVI 谢谢啦 |
| 630 | heldout_neg_general_280 | none | - | 0图 | main | 麻烦了，Excel 怎么做数据透视表，先这样 |
| 631 | heldout_neg_contradiction_281 | none | - | 1图 | main | 嗨，那个，拿波段合成功能翻译文档 4ce43f52-5aef-b2c0-f924-e21d17142530，先这样 |
| 632 | heldout_neg_negation_282 | none | - | 1图 | main | 麻烦了，目标检测 别处理，解释清楚概念就行 谢谢啦 |
| 633 | heldout_neg_concept_283 | none | - | 1图 | main | 对了，NDVI 和普通照片处理的区别是啥 谢谢啦 |
| 634 | heldout_neg_missing_id_284 | none | - | 3图 | main | 急用，就这张图，跑 地物分割 谢谢啦 |
| 635 | heldout_neg_non_owner_285 | none | - | 0图+他1 | main | 急用，用 2225e407e756 跑 水体掩膜 麻烦尽快 |
| 636 | heldout_neg_general_286 | none | - | 0图 | main | 在吗？想请教下，帮我润色一段答辩稿，先这样 |
| 637 | heldout_neg_contradiction_287 | none | - | 1图 | main | 麻烦了，拿云掩膜工具把文档 cfecb983-d524-5a11-2e1e-d175bbd7246f 总结一下 麻烦尽快 |
| 638 | heldout_neg_negation_288 | none | - | 0图 | main | 麻烦了，NDVI 别处理，解释清楚概念就行 麻烦尽快 |
| 639 | heldout_neg_concept_289 | none | - | 1图 | main | 急用，想了解下 假彩色 这个概念，别给我跑数据 |
| 640 | heldout_neg_missing_id_290 | none | - | 0图 | main | 麻烦了，把刚说的那张图做个 地物分割，先这样 |
| 641 | heldout_neg_non_owner_291 | none | - | 0图+他1 | main | 嗨，那个，麻烦处理 8700ab5cfa39 的NDVI，拜托拜托 |
| 642 | heldout_neg_general_292 | none | - | 0图 | main | 麻烦了，用 python 写个二分查找 麻烦尽快 |
| 643 | heldout_neg_contradiction_293 | none | - | 1图 | main | 急用，拿波段合成功能翻译文档 d8fdf870-21b3-2ea7-6396-6870dc6bc7f8 越快越好 |
| 644 | heldout_neg_negation_294 | none | - | 1图 | main | 辛苦帮个忙，地物分割 别处理，解释清楚概念就行，先这样 |
| 645 | heldout_neg_concept_295 | none | - | 1图 | main | 急用，NDVI 和普通照片处理的区别是啥 越快越好 |
| 646 | heldout_neg_missing_id_296 | call | cloud_shadow_mask | 1图 | main | 麻烦了，那张图的 云检测 安排一下 |
| 647 | heldout_neg_non_owner_297 | none | - | 0图+他1 | main | 对了，d2ef7e9c57de，任务是水体掩膜，开始吧，先这样 |
| 648 | heldout_neg_general_298 | none | - | 0图 | main | 对了，给我写段项目周报开头，先这样 |
| 649 | heldout_neg_contradiction_299 | none | - | 1图 | main | 嗨，那个，靠重投影功能数一数 85dd91275675 里的车，今天要 |
| 650 | heldout_bnd_ocr_not_detect_000 | call | ocr_recognize | 1图 | main | 嗨，那个，37f40078b842 上的文字给我读出来，不是让你找飞机 麻烦尽快 |
| 651 | heldout_bnd_detect_not_ocr_001 | call | detect_objects | 1图 | main | 急用，a8a9f1ad6c97 里把船找出来，我不要图上的文字，先这样 |
| 652 | heldout_bnd_water_not_index_002 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，把 d4d48a398f8f 的水体边界提出来，别只给 NDWI 数值 |
| 653 | heldout_bnd_index_not_water_003 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，aef0f525000d 算个 NDWI 就行，别做水域提取，先这样 |
| 654 | heldout_bnd_segment_not_detect_004 | call | segment_landcover | 1图 | main | 嗨，那个，bafb44af5b4a 我要地表分类图，别给我检侧结果 谢谢啦 |
| 655 | heldout_bnd_detect_not_segment_005 | call | detect_objects | 1图 | main | 麻烦了，只找 21b27bf942cd 里的船，不用整图分类，今天要 |
| 656 | heldout_bnd_parse_not_ocr_006 | call | parse_document | 0图 | main | 文档 d9680274-c3a2-c70a-dc3b-cd00997aea24 给我总结要点，不是图片认字，拜托拜托 |
| 657 | heldout_bnd_ocr_not_parse_007 | call | ocr_recognize | 1图 | main | 急用，这景 d7c6515eb272 的地图标注文字提取下，不是文档解析，今天要 |
| 658 | heldout_bnd_ocr_not_detect_008 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，ef391f92fa65 上的文字给我读出来，不是让你找飞机，拜托拜托 |
| 659 | heldout_bnd_detect_not_ocr_009 | call | detect_objects | 1图 | main | 急用，检测 f2334bdacb7c 的飞机位置，注记文字不用管 越快越好 |
| 660 | heldout_bnd_water_not_index_010 | call | extract_water_mask | 1图 | main | 提取 54d47933d825 实际的水面分布，不是指数计祘 麻烦尽快 |
| 661 | heldout_bnd_index_not_water_011 | call | calculate_spectral_index | 1图 | main | 急用，只要 f497bcff17ae 的 NDWI 指数，不用提取水体矢量 谢谢啦 |
| 662 | heldout_bnd_segment_not_detect_012 | call | segment_landcover | 1图 | main | 在吗？想请教下，c5aaa616fb01 整幅按地类分块，不是找单个目标，今天要 |
| 663 | heldout_bnd_detect_not_segment_013 | call | detect_objects | 1图 | main | 嗨，那个，e8acf453930c 检侧桥梁就好，地物分割先不做，拜托拜托 |
| 664 | heldout_bnd_parse_not_ocr_014 | call | parse_document | 0图 | main | 嗨，那个，文档 40c2f209-7146-1f60-62d0-e631e2837a8b 给我总结要点，不是图片认字，先这样 |
| 665 | heldout_bnd_ocr_not_parse_015 | call | ocr_recognize | 1图 | main | 急用，07e6b2fb803b 上的注记认出来就行，别走文挡总结，拜托拜托 |
| 666 | heldout_bnd_ocr_not_detect_016 | call | ocr_recognize | 1图 | main | 92984be4355d 上的文字给我读出来，不是让你找飞机 谢谢啦 |
| 667 | heldout_bnd_detect_not_ocr_017 | call | detect_objects | 1图 | main | 麻烦了，abd3b3eb3df5 找目标：车辆，别给我做 OCR 越快越好 |
| 668 | heldout_bnd_water_not_index_018 | call | extract_water_mask | 1图 | main | 嗨，那个，把 50fdfcaf1373 的水体边界提出来，别只给 NDWI 数值 越快越好 |
| 669 | heldout_bnd_index_not_water_019 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，给 1368f62f334f 出 NDWI 指数图，水体掩膜不需要 |
| 670 | heldout_bnd_segment_not_detect_020 | call | segment_landcover | 1图 | main | 急用，把 78e750009a24 的建筑植被水体分区，不是数飞机，拜托拜托 |
| 671 | heldout_bnd_detect_not_segment_021 | call | detect_objects | 1图 | main | 对了，b5e784c49fb1 找车，别跑分割，先这样 |
| 672 | heldout_bnd_parse_not_ocr_022 | call | parse_document | 0图 | main | 辛苦帮个忙，文档 a08842fb-045d-3758-f625-a1ccc9222cd3 给我总结要点，不是图片认字 谢谢啦 |
| 673 | heldout_bnd_ocr_not_parse_023 | call | ocr_recognize | 1图 | main | 在吗？想请教下，c913c6c8e8c1 上的注记认出来就行，别走文档总结，今天要 |
| 674 | heldout_bnd_ocr_not_detect_024 | call | ocr_recognize | 1图 | main | 麻烦了，0484e934817b 这图我只关心上面写了啥字，目标别管，先这样 |
| 675 | heldout_bnd_detect_not_ocr_025 | call | detect_objects | 1图 | main | 在吗？想请教下，ecd016457544 找目标：车辆，别给我做 OCR，今天要 |
| 676 | heldout_bnd_water_not_index_026 | call | extract_water_mask | 1图 | main | 在吗？想请教下，1086326223a8 圈水域，要掩模结果不要指数图 |
| 677 | heldout_bnd_index_not_water_027 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，只要 a277628b5209 的 NDWI 指数，不用提取水体矢量 谢谢啦 |
| 678 | heldout_bnd_segment_not_detect_028 | call | segment_landcover | 1图 | main | 对了，对 1e75c6bef8c7 做整图地物分割，不要目标框 谢谢啦 |
| 679 | heldout_bnd_detect_not_segment_029 | call | detect_objects | 1图 | main | 0b17540d70ce 检测桥梁就好，地物分割先不做，今天要 |
| 680 | heldout_bnd_parse_not_ocr_030 | call | parse_document | 0图 | main | 嗨，那个，文档 b5905ef5-209e-9f48-15ce-01e055d5ad1f 给我总结要点，不是图片认字，拜托拜托 |
| 681 | heldout_bnd_ocr_not_parse_031 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，识别 e214dd80cf70 图面文字，我没有要传 PDF 越快越好 |
| 682 | heldout_bnd_ocr_not_detect_032 | call | ocr_recognize | 1图 | main | 急用，5004bff195f9 上的文字给我读出来，不是让你找飞机，先这样 |
| 683 | heldout_bnd_detect_not_ocr_033 | call | detect_objects | 1图 | main | 对了，dbd8821a051e 找目标：车辆，别给我做 OCR |
| 684 | heldout_bnd_water_not_index_034 | call | extract_water_mask | 1图 | main | 急用，我要 3b0a035ec5cb 水域的范围掩膜，不是算什么指数，拜托拜托 |
| 685 | heldout_bnd_index_not_water_035 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，只要 f3ee58374692 的 NDWI 指数，不用提取水体矢量，今天要 |
| 686 | heldout_bnd_segment_not_detect_036 | call | segment_landcover | 1图 | main | 辛苦帮个忙，3a18d512f109 整幅按地类分块，不是找单个目标 麻烦尽快 |
| 687 | heldout_bnd_detect_not_segment_037 | call | detect_objects | 1图 | main | 急用，只找 abc6dd1273df 里的船，不用整图分类 越快越好 |
| 688 | heldout_bnd_parse_not_ocr_038 | call | parse_document | 0图 | main | 对了，9343d12c-e2a3-690f-0001-d3f8677471ec 是个 PDF，提炼内容，不用 OCR 影像，拜托拜托 |
| 689 | heldout_bnd_ocr_not_parse_039 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，c17ee0e77815 上的注记认出来就行，别走文档总结，今天要 |
| 690 | heldout_bnd_ocr_not_detect_040 | call | ocr_recognize | 1图 | main | 对了，9bac70cdb8d2 这图我只关心上面写了啥字，目标别管 |
| 691 | heldout_bnd_detect_not_ocr_041 | call | detect_objects | 1图 | main | 在吗？想请教下，e3b95be1623c 里把船找出来，我不要图上的文字，先这样 |
| 692 | heldout_bnd_water_not_index_042 | call | extract_water_mask | 1图 | main | 对了，f3642a43fa44 圈水域，要掩膜结果不要指数图 |
| 693 | heldout_bnd_index_not_water_043 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，076d77020513 算个 NDWI 就行，别做水域提取，拜托拜托 |
| 694 | heldout_bnd_segment_not_detect_044 | call | segment_landcover | 1图 | main | 辛苦帮个忙，把 6ba9eceb6ca8 的建筑植被水体分区，不是数飞机，拜托拜托 |
| 695 | heldout_bnd_detect_not_segment_045 | call | detect_objects | 1图 | main | 对了，201cff090bdf 检测桥梁就好，地物分割先不做 越快越好 |
| 696 | heldout_bnd_parse_not_ocr_046 | call | parse_document | 0图 | main | 在吗？想请教下，f59077c4-b435-6abb-1d03-3f5ce200ab37 是个 PDF，提炼内容，不用 OCR 影像，今天要 |
| 697 | heldout_bnd_ocr_not_parse_047 | call | ocr_recognize | 1图 | main | 在吗？想请教下，a6a404c0d456 是张扫描地图，读上面的字，不是解析什么文档 越快越好 |
| 698 | heldout_bnd_ocr_not_detect_048 | call | ocr_recognize | 1图 | main | 我要 996a50ee3357 的图面注记内容，别做目标检测 |
| 699 | heldout_bnd_detect_not_ocr_049 | call | detect_objects | 1图 | main | 嗨，那个，1afe092282cf 里把船找出来，我不要图上的文字 麻烦尽快 |
| 700 | heldout_bnd_water_not_index_050 | call | extract_water_mask | 1图 | main | 在吗？想请教下，提取 e0e29d358838 实际的水面分布，不是指数计算 麻烦尽快 |
| 701 | heldout_bnd_index_not_water_051 | call | calculate_spectral_index | 1图 | main | 嗨，那个，8a996a9f02fc 算个 NDWI 就行，别做水域提取，先这样 |
| 702 | heldout_bnd_segment_not_detect_052 | call | segment_landcover | 1图 | main | 对了，对 82f1fdc757f1 做整图地物分割，不要目标框 谢谢啦 |
| 703 | heldout_bnd_detect_not_segment_053 | call | detect_objects | 1图 | main | 在吗？想请教下，定位 199a24992bce 中的飞机，不需要 landcover 谢谢啦 |
| 704 | heldout_bnd_parse_not_ocr_054 | call | parse_document | 0图 | main | 在吗？想请教下，文档 d7504a20-54e9-9f6f-ef55-76ed1f720b4e 给我总结要点，不是图片认字 |
| 705 | heldout_bnd_ocr_not_parse_055 | call | ocr_recognize | 1图 | main | 在吗？想请教下，识别 1667a70299fe 图面文字，我没有要传 PDF 谢谢啦 |
| 706 | heldout_bnd_ocr_not_detect_056 | call | ocr_recognize | 1图 | main | 认字！0119197b744d 里印的地名，不是检测车辆，先这样 |
| 707 | heldout_bnd_detect_not_ocr_057 | call | detect_objects | 1图 | main | 麻烦了，框出 1c0470357ce2 中的油罐，文字识别就免了，先这样 |
| 708 | heldout_bnd_water_not_index_058 | call | extract_water_mask | 1图 | main | 麻烦了，21ce66597ab0 圈水域，要掩膜结果不要指数图 |
| 709 | heldout_bnd_index_not_water_059 | call | calculate_spectral_index | 1图 | main | 对了，c403cbe69918 算个 NDWI 就行，别做水域提取，拜托拜托 |
| 710 | heldout_bnd_segment_not_detect_060 | call | segment_landcover | 1图 | main | 把 cbee2646140a 的建筑植被水体分区，不是数飞机 谢谢啦 |
| 711 | heldout_bnd_detect_not_segment_061 | call | detect_objects | 1图 | main | 麻烦了，896c3e871c4e 检测桥梁就好，地物分割先不做 越快越好 |
| 712 | heldout_bnd_parse_not_ocr_062 | call | parse_document | 0图 | main | 5c9400a4-c22e-2a27-8ec4-93534e18acb9 是个 PDF，提炼内容，不用 OCR 影像 谢谢啦 |
| 713 | heldout_bnd_ocr_not_parse_063 | call | ocr_recognize | 1图 | main | 麻烦了，c26adb5b917b 是张扫描地图，读上面的字，不是解析什么文档 麻烦尽快 |
| 714 | heldout_bnd_ocr_not_detect_064 | call | ocr_recognize | 1图 | main | 急用，e4cd113d1728 这图我只关心上面写了啥字，目标别管 麻烦尽快 |
| 715 | heldout_bnd_detect_not_ocr_065 | call | detect_objects | 1图 | main | 在吗？想请教下，框出 58e8233a9dfd 中的油罐，文字识别就免了 越快越好 |
| 716 | heldout_bnd_water_not_index_066 | call | extract_water_mask | 1图 | main | 麻烦了，118636201040 圈水域，要掩膜结果不要指数图，先这样 |
| 717 | heldout_bnd_index_not_water_067 | call | calculate_spectral_index | 1图 | main | 麻烦了，给 76e9209f6c64 出 NDWI 指数图，水体掩膜不需要，今天要 |
| 718 | heldout_bnd_segment_not_detect_068 | call | segment_landcover | 1图 | main | 在吗？想请教下，把 ac6fa631d9af 的建筑植被水体分区，不是数飞机 |
| 719 | heldout_bnd_detect_not_segment_069 | call | detect_objects | 1图 | main | 在吗？想请教下，只找 49980c047962 里的船，不用整图分类，今天要 |
| 720 | heldout_bnd_parse_not_ocr_070 | call | parse_document | 0图 | main | 嗨，那个，帮我梳理文档 034357b5-8ef7-bea2-d6c1-8f40f7de85f6 的结构，这不是扫描图识字 谢谢啦 |
| 721 | heldout_bnd_ocr_not_parse_071 | call | ocr_recognize | 1图 | main | 嗨，那个，38e37a7517ce 上的注记认出来就行，别走文档总结 |
| 722 | heldout_bnd_ocr_not_detect_072 | call | ocr_recognize | 1图 | main | 急用，我要 7634eff5aeea 的图面注记内容，别做目标检测，先这样 |
| 723 | heldout_bnd_detect_not_ocr_073 | call | detect_objects | 1图 | main | 麻烦了，c62b20d3ab2a 里把船找出来，我不要图上的文字，今天要 |
| 724 | heldout_bnd_water_not_index_074 | call | extract_water_mask | 1图 | main | 在吗？想请教下，我要 bbe41c745cdc 水域的范围掩膜，不是算什么指数，先这样 |
| 725 | heldout_bnd_index_not_water_075 | call | calculate_spectral_index | 1图 | main | 对了，只要 0f05f82d3549 的 NDWI 指数，不用提取水体矢量 麻烦尽快 |
| 726 | heldout_bnd_segment_not_detect_076 | call | segment_landcover | 1图 | main | 4e81a0762cc4 我要地表分类图，别给我检测结果 |
| 727 | heldout_bnd_detect_not_segment_077 | call | detect_objects | 1图 | main | 定位 856f1ee66224 中的飞机，不需要 landcover 越快越好 |
| 728 | heldout_bnd_parse_not_ocr_078 | call | parse_document | 0图 | main | 在吗？想请教下，帮我梳理文档 9b7a5512-4348-ebb9-1049-7d7695e4e94a 的结构，这不是扫描图识字 |
| 729 | heldout_bnd_ocr_not_parse_079 | call | ocr_recognize | 1图 | main | 急用，这景 b0cc2eb85c9a 的地图标注文字提取下，不是文档解析 谢谢啦 |
| 730 | heldout_bnd_ocr_not_detect_080 | call | ocr_recognize | 1图 | main | 嗨，那个，7d0d467be7d7 上的文字给我读出来，不是让你找飞机 谢谢啦 |
| 731 | heldout_bnd_detect_not_ocr_081 | call | detect_objects | 1图 | main | 框出 e265cd5a577a 中的油罐，文字识别就免了，拜托拜托 |
| 732 | heldout_bnd_water_not_index_082 | call | extract_water_mask | 1图 | main | 急用，我要 d5fa102a6988 水域的范围掩膜，不是算什么指数，拜托拜托 |
| 733 | heldout_bnd_index_not_water_083 | call | calculate_spectral_index | 1图 | main | 嗨，那个，给 02309e2e09a9 出 NDWI 指数图，水体掩膜不需要 谢谢啦 |
| 734 | heldout_bnd_segment_not_detect_084 | call | segment_landcover | 1图 | main | 辛苦帮个忙，把 3e9d3163c434 的建筑植被水体分区，不是数飞机 越快越好 |
| 735 | heldout_bnd_detect_not_segment_085 | call | detect_objects | 1图 | main | 在吗？想请教下，ebf950c6ca88 找车，别跑分割 |
| 736 | heldout_bnd_parse_not_ocr_086 | call | parse_document | 0图 | main | 在吗？想请教下，d8a3f73a-f9d2-d233-02a7-1eb4e55b512e 文档解析走起，要章节摘要 越快越好 |
| 737 | heldout_bnd_ocr_not_parse_087 | call | ocr_recognize | 1图 | main | 麻烦了，这景 76ed6e1a2553 的地图标注文字提取下，不是文档解析 越快越好 |
| 738 | heldout_bnd_ocr_not_detect_088 | call | ocr_recognize | 1图 | main | 急用，我要 de275170a2ba 的图面注记内容，别做目标检测，拜托拜托 |
| 739 | heldout_bnd_detect_not_ocr_089 | call | detect_objects | 1图 | main | 对了，框出 2d5d2a014ee0 中的油罐，文字识别就免了，今天要 |
| 740 | heldout_bnd_water_not_index_090 | call | extract_water_mask | 1图 | main | 急用，我要 b60581c4634a 水域的范围掩膜，不是算什么指数 麻烦尽快 |
| 741 | heldout_bnd_index_not_water_091 | call | calculate_spectral_index | 1图 | main | 急用，521bd1eaa777 我要的是水体指数分布，不是范围圈定，拜托拜托 |
| 742 | heldout_bnd_segment_not_detect_092 | call | segment_landcover | 1图 | main | f8646cf937c5 我要地表分类图，别给我检测结果 麻烦尽快 |
| 743 | heldout_bnd_detect_not_segment_093 | call | detect_objects | 1图 | main | 麻烦了，定位 1dd20d90c4b2 中的飞机，不需要 landcover 谢谢啦 |
| 744 | heldout_bnd_parse_not_ocr_094 | call | parse_document | 0图 | main | 帮我梳理文档 028744eb-d0bd-b5e9-615c-64760f306ef0 的结构，这不是扫描图识字，今天要 |
| 745 | heldout_bnd_ocr_not_parse_095 | call | ocr_recognize | 1图 | main | 嗨，那个，8b73ab7f86c0 上的注记认出来就行，别走文档总结 麻烦尽快 |
| 746 | heldout_bnd_ocr_not_detect_096 | call | ocr_recognize | 1图 | main | 嗨，那个，d160ade33178 这图我只关心上面写了啥字，目标别管 麻烦尽快 |
| 747 | heldout_bnd_detect_not_ocr_097 | call | detect_objects | 1图 | main | 嗨，那个，99ad5123a913 里把船找出来，我不要图上的文字 麻烦尽快 |
| 748 | heldout_bnd_water_not_index_098 | call | extract_water_mask | 1图 | main | 对了，把 7a6f5a8bde64 的水体边界提出来，别只给 NDWI 数值，今天要 |
| 749 | heldout_bnd_index_not_water_099 | call | calculate_spectral_index | 1图 | main | 嗨，那个，3d22d3dea8fd 算个 NDWI 就行，别做水域提取 谢谢啦 |
| 750 | heldout_bnd_segment_not_detect_100 | call | segment_landcover | 1图 | main | 急用，1f455ce37d56 整幅按地类分块，不是找单个目标 越快越好 |
| 751 | heldout_bnd_detect_not_segment_101 | call | detect_objects | 1图 | main | 在吗？想请教下，bbc76268c6e1 找车，别跑分割 |
| 752 | heldout_bnd_parse_not_ocr_102 | call | parse_document | 0图 | main | 在吗？想请教下，2d34f11a-b2cb-7f59-ff3b-1a6b0613150f 是个 PDF，提炼内容，不用 OCR 影像，今天要 |
| 753 | heldout_bnd_ocr_not_parse_103 | call | ocr_recognize | 1图 | main | 在吗？想请教下，这景 e5b67eb24012 的地图标注文字提取下，不是文档解析 |
| 754 | heldout_bnd_ocr_not_detect_104 | call | ocr_recognize | 1图 | main | 麻烦了，52b5430da392 上的文字给我读出来，不是让你找飞机 越快越好 |
| 755 | heldout_bnd_detect_not_ocr_105 | call | detect_objects | 1图 | main | 麻烦了，检侧 9693f3795be6 的飞机位置，注记文字不用管 谢谢啦 |
| 756 | heldout_bnd_water_not_index_106 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，提取 4193c707e525 实际的水面分布，不是指数计算，今天要 |
| 757 | heldout_bnd_index_not_water_107 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，f4f4a29ac4df 算个 NDWI 就行，别做水域提取，今天要 |
| 758 | heldout_bnd_segment_not_detect_108 | call | segment_landcover | 1图 | main | 急用，对 6bfa8c114a18 做整图地物分割，不要目标框 麻烦尽快 |
| 759 | heldout_bnd_detect_not_segment_109 | call | detect_objects | 1图 | main | 在吗？想请教下，定位 6dd755b93d75 中的飞机，不需要 landcover 谢谢啦 |
| 760 | heldout_bnd_parse_not_ocr_110 | call | parse_document | 0图 | main | 对了，8a933d91-d07a-c43c-4045-e74e72b76e31 是个 PDF，提炼内容，不用 OCR 影像，拜托拜托 |
| 761 | heldout_bnd_ocr_not_parse_111 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，这景 06a63e6080ae 的地图标注文字提取下，不是文档解析 谢谢啦 |
| 762 | heldout_bnd_ocr_not_detect_112 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，d52c2c5f19db 上的文字给我读出来，不是让你找飞机 |
| 763 | heldout_bnd_detect_not_ocr_113 | call | detect_objects | 1图 | main | 急用，3fe7b2cd75a6 找目标：车辆，别给我做 OCR 谢谢啦 |
| 764 | heldout_bnd_water_not_index_114 | call | extract_water_mask | 1图 | main | 对了，把 a98361a00880 的水体边界提出来，别只给 NDWI 数值 麻烦尽快 |
| 765 | heldout_bnd_index_not_water_115 | call | calculate_spectral_index | 1图 | main | 7b895f45981c 算个 NDWI 就行，别做水域提取 麻烦尽快 |
| 766 | heldout_bnd_segment_not_detect_116 | call | segment_landcover | 1图 | main | 对 400f6a109a77 做整图地物分割，不要目标框 谢谢啦 |
| 767 | heldout_bnd_detect_not_segment_117 | call | detect_objects | 1图 | main | 嗨，那个，只找 c091655081b4 里的船，不用整图分类 谢谢啦 |
| 768 | heldout_bnd_parse_not_ocr_118 | call | parse_document | 0图 | main | 麻烦了，473f2521-a8b1-90c8-404d-239d65312128 是个 PDF，提炼内容，不用 OCR 影像，先这样 |
| 769 | heldout_bnd_ocr_not_parse_119 | call | ocr_recognize | 1图 | main | 在吗？想请教下，识别 32cbaed6b168 图面文字，我没有要传 PDF，拜托拜托 |
| 770 | heldout_bnd_ocr_not_detect_120 | call | ocr_recognize | 1图 | main | 急用，13d049f64827 这图我只关心上面写了啥字，目标别管 谢谢啦 |
| 771 | heldout_bnd_detect_not_ocr_121 | call | detect_objects | 1图 | main | 辛苦帮个忙，检测 b5a152471268 的飞机位置，注记文字不用管 麻烦尽快 |
| 772 | heldout_bnd_water_not_index_122 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，提取 95de56530aa9 实际的水面分布，不是指数计算，今天要 |
| 773 | heldout_bnd_index_not_water_123 | call | calculate_spectral_index | 1图 | main | 嗨，那个，给 ec5334e4f346 出 NDWI 指数图，水体掩膜不需要，先这样 |
| 774 | heldout_bnd_segment_not_detect_124 | call | segment_landcover | 1图 | main | 急用，对 81a50bf7c3d9 做整图地物分割，不要目标框 谢谢啦 |
| 775 | heldout_bnd_detect_not_segment_125 | call | detect_objects | 1图 | main | 对了，3ef54851d4f9 检测桥梁就好，地物分割先不做 越快越好 |
| 776 | heldout_bnd_parse_not_ocr_126 | call | parse_document | 0图 | main | 辛苦帮个忙，文挡 ad04daf9-9bdb-5252-f235-534912dbf766 给我总结要点，不是图片认字，先这样 |
| 777 | heldout_bnd_ocr_not_parse_127 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，这景 01bd3e0cb892 的地图标注文字提取下，不是文档解析 谢谢啦 |
| 778 | heldout_bnd_ocr_not_detect_128 | call | ocr_recognize | 1图 | main | 对了，认字！6e164f35d5de 里印的地名，不是检测车辆，先这样 |
| 779 | heldout_bnd_detect_not_ocr_129 | call | detect_objects | 1图 | main | 麻烦了，框出 44c8297f369e 中的油罐，文字识别就免了 |
| 780 | heldout_bnd_water_not_index_130 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，a565c3561caa 圈水域，要掩膜结果不要指数图 越快越好 |
| 781 | heldout_bnd_index_not_water_131 | call | calculate_spectral_index | 1图 | main | 麻烦了，de8ea8c8b8b4 算个 NDWI 就行，别做水域提取，今天要 |
| 782 | heldout_bnd_segment_not_detect_132 | call | segment_landcover | 1图 | main | efaa8936b417 整幅按地类分块，不是找单个目标 谢谢啦 |
| 783 | heldout_bnd_detect_not_segment_133 | call | detect_objects | 1图 | main | 在吗？想请教下，00b9259287a1 找车，别跑分割，先这样 |
| 784 | heldout_bnd_parse_not_ocr_134 | call | parse_document | 0图 | main | 对了，ccf7a6f2-0dd6-a027-1e30-599c0bf8cf70 文档解析走起，要章节摘要 |
| 785 | heldout_bnd_ocr_not_parse_135 | call | ocr_recognize | 1图 | main | 在吗？想请教下，a78d4843754f 上的注记认出来就行，别走文档总结 麻烦尽快 |
| 786 | heldout_bnd_ocr_not_detect_136 | call | ocr_recognize | 1图 | main | 嗨，那个，4feeacedc2f9 这图我只关心上面写了啥字，目标别管，拜托拜托 |
| 787 | heldout_bnd_detect_not_ocr_137 | call | detect_objects | 1图 | main | 对了，dca48a2b80a2 里把船找出来，我不要图上的文字，今天要 |
| 788 | heldout_bnd_water_not_index_138 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，提取 b28a178c5863 实际的水面分布，不是指数计算 谢谢啦 |
| 789 | heldout_bnd_index_not_water_139 | call | calculate_spectral_index | 1图 | main | 麻烦了，bbf45b496e37 算个 NDWI 就行，别做水域提取 越快越好 |
| 790 | heldout_bnd_segment_not_detect_140 | call | segment_landcover | 1图 | main | 在吗？想请教下，把 cf2a432d51ec 的建筑植被水体分区，不是数飞机 |
| 791 | heldout_bnd_detect_not_segment_141 | call | detect_objects | 1图 | main | 嗨，那个，定位 94ac16086d70 中的飞机，不需要 landcover，拜托拜托 |
| 792 | heldout_bnd_parse_not_ocr_142 | call | parse_document | 0图 | main | 急用，b2113168-091f-68ea-4a81-416d02fc0ec7 文档解析走起，要章节摘要，今天要 |
| 793 | heldout_bnd_ocr_not_parse_143 | call | ocr_recognize | 1图 | main | 这景 761ba5cd13fe 的地图标注文字提取下，不是文档解析 |
| 794 | heldout_bnd_ocr_not_detect_144 | call | ocr_recognize | 1图 | main | 在吗？想请教下，我要 255640d65ad3 的图面注记内容，别做目标检测 越快越好 |
| 795 | heldout_bnd_detect_not_ocr_145 | call | detect_objects | 1图 | main | 急用，399ce53692d9 里把船找出来，我不要图上的文字 麻烦尽快 |
| 796 | heldout_bnd_water_not_index_146 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，8fecd18819ba 圈水域，要掩膜结果不要指数图，拜托拜托 |
| 797 | heldout_bnd_index_not_water_147 | call | calculate_spectral_index | 1图 | main | 急用，c0a1b4c527f5 我要的是水体指数分布，不是范围圈定，先这样 |
| 798 | heldout_bnd_segment_not_detect_148 | call | segment_landcover | 1图 | main | 对了，9a8e89100db3 整幅按地类分块，不是找单个目标 |
| 799 | heldout_bnd_detect_not_segment_149 | call | detect_objects | 1图 | main | 麻烦了，只找 d2e2f9f9e1fa 里的船，不用整图分类 麻烦尽快 |
| 800 | heldout_bnd_parse_not_ocr_150 | call | parse_document | 0图 | main | 嗨，那个，文档 b9841c06-9339-83cc-2793-73d36a42521b 给我总结要点，不是图片认字，今天要 |
| 801 | heldout_bnd_ocr_not_parse_151 | call | ocr_recognize | 1图 | main | 在吗？想请教下，这景 76114d9986d7 的地图标注文字提取下，不是文档解析，拜托拜托 |
| 802 | heldout_bnd_ocr_not_detect_152 | call | ocr_recognize | 1图 | main | 对了，f6dcb99ad854 上的文字给我读出来，不是让你找飞机 麻烦尽快 |
| 803 | heldout_bnd_detect_not_ocr_153 | call | detect_objects | 1图 | main | 嗨，那个，检测 b1b36e6c871d 的飞机位置，注记文字不用管，今天要 |
| 804 | heldout_bnd_water_not_index_154 | call | extract_water_mask | 1图 | main | 嗨，那个，提取 785ef89d83b0 实际的水面分布，不是指数计算 |
| 805 | heldout_bnd_index_not_water_155 | call | calculate_spectral_index | 1图 | main | 麻烦了，给 7d7bc95077db 出 NDWI 指数图，水体掩模不需要 |
| 806 | heldout_bnd_segment_not_detect_156 | call | segment_landcover | 1图 | main | 辛苦帮个忙，对 04a317e39c4b 做整图地物分割，不要目标框 麻烦尽快 |
| 807 | heldout_bnd_detect_not_segment_157 | call | detect_objects | 1图 | main | 急用，b114b36e66d1 找车，别跑分割，先这样 |
| 808 | heldout_bnd_parse_not_ocr_158 | call | parse_document | 0图 | main | 在吗？想请教下，文档 c86625de-b5de-a389-9846-086a1a0dd75d 给我总结要点，不是图片认字 谢谢啦 |
| 809 | heldout_bnd_ocr_not_parse_159 | call | ocr_recognize | 1图 | main | 对了，9367dcc028ec 上的注记认出来就行，别走文档总结 麻烦尽快 |
| 810 | heldout_bnd_ocr_not_detect_160 | call | ocr_recognize | 1图 | main | 嗨，那个，认字！8f6fd72384b7 里印的地名，不是检测车辆 越快越好 |
| 811 | heldout_bnd_detect_not_ocr_161 | call | detect_objects | 1图 | main | 对了，1d4c37a49a05 找目标：车辆，别给我做 OCR 谢谢啦 |
| 812 | heldout_bnd_water_not_index_162 | call | extract_water_mask | 1图 | main | 麻烦了，5c20a7e268c4 圈水域，要掩膜结果不要指数图 越快越好 |
| 813 | heldout_bnd_index_not_water_163 | call | calculate_spectral_index | 1图 | main | 在吗？想请教下，只要 e1326a384fb4 的 NDWI 指数，不用提取水体矢量，今天要 |
| 814 | heldout_bnd_segment_not_detect_164 | call | segment_landcover | 1图 | main | 急用，9d43400b9379 整幅按地类分块，不是找单个目标，拜托拜托 |
| 815 | heldout_bnd_detect_not_segment_165 | call | detect_objects | 1图 | main | 辛苦帮个忙，05307f26fcf2 检测桥梁就好，地物分割先不做 |
| 816 | heldout_bnd_parse_not_ocr_166 | call | parse_document | 0图 | main | 对了，386694db-56af-b28d-3f5c-8f9b942de8e0 是个 PDF，提炼内容，不用 OCR 影象，拜托拜托 |
| 817 | heldout_bnd_ocr_not_parse_167 | call | ocr_recognize | 1图 | main | 急用，这景 3042bdf1d323 的地图标注文字提取下，不是文档解析，先这样 |
| 818 | heldout_bnd_ocr_not_detect_168 | call | ocr_recognize | 1图 | main | 对了，1743e3ccd92c 上的文字给我读出来，不是让你找飞机 谢谢啦 |
| 819 | heldout_bnd_detect_not_ocr_169 | call | detect_objects | 1图 | main | 在吗？想请教下，框出 207542c87c41 中的油罐，文字识别就免了 越快越好 |
| 820 | heldout_bnd_water_not_index_170 | call | extract_water_mask | 1图 | main | 麻烦了，提取 c7b49386f947 实际的水面分布，不是指数计算，先这样 |
| 821 | heldout_bnd_index_not_water_171 | call | calculate_spectral_index | 1图 | main | 急用，给 16eb58e20180 出 NDWI 指数图，水体掩膜不需要 越快越好 |
| 822 | heldout_bnd_segment_not_detect_172 | call | segment_landcover | 1图 | main | 辛苦帮个忙，把 4e42fed608c7 的建筑植被水体分区，不是数飞机，先这样 |
| 823 | heldout_bnd_detect_not_segment_173 | call | detect_objects | 1图 | main | 在吗？想请教下，定位 98f87a1a8c3a 中的飞机，不需要 landcover，先这样 |
| 824 | heldout_bnd_parse_not_ocr_174 | call | parse_document | 0图 | main | 嗨，那个，帮我梳理文档 bb07c1fc-9591-b9db-b3a5-50069e3c9b27 的结构，这不是扫描图识字，先这样 |
| 825 | heldout_bnd_ocr_not_parse_175 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，这景 c5501e34d9f3 的地图标注文字提取下，不是文档解析 越快越好 |
| 826 | heldout_bnd_ocr_not_detect_176 | call | ocr_recognize | 1图 | main | 嗨，那个，我要 8979c1bc842e 的图面注记内容，别做目标检测，今天要 |
| 827 | heldout_bnd_detect_not_ocr_177 | call | detect_objects | 1图 | main | d11e583a8d9f 里把船找出来，我不要图上的文字 谢谢啦 |
| 828 | heldout_bnd_water_not_index_178 | call | extract_water_mask | 1图 | main | 急用，我要 2a77b21d6e13 水域的范围掩膜，不是算什么指数 |
| 829 | heldout_bnd_index_not_water_179 | call | calculate_spectral_index | 1图 | main | 辛苦帮个忙，77c7c9284a9e 算个 NDWI 就行，别做水域提取 麻烦尽快 |
| 830 | heldout_bnd_segment_not_detect_180 | call | segment_landcover | 1图 | main | 3405f1a3d509 整幅按地类分块，不是找单个目标 谢谢啦 |
| 831 | heldout_bnd_detect_not_segment_181 | call | detect_objects | 1图 | main | 麻烦了，742644aef3bb 找车，别跑分割 |
| 832 | heldout_bnd_parse_not_ocr_182 | call | parse_document | 0图 | main | 麻烦了，640583ba-7445-38af-14c8-769f93015ddb 是个 PDF，提炼内容，不用 OCR 影像 麻烦尽快 |
| 833 | heldout_bnd_ocr_not_parse_183 | call | ocr_recognize | 1图 | main | 对了，这景 3a6b714230d9 的地图标注文字提取下，不是文挡解析，先这样 |
| 834 | heldout_bnd_ocr_not_detect_184 | call | ocr_recognize | 1图 | main | 麻烦了，我要 645fb2930321 的图面注记内容，别做目标检测，拜托拜托 |
| 835 | heldout_bnd_detect_not_ocr_185 | call | detect_objects | 1图 | main | 辛苦帮个忙，a21699446b59 里把船找出来，我不要图上的文字 麻烦尽快 |
| 836 | heldout_bnd_water_not_index_186 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，提取 476219c52237 实际的水面分布，不是指数计算，今天要 |
| 837 | heldout_bnd_index_not_water_187 | call | calculate_spectral_index | 1图 | main | 对了，只要 60cd77b0a159 的 NDWI 指数，不用提取水体矢量，先这样 |
| 838 | heldout_bnd_segment_not_detect_188 | call | segment_landcover | 1图 | main | 嗨，那个，把 ab499d971ca0 的建筑植被水体分区，不是数飞机，今天要 |
| 839 | heldout_bnd_detect_not_segment_189 | call | detect_objects | 1图 | main | 在吗？想请教下，定位 a4f459e4796a 中的飞机，不需要 landcover 谢谢啦 |
| 840 | heldout_bnd_parse_not_ocr_190 | call | parse_document | 0图 | main | 辛苦帮个忙，文档 75004f4d-6c3a-539a-55d1-5f4397936852 给我总结要点，不是图片认字，今天要 |
| 841 | heldout_bnd_ocr_not_parse_191 | call | ocr_recognize | 1图 | main | 麻烦了，17ebed56a6a8 是张扫描地图，读上面的字，不是解析什么文档 麻烦尽快 |
| 842 | heldout_bnd_ocr_not_detect_192 | call | ocr_recognize | 1图 | main | 辛苦帮个忙，ec69b1acc8fe 上的文字给我读出来，不是让你找飞机，今天要 |
| 843 | heldout_bnd_detect_not_ocr_193 | call | detect_objects | 1图 | main | 对了，检测 a6ec61ecd98e 的飞机位置，注记文字不用管，先这样 |
| 844 | heldout_bnd_water_not_index_194 | call | extract_water_mask | 1图 | main | 辛苦帮个忙，我要 cde7df860333 水域的范围掩膜，不是算什么指数，今天要 |
| 845 | heldout_bnd_index_not_water_195 | call | calculate_spectral_index | 1图 | main | 急用，只要 fff5bc9b6721 的 NDWI 指数，不用提取水体矢量 麻烦尽快 |
| 846 | heldout_bnd_segment_not_detect_196 | call | segment_landcover | 1图 | main | 嗨，那个，对 4dc7bec88e40 做整图地物分割，不要目标框，拜托拜托 |
| 847 | heldout_bnd_detect_not_segment_197 | call | detect_objects | 1图 | main | 辛苦帮个忙，只找 110acf206045 里的船，不用整图分类，今天要 |
| 848 | heldout_bnd_parse_not_ocr_198 | call | parse_document | 0图 | main | 在吗？想请教下，帮我梳理文档 97415d04-f303-9012-096a-2b8a43da3714 的结构，这不是扫描图识字，先这样 |
| 849 | heldout_bnd_ocr_not_parse_199 | call | ocr_recognize | 1图 | main | 麻烦了，这景 86a2fc110f66 的地图标注文字提取下，不是文档解析，先这样 |
| 850 | heldout_cmp_web_000 | call | web_search | 0图 | main | 辛苦帮个忙，帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接，今天要 |
| 851 | heldout_cmp_web_001 | call | web_search | 0图 | main | 明天去南京出差，天气怎样？再查下高铁晚点情况 越快越好 |
| 852 | heldout_cmp_web_002 | call | web_search | 0图 | main | 麻烦了，看下这周末上海限行规定，以及天气适不适合外拍 越快越好 |
| 853 | heldout_cmp_web_003 | call | web_search | 0图 | main | 对了，明天去南京出差，天气怎样？再查下高铁晚点情况 |
| 854 | heldout_cmp_web_004 | call | web_search | 0图 | main | 麻烦了，看下这周末上海限行规定，以及天气适不适合外拍，拜托拜托 |
| 855 | heldout_cmp_web_005 | call | web_search | 0图 | main | 下周末杭州天气怎么样，再帮我查下当地民宿价格行情，先这样 |
| 856 | heldout_cmp_web_006 | call | web_search | 0图 | main | 看下这周末上海限行规定，以及天气适不适合外拍，先这样 |
| 857 | heldout_cmp_web_007 | call | web_search | 0图 | main | 急用，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格，拜托拜托 |
| 858 | heldout_cmp_web_008 | call | web_search | 0图 | main | 搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格 谢谢啦 |
| 859 | heldout_cmp_web_009 | call | web_search | 0图 | main | 麻烦了，明天去南京出差，天气怎样？再查下高铁晚点情况，拜托拜托 |
| 860 | heldout_cmp_web_010 | call | web_search | 0图 | main | 对了，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格，先这样 |
| 861 | heldout_cmp_web_011 | call | web_search | 0图 | main | 嗨，那个，帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接 越快越好 |
| 862 | heldout_cmp_web_012 | call | web_search | 0图 | main | 明天去南京出差，天气怎样？再查下高铁晚点情况，先这样 |
| 863 | heldout_cmp_web_013 | call | web_search | 0图 | main | 在吗？想请教下，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格 谢谢啦 |
| 864 | heldout_cmp_web_014 | call | web_search | 0图 | main | 在吗？想请教下，看下这周末上海限行规定，以及天气适不适合外拍，拜托拜托 |
| 865 | heldout_cmp_web_015 | call | web_search | 0图 | main | 嗨，那个，明天去南京出差，天气怎样？再查下高铁晚点情况 越快越好 |
| 866 | heldout_cmp_web_016 | call | web_search | 0图 | main | 辛苦帮个忙，帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接 麻烦尽快 |
| 867 | heldout_cmp_web_017 | call | web_search | 0图 | main | 急用，下周末杭州天气怎么样，再帮我查下当地民宿价格行情 谢谢啦 |
| 868 | heldout_cmp_web_018 | call | web_search | 0图 | main | 看下这周末上海限行规定，以及天气适不适合外拍，今天要 |
| 869 | heldout_cmp_web_019 | call | web_search | 0图 | main | 在吗？想请教下，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格，拜托拜托 |
| 870 | heldout_cmp_web_020 | call | web_search | 0图 | main | 急用，帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接 |
| 871 | heldout_cmp_web_021 | call | web_search | 0图 | main | 对了，查一下最新的耕地保护政策，另外找几个高分辨率农业遥感公开数据集 越快越好 |
| 872 | heldout_cmp_web_022 | call | web_search | 0图 | main | 急用，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格 |
| 873 | heldout_cmp_web_023 | call | web_search | 0图 | main | 嗨，那个，下周末杭州天气怎么样，再帮我查下当地民宿价格行情，今天要 |
| 874 | heldout_cmp_web_024 | call | web_search | 0图 | main | 麻烦了，下周末杭州天气怎么样，再帮我查下当地民宿价格行情 |
| 875 | heldout_cmp_web_025 | call | web_search | 0图 | main | 嗨，那个，看下这周末上海限行规定，以及天气适不适合外拍，先这样 |
| 876 | heldout_cmp_web_026 | call | web_search | 0图 | main | 明天去南京出差，天气怎样？再查下高铁晚点情况 谢谢啦 |
| 877 | heldout_cmp_web_027 | call | web_search | 0图 | main | 麻烦了，帮我查现在卫星影像云服务的市场价，再找官方的产品文档链接 麻烦尽快 |
| 878 | heldout_cmp_web_028 | call | web_search | 0图 | main | 急用，下周末杭州天气怎么样，再帮我查下当地民宿价格行情，先这样 |
| 879 | heldout_cmp_web_029 | call | web_search | 0图 | main | 对了，明天去南京出差，天气怎样？再查下高铁晚点情况 谢谢啦 |
| 880 | heldout_cmp_web_030 | call | web_search | 0图 | main | 辛苦帮个忙，下周末杭州天气怎么样，再帮我查下当地民宿价格行情 麻烦尽快 |
| 881 | heldout_cmp_web_031 | call | web_search | 0图 | main | 对了，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格，今天要 |
| 882 | heldout_cmp_web_032 | call | web_search | 0图 | main | 在吗？想请教下，下周末杭州天气怎么样，再帮我查下当地民宿价格行情，拜托拜托 |
| 883 | heldout_cmp_multi_000 | none | - | 1图 | diagnostic_unsupported | 把 ade9c75cb70a 的云掩膜和水体掩膜一次性都做了 越快越好 |
| 884 | heldout_cmp_multi_001 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，把 0169b9fa7271 的云掩膜和水体掩膜一次性都做了 谢谢啦 |
| 885 | heldout_cmp_multi_002 | none | - | 1图 | diagnostic_unsupported | 在吗？想请教下，7c537594a05a 既要真彩色预览也要目标检测，一起出 越快越好 |
| 886 | heldout_cmp_multi_003 | none | - | 1图 | diagnostic_unsupported | 急用，686e6e93b0b7 重投影完顺手把船和飞机都检测了，先这样 |
| 887 | heldout_cmp_multi_004 | none | - | 1图 | diagnostic_unsupported | 麻烦了，1d9a5ba802b1 既要真彩色预览也要目标检测，一起出，拜托拜托 |
| 888 | heldout_cmp_multi_005 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，6b496a0e350c 帮我同时算 NDVI 又提水体 越快越好 |
| 889 | heldout_cmp_multi_006 | none | - | 1图 | diagnostic_unsupported | 在吗？想请教下，9df9982f6545 帮我同时算 NDVI 又提水体 越快越好 |
| 890 | heldout_cmp_multi_007 | none | - | 1图 | diagnostic_unsupported | 把 3fc44e047433 的云掩膜和水体掩膜一次性都做了 麻烦尽快 |
| 891 | heldout_cmp_multi_008 | none | - | 1图 | diagnostic_unsupported | 麻烦了，b7c300229a4f 既要真彩色预览也要目标检测，一起出 |
| 892 | heldout_cmp_multi_009 | none | - | 1图 | diagnostic_unsupported | 19934ace0d96 帮我同时算 NDVI 又提水体 麻烦尽快 |
| 893 | heldout_cmp_multi_010 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，先给 e7775f1027d0 去云再马上做地物分割 谢谢啦 |
| 894 | heldout_cmp_multi_011 | none | - | 1图 | diagnostic_unsupported | 急用，先给 cfdbee3fd6e4 去云再马上做地物分割，今天要 |
| 895 | heldout_cmp_multi_012 | none | - | 1图 | diagnostic_unsupported | 在吗？想请教下，ee29c04c1dbc 重投影完顺手把船和飞机都检测了 麻烦尽快 |
| 896 | heldout_cmp_multi_013 | none | - | 1图 | diagnostic_unsupported | 麻烦了，880be55b374e 既要真彩色预览也要目标检测，一起出，拜托拜托 |
| 897 | heldout_cmp_multi_014 | none | - | 1图 | diagnostic_unsupported | 急用，一口气把 201e39cea748 的文字读出来再算个 NBR，拜托拜托 |
| 898 | heldout_cmp_multi_015 | none | - | 1图 | diagnostic_unsupported | 麻烦了，把 400459e1db4c 的云掩膜和水体掩膜一次性都做了 |
| 899 | heldout_cmp_multi_016 | none | - | 1图 | diagnostic_unsupported | 对了，一口气把 d838ed60bc47 的文字读出来再算个 NBR 越快越好 |
| 900 | heldout_cmp_multi_017 | none | - | 1图 | diagnostic_unsupported | 急用，17f9db2537b5 先查元数据，接着直接分割，一条龙 |
| 901 | heldout_cmp_multi_018 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，5047908f3058 帮我同时算 NDVI 又提水体 |
| 902 | heldout_cmp_multi_019 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，fbda2df9e497 帮我同时算 NDVI 又提水体，今天要 |
| 903 | heldout_cmp_multi_020 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，先给 a662aa305f4b 去云再马上做地物分割 谢谢啦 |
| 904 | heldout_cmp_multi_021 | none | - | 1图 | diagnostic_unsupported | 急用，93b96cd6ef10 帮我同时算 NDVI 又提水体 越快越好 |
| 905 | heldout_cmp_multi_022 | none | - | 1图 | diagnostic_unsupported | 509b15619ca9 帮我同时算 NDVI 又提水体 |
| 906 | heldout_cmp_multi_023 | none | - | 1图 | diagnostic_unsupported | 麻烦了，一口气把 0398a1c6bed6 的文字读出来再算个 NBR 麻烦尽快 |
| 907 | heldout_cmp_multi_024 | none | - | 1图 | diagnostic_unsupported | 麻烦了，61752dcae315 既要真彩色预览也要目标检测，一起出 越快越好 |
| 908 | heldout_cmp_multi_025 | none | - | 1图 | diagnostic_unsupported | 对了，930b23b23315 重投影完顺手把船和飞机都检测了 |
| 909 | heldout_cmp_multi_026 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，549f55fad2ec 先查元数据，接着直接分割，一条龙 |
| 910 | heldout_cmp_multi_027 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，fec5dd82eba9 重投影完顺手把船和飞机都检测了，拜托拜托 |
| 911 | heldout_cmp_multi_028 | none | - | 1图 | diagnostic_unsupported | 对了，一口气把 716cd99c95d0 的文字读出来再算个 NBR 谢谢啦 |
| 912 | heldout_cmp_multi_029 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，先给 6fb195e73e6d 去云再马上做地物分割，先这样 |
| 913 | heldout_cmp_multi_030 | none | - | 1图 | diagnostic_unsupported | 急用，把 b024df01b8fe 的云掩膜和水体掩膜一次性都做了 麻烦尽快 |
| 914 | heldout_cmp_multi_031 | none | - | 1图 | diagnostic_unsupported | 急用，把 6da86bf06e3d 的云掩膜和水体掩膜一次性都做了 越快越好 |
| 915 | heldout_cmp_multi_032 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，先给 50e330016997 去云再马上做地物分割 越快越好 |
| 916 | heldout_cmp_multi_033 | none | - | 1图 | diagnostic_unsupported | 一口气把 96f179abdb6d 的文字读出来再算个 NBR，先这样 |
| 917 | heldout_cmp_multi_034 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，2a3b0cb2d0a4 先查元数据，接着直接分割，一条龙 谢谢啦 |
| 918 | heldout_cmp_multi_035 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，06335f467256 帮我同时算 NDVI 又提水体 谢谢啦 |
| 919 | heldout_cmp_multi_036 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，3108d1101178 先查元数据，接着直接分割，一条龙 麻烦尽快 |
| 920 | heldout_cmp_multi_037 | none | - | 1图 | diagnostic_unsupported | 麻烦了，先给 83bccee1b54d 去云再马上做地物分割，先这样 |
| 921 | heldout_cmp_multi_038 | none | - | 1图 | diagnostic_unsupported | 麻烦了，先给 0053526d9a13 去云再马上做地物分割，今天要 |
| 922 | heldout_cmp_multi_039 | none | - | 1图 | diagnostic_unsupported | 麻烦了，先给 f8f7e54cdfc0 去云再马上做地物分割 越快越好 |
| 923 | heldout_cmp_multi_040 | none | - | 1图 | diagnostic_unsupported | 麻烦了，先给 29ac75dfa844 去云再马上做地物分割 |
| 924 | heldout_cmp_multi_041 | none | - | 1图 | diagnostic_unsupported | 先给 b38ad39d9c8c 去云再马上做地物分割 谢谢啦 |
| 925 | heldout_cmp_multi_042 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，729cdba66694 既要真彩色预览也要目标检测，一起出 麻烦尽快 |
| 926 | heldout_cmp_multi_043 | none | - | 1图 | diagnostic_unsupported | 急用，先给 ca7aab26f01a 去云再马上做地物分割，今天要 |
| 927 | heldout_cmp_multi_044 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，1e8e89980f3d 既要真彩色预览也要目标检测，一起出 谢谢啦 |
| 928 | heldout_cmp_multi_045 | none | - | 1图 | diagnostic_unsupported | 在吗？想请教下，197b5b0ead5b 重投影完顺手把船和飞机都检测了 |
| 929 | heldout_cmp_multi_046 | none | - | 1图 | diagnostic_unsupported | 102ed4576e26 先查元数据，接着直接分割，一条龙 麻烦尽快 |
| 930 | heldout_cmp_multi_047 | none | - | 1图 | diagnostic_unsupported | 急用，2cb8ecc6ca9f 既要真彩色预览也要目标检测，一起出 麻烦尽快 |
| 931 | heldout_cmp_multi_048 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，f7dc73f9538b 既要真彩色预览也要目标检测，一起出，先这样 |
| 932 | heldout_cmp_multi_049 | none | - | 1图 | diagnostic_unsupported | 对了，先给 ef5c387252e7 去云再马上做地物分割，今天要 |
| 933 | heldout_cmp_multi_050 | none | - | 1图 | diagnostic_unsupported | 对了，58ff01093b8a 先查元数据，接着直接分割，一条龙 谢谢啦 |
| 934 | heldout_cmp_multi_051 | none | - | 1图 | diagnostic_unsupported | 急用，把 a313b5f4ae30 的云掩膜和水体掩膜一次性都做了 麻烦尽快 |
| 935 | heldout_cmp_multi_052 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，先给 14b65ed7aaab 去云再马上做地物分割 越快越好 |
| 936 | heldout_cmp_multi_053 | none | - | 1图 | diagnostic_unsupported | 在吗？想请教下，b8a6d1a8cc95 帮我同时算 NDVI 又提水体 |
| 937 | heldout_cmp_multi_054 | none | - | 1图 | diagnostic_unsupported | 急用，a68f3bd89199 重投影完顺手把船和飞机都检测了，拜托拜托 |
| 938 | heldout_cmp_multi_055 | none | - | 1图 | diagnostic_unsupported | 对了，bd46cfafff43 先查元数据，接着直接分割，一条龙 越快越好 |
| 939 | heldout_cmp_multi_056 | none | - | 1图 | diagnostic_unsupported | 对了，把 d2c19eef0fc7 的云掩膜和水体掩膜一次性都做了 谢谢啦 |
| 940 | heldout_cmp_multi_057 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，7c0c81a05110 先查元数据，接着直接分割，一条龙，今天要 |
| 941 | heldout_cmp_multi_058 | none | - | 1图 | diagnostic_unsupported | 麻烦了，0ed3bd56a5ea 先查元数据，接着直接分割，一条龙，拜托拜托 |
| 942 | heldout_cmp_multi_059 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，先给 cecb4eead981 去云再马上做地物分割，先这样 |
| 943 | heldout_cmp_multi_060 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，把 385ccdc178f4 的云掩膜和水体掩膜一次性都做了 越快越好 |
| 944 | heldout_cmp_multi_061 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，f9a74b2a8e05 重投影完顺手把船和飞机都检测了 |
| 945 | heldout_cmp_multi_062 | none | - | 1图 | diagnostic_unsupported | 麻烦了，d94695119c5b 重投影完顺手把船和飞机都检测了，今天要 |
| 946 | heldout_cmp_multi_063 | none | - | 1图 | diagnostic_unsupported | 在吗？想请教下，6ac93039996d 重投影完顺手把船和飞机都检测了，拜托拜托 |
| 947 | heldout_cmp_multi_064 | none | - | 1图 | diagnostic_unsupported | 急用，把 179a7adf66d6 的云掩膜和水体掩膜一次性都做了 谢谢啦 |
| 948 | heldout_cmp_multi_065 | none | - | 1图 | diagnostic_unsupported | 嗨，那个，先给 cc55ad20c5d5 去云再马上做地物分割 越快越好 |
| 949 | heldout_cmp_multi_066 | none | - | 1图 | diagnostic_unsupported | 辛苦帮个忙，c5dc069cc29e 帮我同时算 NDVI 又提水体 越快越好 |
| 950 | heldout_noise_dirty_000 | call | calculate_ndvi | 1图 | main | 在吗？想请教下 评估下 f973829c00f3 的植被覆盖 用 NDVI 就行 先这样 嗯嗯嗯嗯嗯嗯嗯嗯 |
| 951 | heldout_noise_dirty_001 | call | detect_objects | 1图 | main | 辛苦帮个忙 帮我定位 e9f406ef377a 中的桥 今天要 嗯嗯嗯嗯嗯嗯 |
| 952 | heldout_noise_dirty_002 | call | raster_inspect | 1图 | main | 嗨 那个 上传的 61b52be976ca 是多少波段的？顺便看下 CRS 先这样 |
| 953 | heldout_noise_dirty_003 | call | calculate_ndvi | 1图 | main | 麻烦了 评估下 45584da87729 的植被覆盖 用 NDVI 就行 嗯嗯嗯嗯嗯嗯 |
| 954 | heldout_noise_dirty_004 | call | detect_objects | 1图 | main | 急用，帮我定位 5dd488ee4ae8 中的车 谢谢啦 |
| 955 | heldout_noise_dirty_005 | call | raster_inspect | 1图 | main | 麻烦了，帮我确认 03e0ba17ceca 的投影和覆盖范围对不对 麻烦尽快 嗯嗯嗯 |
| 956 | heldout_noise_dirty_006 | call | calculate_ndvi | 1图 | main | 看下 1327d5c26c69 里植被健康度，先出 NDVI |
| 957 | heldout_noise_dirty_007 | call | detect_objects | 1图 | main | 辛苦帮个忙 数一数 aa2b07e601ee 里有多少车 今天要 |
| 958 | heldout_noise_dirty_008 | call | raster_inspect | 1图 | main | 先核对一下 fa0ae7d73c70 的影象参数再说别的，先这样 |
| 959 | heldout_noise_dirty_009 | call | calculate_ndvi | 1图 | main | 急用，帮忙出一下 bf9cc7df8802 的归一化植被指数 嗯嗯嗯嗯嗯嗯嗯 |
| 960 | heldout_noise_dirty_010 | call | detect_objects | 1图 | main | 66b716ee4ad0 这景找油罐，标出来 麻烦尽快 嗯嗯嗯 |
| 961 | heldout_noise_dirty_011 | call | raster_inspect | 1图 | main | 2c946ddbeaa6 这景图的基本属性查一下，宽高波段那些，今天要 嗯嗯嗯 |
| 962 | heldout_noise_dirty_012 | call | calculate_ndvi | 1图 | main | 辛苦帮个忙 麻烦对 59281d6cee0b 执行 NDVI 计祘 谢谢啦 嗯嗯嗯 |
| 963 | heldout_noise_dirty_013 | call | detect_objects | 1图 | main | 检出 6eff38ef239d 中所有车的位置，今天要 嗯嗯嗯嗯嗯嗯嗯嗯 |
| 964 | heldout_noise_dirty_014 | call | raster_inspect | 1图 | main | 麻烦了，查询影象 1090ce3a9577 的 profile 信息，先这样 嗯嗯嗯嗯嗯 |
| 965 | heldout_noise_dirty_015 | call | calculate_ndvi | 1图 | main | 麻烦了，看下 2dbe26a9a997 里植被健康度，先出 NDVI，先这样 嗯嗯嗯嗯嗯嗯嗯 |
| 966 | heldout_noise_dirty_016 | call | detect_objects | 1图 | main | 对了 数一数 d1860196a97d 里有多少车 |
| 967 | heldout_noise_dirty_017 | call | raster_inspect | 1图 | main | 嗨，那个，5d04fc8ac880 的元数据帮我拉出来看看 谢谢啦 |
| 968 | heldout_noise_dirty_018 | call | calculate_ndvi | 1图 | main | 在吗？想请教下 麻烦对 e47a730367a3 执行 NDVI 计祘 嗯嗯嗯嗯嗯嗯嗯 |
| 969 | heldout_noise_dirty_019 | call | detect_objects | 1图 | main | 嗨，那个，帮我定位 55e12fd74b79 中的飞机，今天要 |
| 970 | heldout_noise_dirty_020 | call | raster_inspect | 1图 | main | 在吗？想请教下 先核对一下 bf2fbfe2124f 的影象参数再说别的 谢谢啦 |
| 971 | heldout_noise_dirty_021 | call | calculate_ndvi | 1图 | main | 嗨 那个 9d0949ee6b9d 的 ndvi 跑一下呗 急等 今天要 嗯嗯嗯嗯嗯 |
| 972 | heldout_noise_dirty_022 | call | detect_objects | 1图 | main | 39022dec1a2f 这景找飞机 标出来 嗯嗯嗯嗯 |
| 973 | heldout_noise_dirty_023 | call | raster_inspect | 1图 | main | 急用，我想先摸清 0c4704441a61 的底细，分辨率、范围、坐标系都报一下，拜托拜托 嗯嗯嗯嗯嗯嗯嗯 |
| 974 | heldout_noise_dirty_024 | call | calculate_ndvi | 1图 | main | 对了 评估下 76913f8bd31d 的植被覆盖 用 NDVI 就行 先这样 |
| 975 | heldout_noise_badid_000 | call | cloud_shadow_mask | 1图 | main | 在吗？想请教下，对 efd68f00 做云检测，应该是这个 ID 吧，拜托拜托 |
| 976 | heldout_noise_badid_001 | call | extract_water_mask | 2图 | main | 对了，a3f9e5 这景帮我做水体掩膜，ID 我记不全了，拜托拜托 |
| 977 | heldout_noise_badid_002 | call | calculate_ndvi | 2图 | main | 急用，好像是 7e43gd7e79b9？给它做NDVI，今天要 |
| 978 | heldout_noise_badid_003 | call | calculate_ndvi | 1图 | main | 辛苦帮个忙，8f51gf665a4c 这景帮我做NDVI，ID 我记不全了，今天要 |
| 979 | heldout_noise_badid_004 | call | extract_water_mask | 2图 | main | 急用，好像是 3f433425？给它做水体掩膜 麻烦尽快 |
| 980 | heldout_noise_badid_005 | none | - | 2图 | main | 嗨，那个，好像是 7e1356？给它做地物分割 |
| 981 | heldout_noise_badid_006 | call | calculate_ndvi | 1图 | main | 好像是 50e0c465？给它做NDVI，先这样 |
| 982 | heldout_noise_badid_007 | call | calculate_ndvi | 2图 | main | 嗨，那个，cd1c7643 这景帮我做NDVI，ID 我记不全了，拜托拜托 |
| 983 | heldout_noise_badid_008 | none | - | 2图 | main | 对了，好像是 cac47d？给它做地物分割，先这样 |
| 984 | heldout_noise_badid_009 | call | calculate_ndvi | 1图 | main | 在吗？想请教下，影像 240bg0db0a2a 的NDVI跑一下，先这样 |
| 985 | heldout_noise_badid_010 | call | cloud_shadow_mask | 2图 | main | 嗨，那个，206fg9ef7b4a 这景帮我做云检测，ID 我记不全了，拜托拜托 |
| 986 | heldout_noise_badid_011 | call | segment_landcover | 2图 | main | 嗨，那个，影像 175e2ba8 的地物分割跑一下，拜托拜托 |
| 987 | heldout_noise_badid_012 | call | segment_landcover | 1图 | main | 对了，91725a 这景帮我做地物分割，ID 我记不全了，拜托拜托 |
| 988 | heldout_noise_badid_013 | call | cloud_shadow_mask | 2图 | main | 在吗？想请教下，99bde2 做个云检测，记错了的话你帮我看下清单 谢谢啦 |
| 989 | heldout_noise_badid_014 | call | extract_water_mask | 2图 | main | 辛苦帮个忙，对 b4e9g6591603 做水体掩膜，应该是这个 ID 吧，先这样 |
| 990 | heldout_noise_badid_015 | call | extract_water_mask | 1图 | main | 对了，4141g9c9880c 做个水体掩膜，记错了的话你帮我看下清单 越快越好 |
| 991 | heldout_noise_badid_016 | call | cloud_shadow_mask | 2图 | main | 对 05399548 做云检测，应该是这个 ID 吧 |
| 992 | heldout_noise_badid_017 | call | cloud_shadow_mask | 2图 | main | 对了，ada6g9376784 这景帮我做云检测，ID 我记不全了 越快越好 |
| 993 | heldout_noise_badid_018 | call | extract_water_mask | 1图 | main | 影像 9540ab 的水体掩膜跑一下 谢谢啦 |
| 994 | heldout_noise_badid_019 | call | extract_water_mask | 2图 | main | 急用，23a0gae35477 这景帮我做水体掩膜，ID 我记不全了 越快越好 |
| 995 | heldout_noise_badid_020 | none | - | 2图 | main | 在吗？想请教下，好像是 4c9a89？给它做NDVI 谢谢啦 |
| 996 | heldout_noise_badid_021 | call | calculate_ndvi | 1图 | main | 影像 cdd34352 的NDVI跑一下 麻烦尽快 |
| 997 | heldout_noise_badid_022 | call | segment_landcover | 2图 | main | 在吗？想请教下，对 a05bg3874a8f 做地物分割，应该是这个 ID 吧 谢谢啦 |
| 998 | heldout_noise_badid_023 | call | segment_landcover | 2图 | main | 在吗？想请教下，对 83f5fbaf 做地物分割，应该是这个 ID 吧 |
| 999 | heldout_noise_badid_024 | call | extract_water_mask | 1图 | main | 急用，影像 c92age5d3d17 的水体掩膜跑一下 麻烦尽快 |
