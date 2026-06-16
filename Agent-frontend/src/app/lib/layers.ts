import type { GeospatialResult, ChatTurn, LegendInfo } from "../types";
import { DETECTION_CLASSES, LANDCOVER_CLASSES, NDVI_RAMP, WATER_RAMP } from "../data/rs";

// 图层视图模型：地图叠加 + 右侧图层面板共用。
// 全部由对话中的真实 geospatial_result 派生，不含任何 mock。
export type LayerKind = "imagery" | "index" | "water" | "detection" | "segmentation";

export interface LegendStop {
  label: string;
  color: string;
}

export interface RSLayer {
  id: string;
  name: string;
  sublabel: string;
  kind: LayerKind;
  visible: boolean;
  opacity: number; // 0..1
  color: string;
  legend?: LegendStop[];
  /** 真实结果图片 URL（相对 /api，地图用 image source 叠加）。 */
  url?: string;
  /** [west, south, east, north]，地图据此 fitBounds + 四角定位。 */
  bounds?: [number, number, number, number] | null;
  imageryId: string;
  meta?: Record<string, string>;
}

type LayerOverride = { visible?: boolean; opacity?: number; removed?: boolean };

const KIND_COLOR: Record<LayerKind, string> = {
  imagery: "#2dd4bf",
  index: "#a3e635",
  water: "#38bdf8",
  detection: "#fbbf24",
  segmentation: "#fb7185",
};

function backendLegend(legend: LegendInfo | null | undefined): LegendStop[] | undefined {
  if (!legend) return undefined;
  return [
    { label: `${legend.label} ${fmt(legend.min)}`, color: rampLow(legend.palette) },
    { label: `${fmt(legend.max)}`, color: rampHigh(legend.palette) },
  ];
}

/** 把一条 geospatial 结果转成一个图层视图模型（id 用 imagery_id + 类型，保证同图同类可替换）。 */
function layerFromResult(result: GeospatialResult): RSLayer {
  const idShort = result.imagery_id.slice(0, 8);
  const base = {
    url: result.result_url || undefined,
    bounds: result.bounds,
    imageryId: result.imagery_id,
    visible: true,
    opacity: 1,
  };
  switch (result.type) {
    case "preview":
      return {
        ...base,
        id: `imagery-${result.imagery_id}`,
        name: "影像预览",
        sublabel: `GeoTIFF · ${idShort}`,
        kind: "imagery",
        color: KIND_COLOR.imagery,
      };
    case "composite":
      return {
        ...base,
        id: `composite-${result.imagery_id}`,
        name: result.mode === "false_color" ? "假彩色合成" : result.mode === "true_color" ? "真彩色合成" : "波段合成",
        sublabel: `波段 ${result.bands_used.join("-")}`,
        kind: "imagery",
        color: KIND_COLOR.imagery,
      };
    case "ndvi":
      return {
        ...base,
        id: `ndvi-${result.imagery_id}`,
        name: "NDVI",
        sublabel: `植被指数 · 均值 ${fmt(result.stats.mean)}`,
        kind: "index",
        opacity: 0.78,
        color: KIND_COLOR.index,
        legend: backendLegend(result.legend) ?? NDVI_RAMP,
      };
    case "spectral_index": {
      const isWater = /ndwi|mndwi/i.test(result.index_type);
      return {
        ...base,
        id: `index-${result.index_type}-${result.imagery_id}`,
        name: result.index_type.toUpperCase(),
        sublabel: `光谱指数 · 均值 ${fmt(result.stats.mean)}`,
        kind: isWater ? "water" : "index",
        opacity: 0.75,
        color: isWater ? KIND_COLOR.water : KIND_COLOR.index,
        legend: backendLegend(result.legend) ?? (isWater ? WATER_RAMP : NDVI_RAMP),
      };
    }
    case "detection":
      return {
        ...base,
        id: `detect-${result.imagery_id}`,
        name: "目标检测",
        sublabel: `${result.detection_count} 个目标`,
        kind: "detection",
        color: KIND_COLOR.detection,
        legend: result.classes.length
          ? result.classes.map((c) => ({ label: `${c.label || c.name} ${c.count}`, color: c.color }))
          : DETECTION_CLASSES,
      };
    case "segmentation":
      return {
        ...base,
        id: `segment-${result.imagery_id}`,
        name: "地物分类",
        sublabel: `${result.classes.length} 类`,
        kind: "segmentation",
        opacity: 0.62,
        color: KIND_COLOR.segmentation,
        legend: result.classes.length
          ? result.classes.map((c) => ({ label: `${c.label || c.name} ${fmt(c.percentage)}%`, color: c.color }))
          : LANDCOVER_CLASSES,
      };
  }
}

/**
 * 从对话 turns 中收集所有 geospatial 结果，派生图层列表。
 * 同 id 后出现的覆盖先出现的（最新结果优先）；imagery 预览置于列表底部作为底图。
 * layerOverrides 提供用户在右侧面板的显隐/透明度/删除覆盖。
 */
export function layersFromTurns(
  turns: ChatTurn[],
  overrides: Record<string, LayerOverride>,
): RSLayer[] {
  const byId = new Map<string, RSLayer>();
  for (const turn of turns) {
    if (!turn.geospatialResult) continue;
    const layer = layerFromResult(turn.geospatialResult);
    byId.set(layer.id, layer); // 后出现覆盖先出现
  }
  const layers = [...byId.values()]
    .map((layer) => {
      const ov = overrides[layer.id];
      if (!ov) return layer;
      return {
        ...layer,
        visible: ov.visible ?? layer.visible,
        opacity: ov.opacity ?? layer.opacity,
        removed: ov.removed,
      } as RSLayer & { removed?: boolean };
    })
    .filter((layer) => !(layer as RSLayer & { removed?: boolean }).removed);

  // imagery 类置底（先渲染，作为其它结果图层的底图）。
  return layers.sort((a, b) => {
    const rank = (l: RSLayer) => (l.kind === "imagery" ? 1 : 0);
    return rank(a) - rank(b);
  });
}

function fmt(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "N/A";
  if (Math.abs(value) >= 100) return value.toFixed(1);
  return value.toFixed(3).replace(/\.?0+$/, "");
}

// 后端 palette 名 → 取两端代表色（仅用于图例两端示意，真实渲染由结果 PNG 自带配色）。
function rampLow(palette: string): string {
  if (/ndvi|rdylgn|greens/i.test(palette)) return "#5b4636";
  if (/blue|water/i.test(palette)) return "#7dd3fc";
  return "#475569";
}
function rampHigh(palette: string): string {
  if (/ndvi|rdylgn|greens/i.test(palette)) return "#1f7a1f";
  if (/blue|water/i.test(palette)) return "#0ea5e9";
  return "#e2e8f0";
}
