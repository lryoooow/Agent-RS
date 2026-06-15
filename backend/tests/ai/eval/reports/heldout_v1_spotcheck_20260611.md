# heldout-v1 人工抽检报告（分层抽样，每 category 12.5%）

- dataset_hash: `cdb1f1370f19f7166002b2827b85ca7d60b637b5f19805c68bde738d87531a57`
- seed: 20260610  case_count: 1000  sampled: 126
- 抽样：按 category 分层、seed 确定性随机，每子类至少 1 条——任何子类都不会成为盲区。
- 检查点：①表达无歧义 ②场景合理 ③label 与场景一致。
- 纪律：发现错标不许单条改题；整体废弃本数据集（删除冻结目录——它尚未运行），换新 seed 重新生成冻结。

| # | case_id | expected | query |
| --- | --- | --- | --- |
| 1 | heldout_pos_calculate_ndvi_001 | calculate_ndvi | 嗨，那个，麻烦对 809aeb7a26af 执行 NDVI 计祘，拜托拜托 |
| 10 | heldout_pos_parse_document_010 | parse_document | 对了，文挡 5d024ec5-a7af-1c1e-1e37-8ba0f34f6d68 的核心内容提炼出来 谢谢啦 |
| 26 | heldout_pos_calculate_spectral_index_026 | calculate_spectral_index | 对 b1150b2fdbdc 来个 增强植被指数 EVI 的结果 麻烦尽快 |
| 31 | heldout_pos_detect_objects_031 | detect_objects | 在吗？想请教下，e87e6fe1a9dc 目标排查：重点是船，先这样 |
| 33 | heldout_pos_ocr_recognize_033 | ocr_recognize | 对了，0a0d593825cd 上写了什么字？OCR 一下 麻烦尽快 |
| 41 | heldout_pos_extract_water_mask_041 | extract_water_mask | 辛苦帮个忙，0a2f042dc4ca 做水体提取，掩膜给我 |
| 44 | heldout_pos_segment_landcover_044 | segment_landcover | 嗨，那个，c4fd06a7f99c 的地表覆盖类型图做一份，拜托拜托 |
| 48 | heldout_pos_raster_inspect_048 | raster_inspect | 辛苦帮个忙，先核对一下 05ec299941ff 的影像参数再说别的，今天要 |
| 52 | heldout_pos_cloud_shadow_mask_052 | cloud_shadow_mask | 在吗？想请教下，查下 ae4c2a1d8ee8 哪些区域被云污染了 越快越好 |
| 55 | heldout_pos_detect_objects_055 | detect_objects | 嗨，那个，帮我定位 e222c25d8641 中的车 谢谢啦 |
| 72 | heldout_pos_raster_inspect_072 | raster_inspect | 对了，这景 cb1f3f32eefc 到底几个波段、什么投影，给我看下基本信息 越快越好 |
| 92 | heldout_pos_segment_landcover_092 | segment_landcover | 把 b2c892651e53 按地类切成一块块的，先这样 |
| 108 | heldout_pos_raster_inspect_108 | raster_inspect | 辛苦帮个忙，51ee3a5226f0 这景图的基本属性查一下，宽高波段那些，拜托拜托 |
| 112 | heldout_pos_cloud_shadow_mask_112 | cloud_shadow_mask | 对了，b7bec39dbe95 的云量情况出个掩膜评估下 麻烦尽快 |
| 114 | heldout_pos_clip_reproject_raster_114 | clip_reproject_raster | 麻烦了，c24f40580812 现在的投影不对，统一到 EPSG:32650 越快越好 |
| 146 | heldout_pos_calculate_spectral_index_146 | calculate_spectral_index | 在吗？想请教下，出一份 0e4fac7ba259 的 建筑指数 NDBI 图，先这样 |
| 150 | heldout_pos_clip_reproject_raster_150 | clip_reproject_raster | 麻烦了，5a1078aaa943 帮我换到 EPSG:32650 这个坐标系 越快越好 |
| 154 | heldout_pos_parse_document_154 | parse_document | 急用，1dcfb24d-a814-5ef3-d77b-6e557aefbf9e 内容整理成几条要点 越快越好 |
| 157 | heldout_pos_calculate_ndvi_157 | calculate_ndvi | 嗨，那个，给 75283fe2cbad 算下植被指数 NDVI，看看绿化情况 |
| 160 | heldout_pos_cloud_shadow_mask_160 | cloud_shadow_mask | 急用，ab7dd2e2004b 好像有云，先把云和阴影圈出来质检下 越快越好 |
| 165 | heldout_pos_ocr_recognize_165 | ocr_recognize | 读取 c6ab629171af 中的文字标注信息 越快越好 |
| 169 | heldout_pos_calculate_ndvi_169 | calculate_ndvi | 对了，我要 632cadc4ac8c 的 NDVI 结果图 |
| 171 | heldout_pos_render_band_composite_171 | render_band_composite | 嗨，那个，假彩色合成图来一张，用 677f619414e2 越快越好 |
| 176 | heldout_pos_segment_landcover_176 | segment_landcover | 急用，4a510ccf4e00 的地表覆盖类型图做一份 麻烦尽快 |
| 180 | heldout_pos_raster_inspect_180 | raster_inspect | 在吗？想请教下，这景 7e2835813111 到底几个波段、什么投影，给我看下基本信息，先这样 |
| 186 | heldout_pos_clip_reproject_raster_186 | clip_reproject_raster | 在吗？想请教下，重头影：ec266066a4da 转 EPSG:32649，谢谢 麻烦尽快 |
| 191 | heldout_pos_web_search_191 | web_search | 在吗？想请教下，查查 2026 年新发布的开源遥感数据集有哪些 越快越好 |
| 195 | heldout_pos_render_band_composite_195 | render_band_composite | 辛苦帮个忙，ef8aca9d2f89 渲染成假彩色发我 麻烦尽快 |
| 197 | heldout_pos_extract_water_mask_197 | extract_water_mask | 麻烦了，我要 a04bee55fe96 的水域边界图层，先这样 |
| 198 | heldout_pos_clip_reproject_raster_198 | clip_reproject_raster | 在吗？想请教下，eb43cd29b618 现在的投影不对，统一到 EPSG:32650，先这样 |
| 220 | heldout_pos_cloud_shadow_mask_220 | cloud_shadow_mask | 辛苦帮个忙，9e451f323494 需要云和云影的质检掩模，拜托拜托 |
| 225 | heldout_pos_ocr_recognize_225 | ocr_recognize | 对了，d94fc8a48e35 上写了什么字？OCR 一下，今天要 |
| 239 | heldout_pos_web_search_239 | web_search | 辛苦帮个忙，这两天哪里有台风预警，查一下 麻烦尽快 |
| 242 | heldout_pos_calculate_spectral_index_242 | calculate_spectral_index | 麻烦了，866366670eba 需要做 增强植被指数 EVI 分析，拜托拜托 |
| 263 | heldout_pos_web_search_263 | web_search | 嗨，那个，下周成都的天气趋势帮我查下 |
| 271 | heldout_pos_detect_objects_271 | detect_objects | 麻烦了，帮我定位 4da9a4adbe59 中的车 越快越好 |
| 275 | heldout_pos_web_search_275 | web_search | 麻烦了，最近高分卫星影象的官方采购价格是多少 越快越好 |
| 277 | heldout_pos_calculate_ndvi_277 | calculate_ndvi | 急用，我要 9ded6c6fb083 的 NDVI 结果图 谢谢啦 |
| 278 | heldout_pos_calculate_spectral_index_278 | calculate_spectral_index | 麻烦了，对 376a9a5342dd 来个 土壤调节植被 SAVI 的结果 麻烦尽快 |
| 281 | heldout_pos_extract_water_mask_281 | extract_water_mask | 麻烦了，我要 a2449dc09209 的水域边界图层 越快越好 |
| 284 | heldout_pos_segment_landcover_284 | segment_landcover | 麻烦了，把 5a30c2eea614 按地类切成一块块的 谢谢啦 |
| 286 | heldout_pos_parse_document_286 | parse_document | 麻烦了，总结一下文档 727792bb-30f0-893c-9254-90edb9b5ef64 讲了什么 |
| 303 | heldout_pos_render_band_composite_303 | render_band_composite | 对了，给 df4c63430a57 做假彩色显示，先这样 |
| 307 | heldout_pos_detect_objects_307 | detect_objects | 在吗？想请教下，8e721201090b 目标排查：重点是桥，拜托拜托 |
| 317 | heldout_pos_extract_water_mask_317 | extract_water_mask | 对了，把 1b9dcd1d8d81 的河湖水域提取一下，先这样 |
| 333 | heldout_pos_ocr_recognize_333 | ocr_recognize | 急用，153f9ab10c4d 里印的文字内容提取一下 |
| 339 | heldout_pos_render_band_composite_339 | render_band_composite | 在吗？想请教下，我想看 f230cc1f3a46 的假彩色效果 谢谢啦 |
| 346 | heldout_pos_parse_document_346 | parse_document | 在吗？想请教下，把 a6928719-f612-1c06-ab23-638b71bee5e5 里的章节要点列一列 |
| 352 | heldout_neg_missing_id_002 | none | 嗨，那个，把刚说的那张图做个 地物分割 麻烦尽快 |
| 357 | heldout_neg_concept_007 | none | 在吗？想请教下，NBR 和普通照片处理的区别是啥，先这样 |
| 365 | heldout_neg_non_owner_015 | none | 辛苦帮个忙，7b62d3281e2e 这景做一下 地物分割 |
| 374 | heldout_neg_negation_024 | none | 辛苦帮个忙，先别动手算，就跟我讲讲 NDVI 是怎么回事 越快越好 |
| 375 | heldout_neg_concept_025 | none | 在吗？想请教下，科普一下 近红外波段 呗 麻烦尽快 |
| 378 | heldout_neg_general_028 | none | 把 land cover 翻译成中文，拜托拜托 |
| 386 | heldout_neg_negation_036 | none | 对了，地物分割 别处理，解释清楚概念就行，先这样 |
| 394 | heldout_neg_missing_id_044 | none | 对了，那张图的 地物分割 安排一下 麻烦尽快 |
| 407 | heldout_neg_non_owner_057 | none | 辛苦帮个忙，麻烦处理 78d9d63c9897 的水体掩膜 谢谢啦 |
| 409 | heldout_neg_contradiction_059 | none | 辛苦帮个忙，用 OCR 帮我判断 2506ff32a252 的植被覆盖多少 谢谢啦 |
| 410 | heldout_neg_negation_060 | none | 嗨，那个，先别动手算，就跟我讲讲 目标检测 是怎么回事，拜托拜托 |
| 412 | heldout_neg_missing_id_062 | none | 把刚说的那张图做个 NDVI 麻烦尽快 |
| 423 | heldout_neg_concept_073 | none | 近红外波段 的取值范围一般是多少，怎么解读，今天要 |
| 424 | heldout_neg_missing_id_074 | none | 对了，把刚说的那张图做个 水体掩膜 麻烦尽快 |
| 431 | heldout_neg_non_owner_081 | none | 在吗？想请教下，麻烦处理 50502b934dd3 的重投影，拜托拜托 |
| 432 | heldout_neg_general_082 | none | 嗨，那个，推荐几本科幻小说，先这样 |
| 434 | heldout_neg_negation_084 | none | 对了，地物分割 别处理，解释清楚概念就行 越快越好 |
| 442 | heldout_neg_missing_id_092 | none | 那张图的 水体掩膜 安排一下 |
| 444 | heldout_neg_general_094 | none | 急用，用 python 写个二分查找，今天要 |
| 459 | heldout_neg_concept_109 | none | NBR 在遥感里到底意味着什么，今天要 |
| 461 | heldout_neg_non_owner_111 | none | 在吗？想请教下，用 6dbd86ded878 跑 重投影 谢谢啦 |
| 462 | heldout_neg_general_112 | none | 推荐几本科幻小说 麻烦尽快 |
| 481 | heldout_neg_contradiction_131 | none | 拿云掩膜工具把文档 8e639fa8-bc42-dcda-f78b-d4380f8ae455 总结一下，今天要 |
| 503 | heldout_neg_non_owner_153 | none | 78c63342319e，任务是水体掩膜，开始吧 |
| 507 | heldout_neg_concept_157 | none | 麻烦了，想了解下 NDVI 这个概念，别给我跑数据 越快越好 |
| 523 | heldout_neg_contradiction_173 | none | 拿波段合成功能翻译文档 d6173b09-f8d2-54ed-c0ff-414c533c8216 麻烦尽快 |
| 524 | heldout_neg_negation_174 | none | 急用，云掩膜 别处理，解释清楚概念就行，今天要 |
| 546 | heldout_neg_general_196 | none | 辛苦帮个忙，给我写段项目周报开头 越快越好 |
| 565 | heldout_neg_contradiction_215 | none | 麻烦了，拿波段合成功能翻译文档 d8ba5393-8073-4537-1b50-73afd5be6716，拜托拜托 |
| 569 | heldout_neg_non_owner_219 | none | 辛苦帮个忙，d858c8cbf747 这景做一下 NDVI 谢谢啦 |
| 582 | heldout_neg_general_232 | none | 急用，推荐几本科幻小说，拜托拜托 |
| 583 | heldout_neg_contradiction_233 | none | 急用，拿波段合成功能翻译文档 7543b263-aaa3-c186-5828-177079edfd39 |
| 585 | heldout_neg_concept_235 | none | 在吗？想请教下，云阴影 在遥感里到底意味着什么 谢谢啦 |
| 595 | heldout_neg_contradiction_245 | none | 嗨，那个，用 OCR 帮我判断 3a0be7ff68e3 的植被覆盖多少，拜托拜托 |
| 622 | heldout_neg_missing_id_272 | none | 急用，就这张图，跑 重投影 |
| 626 | heldout_neg_negation_276 | none | 辛苦帮个忙，不用调用什么工具，目标检测 的思路给我讲讲 谢谢啦 |
| 654 | heldout_bnd_segment_not_detect_004 | segment_landcover | 辛苦帮个忙，对 75298236a47b 做整图地物分割，不要目标框 麻烦尽快 |
| 656 | heldout_bnd_parse_not_ocr_006 | parse_document | 对了，文档 7151b065-c40e-fac1-7939-6eb6733d3a42 给我总结要点，不是图片认字 越快越好 |
| 664 | heldout_bnd_parse_not_ocr_014 | parse_document | 急用，aae17044-b26d-6e47-817c-49df9e978d5e 文档解析走起，要章节摘要，今天要 |
| 682 | heldout_bnd_ocr_not_detect_032 | ocr_recognize | 对了，28beef150f5b 上的文字给我读出来，不是让你找飞机 越快越好 |
| 689 | heldout_bnd_ocr_not_parse_039 | ocr_recognize | 对了，c1d254b6e0bf 是张扫描地图，读上面的字，不是解析什么文档 越快越好 |
| 702 | heldout_bnd_segment_not_detect_052 | segment_landcover | 麻烦了，对 732dd80a425a 做整图地物分割，不要目标框，今天要 |
| 706 | heldout_bnd_ocr_not_detect_056 | ocr_recognize | 在吗？想请教下，d28af786d835 这图我只关心上面写了啥字，目标别管 |
| 719 | heldout_bnd_detect_not_segment_069 | detect_objects | 在吗？想请教下，定位 133e684199f7 中的飞机，不需要 landcover |
| 764 | heldout_bnd_water_not_index_114 | extract_water_mask | 我要 646844cffaf7 水域的范围掩膜，不是算什么指数 越快越好 |
| 767 | heldout_bnd_detect_not_segment_117 | detect_objects | 麻烦了，只找 adc28b33c5c9 里的船，不用整图分类，先这样 |
| 768 | heldout_bnd_parse_not_ocr_118 | parse_document | 辛苦帮个忙，文档 0907b01e-7bcc-850d-0a13-9dc9dfcaffa1 给我总结要点，不是图片认字 |
| 772 | heldout_bnd_water_not_index_122 | extract_water_mask | 嗨，那个，把 bbc41c04e6d0 的水体边界提出来，别只给 NDWI 数值 |
| 780 | heldout_bnd_water_not_index_130 | extract_water_mask | 把 c3fb0d3a857b 的水体边界提出来，别只给 NDWI 数值 越快越好 |
| 783 | heldout_bnd_detect_not_segment_133 | detect_objects | 嗨，那个，295f88f6ca7d 找车，别跑分割 谢谢啦 |
| 787 | heldout_bnd_detect_not_ocr_137 | detect_objects | 辛苦帮个忙，框出 3a749d5faafd 中的油罐，文字识别就免了 越快越好 |
| 789 | heldout_bnd_index_not_water_139 | calculate_spectral_index | 辛苦帮个忙，给 7782c251b09f 出 NDWI 指数图，水体掩模不需要，先这样 |
| 797 | heldout_bnd_index_not_water_147 | calculate_spectral_index | 对了，eea925b171a5 我要的是水体指数分布，不是范围圈定 麻烦尽快 |
| 801 | heldout_bnd_ocr_not_parse_151 | ocr_recognize | 麻烦了，识别 4308c4c308dc 图面文字，我没有要传 PDF，拜托拜托 |
| 809 | heldout_bnd_ocr_not_parse_159 | ocr_recognize | 急用，d75e364e00b9 是张扫描地图，读上面的字，不是解析什么文档 麻烦尽快 |
| 818 | heldout_bnd_ocr_not_detect_168 | ocr_recognize | 我要 756a240edd02 的图面注记内容，别做目标检测，今天要 |
| 819 | heldout_bnd_detect_not_ocr_169 | detect_objects | 麻烦了，f677a689c270 找目标：车辆，别给我做 OCR 越快越好 |
| 827 | heldout_bnd_detect_not_ocr_177 | detect_objects | 嗨，那个，检测 7b5830a7b512 的飞机位置，注记文字不用管，拜托拜托 |
| 838 | heldout_bnd_segment_not_detect_188 | segment_landcover | 嗨，那个，895dcf6b6c90 整幅按地类分块，不是找单个目标 |
| 845 | heldout_bnd_index_not_water_195 | calculate_spectral_index | 在吗？想请教下，84af783e38d1 我要的是水体指数分布，不是范围圈定，先这样 |
| 858 | heldout_cmp_web_008 | web_search | 查一下最新的耕地保护政策，另外找几个高分辨率农业遥感公开数据集，拜托拜托 |
| 861 | heldout_cmp_web_011 | web_search | 嗨，那个，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格 越快越好 |
| 870 | heldout_cmp_web_020 | web_search | 在吗？想请教下，看下这周末上海限行规定，以及天气适不适合外拍 |
| 882 | heldout_cmp_web_032 | web_search | 急用，搜下今年遥感大会的举办时间，顺便查下举办地的酒店价格 麻烦尽快 |
| 885 | heldout_cmp_multi_002 | none | 辛苦帮个忙，9ea39b7d69dc 先查元数据，接着直接分割，一条龙 |
| 897 | heldout_cmp_multi_014 | none | 麻烦了，41e11c94a17f 既要真彩色预览也要目标检测，一起出 谢谢啦 |
| 916 | heldout_cmp_multi_033 | none | 麻烦了，3ba379c12fcc 既要真彩色预览也要目标检测，一起出，今天要 |
| 919 | heldout_cmp_multi_036 | none | 麻烦了，把 a9c0da7fc230 的云掩膜和水体掩膜一次性都做了，今天要 |
| 920 | heldout_cmp_multi_037 | none | 在吗？想请教下，935db9f3d28e 重投影完顺手把船和飞机都检测了 越快越好 |
| 921 | heldout_cmp_multi_038 | none | 对了，a5b4a491e624 重投影完顺手把船和飞机都检测了 谢谢啦 |
| 926 | heldout_cmp_multi_043 | none | 嗨，那个，先给 a77d3cecee5d 去云再马上做地物分割 麻烦尽快 |
| 941 | heldout_cmp_multi_058 | none | 先给 b169c5f7cacd 去云再马上做地物分割，今天要 |
| 959 | heldout_noise_dirty_009 | calculate_ndvi | 在吗？想请教下，给 9d47ff15e1f8 算下植被指数 NDVI，看看绿化情况 麻烦尽快 嗯嗯嗯嗯 |
| 960 | heldout_noise_dirty_010 | detect_objects | 麻烦了，2c09a28bd50b 目标排查：重点是飞机 麻烦尽快 嗯嗯嗯 |
| 970 | heldout_noise_dirty_020 | raster_inspect | 辛苦帮个忙 帮我确认 8013f00c29c1 的投影和覆盖范围对不对 谢谢啦 嗯嗯嗯嗯嗯嗯嗯 |
| 981 | heldout_noise_badid_006 | none | 3da1g1c035bf 做个重投影，记错了的话你帮我看下清单，拜托拜托 |
| 984 | heldout_noise_badid_009 | none | 在吗？想请教下，好像是 c146gad27026？给它做水体掩膜 越快越好 |
| 992 | heldout_noise_badid_017 | none | 在吗？想请教下，对 1303gf86400a 做NDVI，应该是这个 ID 吧，今天要 |

## 人工结论

- [ ] 抽检通过，冻结生效
- [ ] 发现错标（列出 case_id，废弃数据集换 seed 重生成）
