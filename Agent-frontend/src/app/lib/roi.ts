// 框选「分析聚焦区」(ROI) 的纯逻辑：类型定义 + 归一化 + 转给模型的上下文提示文本。
// 两种来源：
//   - geo：带地理坐标的影像，地图上框选 → 经纬度 bbox [west, south, east, north]（EPSG:4326）。
//   - pixel：无地理坐标的影像，查看器内框选 → 影像内相对位置 [x0, y0, x1, y1]，取值 0..1，左上角为原点。
// 重要事实：后端所有分析工具（NDVI/检测/分割…）都是「全图计算」、无区域参数，
// 只有 clip_reproject_raster 接受 bbox。所以 ROI 不会真正裁剪计算范围，
// 它只作为「解读聚焦提示」注入下一轮对话 + 在图面画出。roiContextLine 必须显式声明这一点，
// 避免模型谎称「只计算了选区」。意图识别仍由后端 LLM 负责，这里不做任何关键词路由。

export type GeoRoi = {
  kind: "geo";
  /** [west, south, east, north]，经纬度（EPSG:4326）。 */
  bbox: [number, number, number, number];
};

export type PixelRoi = {
  kind: "pixel";
  /** [x0, y0, x1, y1]，影像内相对位置 0..1，左上角原点。 */
  rel: [number, number, number, number];
};

export type Roi = GeoRoi | PixelRoi;

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/** 由拖拽两角（任意先后）构造 geo ROI：保证 west<east、south<north。 */
export function geoRoiFromCorners(
  a: [number, number],
  b: [number, number],
): GeoRoi {
  const [lng1, lat1] = a;
  const [lng2, lat2] = b;
  return {
    kind: "geo",
    bbox: [
      Math.min(lng1, lng2),
      Math.min(lat1, lat2),
      Math.max(lng1, lng2),
      Math.max(lat1, lat2),
    ],
  };
}

/** 由拖拽两角（任意先后）构造 pixel ROI：钳制到 0..1，保证 x0<x1、y0<y1。 */
export function pixelRoiFromCorners(
  a: [number, number],
  b: [number, number],
): PixelRoi {
  const x1 = clamp01(a[0]);
  const y1 = clamp01(a[1]);
  const x2 = clamp01(b[0]);
  const y2 = clamp01(b[1]);
  return {
    kind: "pixel",
    rel: [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)],
  };
}

/** ROI 是否为退化区域（面积≈0），用于忽略误点。 */
export function isDegenerateRoi(roi: Roi, epsilon = 1e-9): boolean {
  const [a, b, c, d] = roi.kind === "geo" ? roi.bbox : roi.rel;
  return Math.abs(c - a) < epsilon || Math.abs(d - b) < epsilon;
}

function fmtCoord(value: number): string {
  if (!Number.isFinite(value)) return "N/A";
  return value.toFixed(4).replace(/\.?0+$/, "");
}

function fmtPct(value01: number): string {
  return `${Math.round(clamp01(value01) * 100)}%`;
}

/**
 * 生成注入下一轮对话的 system 提示文本。
 * 末句明确「工具计算仍基于整幅影像」——对齐后端全图计算事实，防止模型谎称只算选区。
 */
export function roiContextLine(roi: Roi): string {
  if (roi.kind === "geo") {
    const [west, south, east, north] = roi.bbox;
    return (
      `用户在地图上框选了分析聚焦区：经度 ${fmtCoord(west)}°–${fmtCoord(east)}°、` +
      `纬度 ${fmtCoord(south)}°–${fmtCoord(north)}°（EPSG:4326）。` +
      `四角坐标（经度, 纬度）：左上[${fmtCoord(west)}, ${fmtCoord(north)}]、` +
      `右上[${fmtCoord(east)}, ${fmtCoord(north)}]、` +
      `左下[${fmtCoord(west)}, ${fmtCoord(south)}]、` +
      `右下[${fmtCoord(east)}, ${fmtCoord(south)}]。` +
      `请在解读结果时重点关注该区域，并明确说明：当前遥感工具仍基于整幅影像计算，该范围仅用于聚焦解读。`
    );
  }
  const [x0, y0, x1, y1] = roi.rel;
  return (
    `用户在影像上框选了分析聚焦区：以影像左上角为原点，` +
    `横向 ${fmtPct(x0)}–${fmtPct(x1)}、纵向 ${fmtPct(y0)}–${fmtPct(y1)} 的矩形区域（该影像无地理坐标，按影像内相对位置描述）。` +
    `请在解读结果时重点关注该区域，并明确说明：当前遥感工具仍基于整幅影像计算，该范围仅用于聚焦解读。`
  );
}
