# 卫星目录备用快照

来自 CelesTrak 的公开 OMM 轨道数据，使用 Flowm/satvis 官方目录生成流程整理。
采集时间：2026-10-10 02:04 UTC；SatVis 源版本：8e36f033ab913d097ef935df52f63899b4ca689d。
15 个分组，active 分组包含 16,695 颗卫星；分组之间存在重复，不能相加当作卫星总数。
轨道数据用于位置推算，不表示卫星能提供某地影像，也不是影像获取时间。

后端立即提供备用数据，每六小时按需刷新固定的八个 CelesTrak 来源；刷新失败保留最近有效结果。
`ops/prepare_satellite_catalog.py` 在发布时生成 SatVis 的独立静态备用目录。
更新快照时必须保留 index 和所有分组，并执行 `ops/verify_release.py` 验证。
轨道与卫星元数据的来源：https://celestrak.org/NORAD/elements/ 、https://celestrak.org/pub/satcat.csv 。
