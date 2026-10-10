def format_cloud_mask_context(imagery_id: str, stats: dict, result_filename: str) -> str:
    heuristic = stats.get("method") == "heuristic"
    title = "未验证的疑似亮暗区粗筛" if heuristic else "传感器云/云影质量产品"
    lines = [f"## {title}", f"- 影像ID: {imagery_id}", f"- 方法: {stats.get('method')}",
             f"- 有效像元/全幅像元: {stats.get('valid_pixels')}/{stats.get('total_pixels')}"]
    if heuristic:
        lines.extend([
            "边界：此方法没有云/云影识别准确率验证；高亮屋顶、雪、暗色地表可落入候选区。",
            "不得把候选比例称为云量、云影或晴空比例，不得据此声称影像可用于后续定量分析或自动去云。",
        ])
        fields = (("candidate_bright_pct", "疑似高亮候选区"), ("candidate_dark_pct", "疑似暗色候选区"),
                  ("candidate_other_pct", "未命中规则"))
    else:
        lines.extend([
            f"- 质量产品类型: {stats.get('quality_type')}",
            f"- 产品来源/条目: {stats.get('quality_source')}/{stats.get('quality_item_id')}",
            "边界：以下是质量产品的标记统计，产品也可能误检/漏检，不等于实测云量。",
            "未知、雪冰和地形阴影单独保留；未标记云/云影不能保证满足后续分析条件。",
        ])
        if stats.get("quality_type") == "sentinel2_scl":
            lines.append("云标记包含SCL中等/高概率云与薄卷云，地形阴影不计入云影。")
        else:
            lines.append("云标记包含高置信云、膨胀云邻域以及Landsat 8/9的卷云标记；中等/保留置信状态归未知。")
        lines.append("有效像元统计仍包括未知、雪冰和地形阴影等质量状态，不能等同于可分析像元。")
        fields = (("cloud_pct", "云标记"), ("shadow_pct", "云影标记"),
                  ("clear_pct", "QA未标记云/云影的地表"), ("snow_pct", "雪冰"), ("terrain_shadow_pct", "地形阴影"))
    for key, label in (*fields, ("unknown_pct", "未知/未分类"), ("nodata_pct", "无效像元")):
        value = stats.get(key)
        lines.append(f"- {label}（全幅占比）: {value:.2f}%" if isinstance(value, (int, float)) else f"- {label}: 未返回")
    if not heuristic:
        for key, label in (("cloud_valid_pct", "云标记"), ("shadow_valid_pct", "云影标记")):
            value = stats.get(key)
            if isinstance(value, (int, float)):
                lines.append(f"- {label}（有效像元占比）: {value:.2f}%")
    lines.extend([f"- 结果文件: {result_filename}",
                  "分类编码: 0=未标记/未命中规则，1=云标记或疑似高亮，2=云影标记或疑似暗区，"
                  "3=无效，4=未知，5=雪冰，6=地形阴影；1/2的含义必须以本次方法为准。"])
    return "\n".join(lines)
