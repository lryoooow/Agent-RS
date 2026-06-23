// 经纬网（graticule）纯逻辑：按当前视图范围 + zoom 选「整齐」间隔，生成经纬线 GeoJSON + 端点标签。
// 不依赖 maplibre，便于单测。地图侧只负责把返回的 FeatureCollection 灌进 geojson source。

export type LngLatBounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};

// 候选间隔（度）：从大到小，按 zoom 选第一个「在视图里能产生足够但不过密线条」的值。
const STEP_CANDIDATES = [30, 10, 5, 2, 1, 0.5, 0.25, 0.1, 0.05, 0.02, 0.01];

/**
 * 根据可视范围跨度选一个整齐间隔：目标是每个方向大约 4~10 条线。
 * 跨度越小（放得越大）间隔越细。返回的间隔保证视图内线条数落在合理区间。
 */
export function pickGraticuleStep(bounds: LngLatBounds): number {
  const lonSpan = Math.abs(bounds.east - bounds.west);
  const latSpan = Math.abs(bounds.north - bounds.south);
  const span = Math.max(lonSpan, latSpan, 1e-6);
  // 期望约 6 条线 → 目标间隔 = span / 6，取「不大于它」的最大候选值。
  const target = span / 6;
  for (const step of STEP_CANDIDATES) {
    if (step <= target) return step;
  }
  return STEP_CANDIDATES[STEP_CANDIDATES.length - 1];
}

function snapDown(value: number, step: number): number {
  return Math.floor(value / step) * step;
}

// 浮点间隔累加会有误差，按 step 的小数位四舍五入清理，避免标签出现 1.7999999。
function roundTo(value: number, step: number): number {
  const decimals = step < 1 ? Math.ceil(-Math.log10(step)) + 1 : 0;
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

export function formatGraticuleLabel(value: number, axis: "lon" | "lat"): string {
  const v = Math.abs(value);
  const text = v % 1 === 0 ? v.toFixed(0) : v.toFixed(2).replace(/\.?0+$/, "");
  if (axis === "lon") return `${text}°${value >= 0 ? "E" : "W"}`;
  return `${text}°${value >= 0 ? "N" : "S"}`;
}

/**
 * 生成经纬网 GeoJSON：每条经线/纬线一个 LineString；每条线在视图边缘放一个标签点。
 * - 纬度截断在 [-85, 85]（Web Mercator 极区不可用）。
 * - 经度跨度按 step 限制最多生成 ~200 条线，避免极端缩放下卡死。
 */
export function buildGraticule(bounds: LngLatBounds): GeoJSON.FeatureCollection {
  const step = pickGraticuleStep(bounds);
  const features: GeoJSON.Feature[] = [];

  const south = Math.max(-85, Math.min(bounds.south, bounds.north));
  const north = Math.min(85, Math.max(bounds.south, bounds.north));
  const west = Math.min(bounds.west, bounds.east);
  const east = Math.max(bounds.west, bounds.east);

  const MAX_LINES = 200;

  // 经线（竖线）：lng 固定，从 south 画到 north。
  let lonCount = 0;
  for (let lng = snapDown(west, step); lng <= east && lonCount < MAX_LINES; lng += step) {
    const v = roundTo(lng, step);
    features.push({
      type: "Feature",
      properties: { kind: "line" },
      geometry: { type: "LineString", coordinates: [[v, south], [v, north]] },
    });
    features.push({
      type: "Feature",
      properties: { kind: "label", label: formatGraticuleLabel(v, "lon") },
      geometry: { type: "Point", coordinates: [v, south] },
    });
    lonCount += 1;
  }

  // 纬线（横线）：lat 固定，从 west 画到 east。
  // 注意 snapDown 可能落到 clamp 边界之下（如 step=30、south=-85 → -90），故逐条跳过越界纬度。
  let latCount = 0;
  for (let lat = snapDown(south, step); lat <= north && latCount < MAX_LINES; lat += step) {
    if (lat < south || lat > north) continue;
    const v = roundTo(lat, step);
    features.push({
      type: "Feature",
      properties: { kind: "line" },
      geometry: { type: "LineString", coordinates: [[west, v], [east, v]] },
    });
    features.push({
      type: "Feature",
      properties: { kind: "label", label: formatGraticuleLabel(v, "lat") },
      geometry: { type: "Point", coordinates: [west, v] },
    });
    latCount += 1;
  }

  return { type: "FeatureCollection", features };
}
