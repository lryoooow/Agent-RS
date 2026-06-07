from __future__ import annotations

from typing import Any


INDEX_LABELS = {
    "ndwi": "NDWI 水体指数",
    "mndwi": "MNDWI 改进水体指数",
    "ndbi": "NDBI 建成区指数",
    "evi": "EVI 增强植被指数",
    "savi": "SAVI 土壤调节植被指数",
    "gndvi": "GNDVI 绿光归一化植被指数",
    "ndmi": "NDMI 植被水分指数",
    "nbr": "NBR 火烧迹地指数",
    "msavi": "MSAVI 改进土壤调节植被指数",
    "bsi": "BSI 裸土指数",
}


def format_spectral_index_context(imagery_id: str, index_type: str, stats: dict[str, Any], result_filename: str) -> str:
    label = INDEX_LABELS.get(index_type, index_type.upper())
    return "\n".join(
        [
            f"{label} 计算完成（影像 ID: {imagery_id}）。",
            f"- 结果图层: {result_filename}",
            f"- 最小值: {stats.get('min')}",
            f"- 最大值: {stats.get('max')}",
            f"- 平均值: {stats.get('mean')}",
            f"- 标准差: {stats.get('std')}",
            f"- NoData 占比: {stats.get('nodata_pct', 0.0)}%",
            "解读边界: 该结果用于单景影像内部相对分析；跨时相定量对比需要确认辐射校正和波段一致性。",
        ]
    )
