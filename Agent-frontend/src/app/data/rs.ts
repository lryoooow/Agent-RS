// Domain catalog for the Agent-RS remote-sensing workbench.
// 真实工具目录 + 图例配色常量（展示资产）。
// 注意：这里只放静态展示数据，绝不含意图路由 / 预设回复（意图识别由后端 LLM 负责）。

import type { LucideIcon } from "lucide-react";
import {
  Leaf,
  Droplets,
  Layers3,
  Crosshair,
  Map as MapIcon,
  Gauge,
  Building2,
  Sprout,
  Route,
  Ship,
  Car,
  Plane,
} from "lucide-react";

export interface LegendStop {
  label: string;
  color: string;
}

export interface ToolDef {
  id: string;
  name: string;
  cn: string;
  desc: string;
  icon: LucideIcon;
  color: string;
  subagent: "基础" | "指数分析" | "地物分类" | "目标检测";
}

export const TOOLS: ToolDef[] = [
  {
    id: "qc",
    name: "Image QC",
    cn: "影像质检",
    desc: "读取元数据：尺寸、波段、坐标系、像素统计",
    icon: Gauge,
    color: "#94a3b8",
    subagent: "基础",
  },
  {
    id: "bandcomb",
    name: "Band Composite",
    cn: "波段合成",
    desc: "真彩 / 假彩自定义渲染",
    icon: MapIcon,
    color: "#a78bfa",
    subagent: "基础",
  },
  {
    id: "ndvi",
    name: "NDVI",
    cn: "植被指数",
    desc: "归一化植被指数，评估长势与覆盖",
    icon: Leaf,
    color: "#a3e635",
    subagent: "指数分析",
  },
  {
    id: "ndwi",
    name: "NDWI / MNDWI",
    cn: "水体提取",
    desc: "归一化水体指数，提取河流与水面",
    icon: Droplets,
    color: "#38bdf8",
    subagent: "指数分析",
  },
  {
    id: "detect",
    name: "PP-YOLOE-R",
    cn: "目标检测",
    desc: "DOTA 15 类旋转框：飞机 / 船舶 / 车辆…",
    icon: Crosshair,
    color: "#fbbf24",
    subagent: "目标检测",
  },
  {
    id: "segment",
    name: "U-Net / LandCover.ai",
    cn: "地物分类",
    desc: "像素级语义分割：建筑 / 林地 / 水体",
    icon: Layers3,
    color: "#fb7185",
    subagent: "地物分类",
  },
];

/**
 * Model catalog shown on the 「模型工具」 page (opened from the task bar).
 * 每张卡片的 `prompt` 是发给后端的自然语言任务描述——由后端 LLM 识别意图并规划工具调用，
 * 前端不做任何关键词路由。
 */
export interface ModelTool {
  id: string;
  category: "基础处理" | "指数分析" | "地物分类" | "目标检测";
  cn: string;
  model: string;
  framework: string;
  desc: string;
  icon: LucideIcon;
  color: string;
  /** 点击「运行」时发送给后端的自然语言任务描述。 */
  prompt: string;
}

export const MODELS: ModelTool[] = [
  {
    id: "m-qc",
    category: "基础处理",
    cn: "影像质检",
    model: "Metadata QC",
    framework: "GDAL",
    desc: "读取尺寸、波段、坐标系与像素统计",
    icon: Gauge,
    color: "#94a3b8",
    prompt: "对当前影像做质检，读取尺寸、波段、坐标系与像素统计。",
  },
  {
    id: "m-band",
    category: "基础处理",
    cn: "波段合成",
    model: "Band Composite",
    framework: "Rasterio",
    desc: "真彩 / 假彩自定义渲染",
    icon: MapIcon,
    color: "#a78bfa",
    prompt: "对当前影像做假彩色波段合成（NIR-Red-Green）。",
  },
  {
    id: "m-ndvi",
    category: "指数分析",
    cn: "植被指数",
    model: "NDVI / EVI",
    framework: "NumPy",
    desc: "归一化植被指数，评估长势与覆盖度",
    icon: Leaf,
    color: "#a3e635",
    prompt: "计算当前影像的 NDVI 植被指数，评估长势。",
  },
  {
    id: "m-ndwi",
    category: "指数分析",
    cn: "水体提取",
    model: "MNDWI",
    framework: "NumPy",
    desc: "归一化水体指数，提取河流与水面",
    icon: Droplets,
    color: "#38bdf8",
    prompt: "用 MNDWI 提取当前影像的水体范围。",
  },
  {
    id: "m-building",
    category: "地物分类",
    cn: "建筑提取",
    model: "OCRNet",
    framework: "飞桨 PaddleSeg",
    desc: "城镇建筑物轮廓像素级分割",
    icon: Building2,
    color: "#fb7185",
    prompt: "对当前影像做地物语义分割，提取建筑物轮廓。",
  },
  {
    id: "m-farmland",
    category: "地物分类",
    cn: "农田识别",
    model: "U-Net",
    framework: "飞桨 PaddleSeg",
    desc: "耕地 / 农田地块语义分割",
    icon: Sprout,
    color: "#84cc16",
    prompt: "对当前影像做语义分割，识别耕地与农田地块。",
  },
  {
    id: "m-road",
    category: "地物分类",
    cn: "道路提取",
    model: "D-LinkNet",
    framework: "飞桨 PaddleSeg",
    desc: "线性路网拓扑提取",
    icon: Route,
    color: "#f59e0b",
    prompt: "对当前影像做语义分割，提取道路路网。",
  },
  {
    id: "m-ship",
    category: "目标检测",
    cn: "船舶检测",
    model: "PP-YOLOE-R",
    framework: "飞桨 PaddleDetection",
    desc: "DOTA 旋转框：港口船舶识别",
    icon: Ship,
    color: "#fbbf24",
    prompt: "对当前影像做目标检测，识别港口船舶。",
  },
  {
    id: "m-vehicle",
    category: "目标检测",
    cn: "车辆检测",
    model: "YOLOv8-OBB",
    framework: "Ultralytics YOLO",
    desc: "停车场 / 道路车辆计数",
    icon: Car,
    color: "#f97316",
    prompt: "对当前影像做目标检测，统计道路与停车场车辆。",
  },
  {
    id: "m-plane",
    category: "目标检测",
    cn: "飞机检测",
    model: "YOLOv8-OBB",
    framework: "Ultralytics YOLO",
    desc: "机场停机坪飞机识别",
    icon: Plane,
    color: "#22d3ee",
    prompt: "对当前影像做目标检测，识别机场停机坪的飞机。",
  },
];

export const MODEL_CATEGORIES = [
  "基础处理",
  "指数分析",
  "地物分类",
  "目标检测",
] as const;

export const SPECTRAL_INDICES = [
  "NDVI", "EVI", "SAVI", "MSAVI", "GNDVI",
  "NDWI", "MNDWI", "NDBI", "BSI", "NDMI", "NBR",
];

export const DETECTION_CLASSES: LegendStop[] = [
  { label: "ship 船舶", color: "#fbbf24" },
  { label: "small-vehicle 车辆", color: "#f97316" },
  { label: "harbor 港口", color: "#22d3ee" },
  { label: "storage-tank 储罐", color: "#a78bfa" },
];

export const LANDCOVER_CLASSES: LegendStop[] = [
  { label: "building 建筑", color: "#fb7185" },
  { label: "woodland 林地", color: "#22c55e" },
  { label: "water 水体", color: "#38bdf8" },
  { label: "background 背景", color: "#64748b" },
];

export const NDVI_RAMP: LegendStop[] = [
  { label: "< 0.0 裸地/水", color: "#5b4636" },
  { label: "0.0 – 0.2", color: "#d9c97e" },
  { label: "0.2 – 0.4", color: "#a3c34a" },
  { label: "0.4 – 0.6", color: "#5fae2e" },
  { label: "> 0.6 茂盛", color: "#1f7a1f" },
];

export const WATER_RAMP: LegendStop[] = [
  { label: "open water 明水面", color: "#0ea5e9" },
  { label: "mixed 混合像元", color: "#7dd3fc" },
];

/** 输入框/欢迎页的任务建议——纯自然语言，发给后端由 LLM 处理。 */
export const SUGGESTIONS = [
  { label: "计算 NDVI 评估长势" },
  { label: "提取水体范围" },
  { label: "检测港口船舶与车辆" },
  { label: "地物语义分类" },
];
