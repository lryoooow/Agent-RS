from __future__ import annotations


def format_instance_segment_context(imagery_id: str, result: dict) -> str:
    counts = result.get("counts") or {}
    summary = "、".join(f"{name} {int(count):,} 个" for name, count in counts.items()) or "未发现匹配实例"
    pixels = int(result.get("union_pixels") or 0)
    area = result.get("area_m2")
    area_text = f"，掩膜估算面积 {float(area):,.2f} 平方米" if area is not None else ""
    return (
        f"SAM3 实例分割完成。影像 {imagery_id}；{summary}；掩膜像素 {pixels:,}{area_text}。"
        "这是开放词汇模型识别结果，实例数量、边界和面积需要结合原始影像复核。"
    )
