// Static catalog data for the Agent-RS remote-sensing workbench.
// Runtime mock logic (scripted agent responses, fake layers) has been removed —
// the app now drives everything from the real backend via useChatController /
// useImageryUpload. This file only holds static UI catalog data.

import type { LucideIcon } from "lucide-react";
import {
  Leaf,
  Droplets,
  Map as MapIcon,
  Gauge,
  Building2,
  Sprout,
  Route,
  Ship,
  Car,
  Plane,
} from "lucide-react";

/** Default area-of-interest the map opens on before any imagery is loaded. */
export const AOI = {
  center: [-121.6, 38.06] as [number, number],
  zoom: 12.2,
  // [west, south, east, north]
  bbox: [-121.665, 38.022, -121.535, 38.098] as [number, number, number, number],
};

/**
 * Model catalog shown on the 「模型工具」 page (opened from the task bar).
 * Grouped by category. `intent` links a card to a task description that gets sent
 * to the real agent (App.launchModel), which decides the actual tool call.
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
  /** Maps to a task the agent can run; used as the launch hint. */
  intent?: string;
}

export const MODELS: ModelTool[] = [
  // 基础处理
  {
    id: "m-qc",
    category: "基础处理",
    cn: "影像质检",
    model: "Metadata QC",
    framework: "GDAL",
    desc: "读取尺寸、波段、坐标系与像素统计",
    icon: Gauge,
    color: "#94a3b8",
    intent: "qc",
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
    intent: "bandcomb",
  },
  // 指数分析
  {
    id: "m-ndvi",
    category: "指数分析",
    cn: "植被指数",
    model: "NDVI / EVI",
    framework: "NumPy",
    desc: "归一化植被指数，评估长势与覆盖度",
    icon: Leaf,
    color: "#a3e635",
    intent: "ndvi",
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
    intent: "ndwi",
  },
  // 地物分类
  {
    id: "m-building",
    category: "地物分类",
    cn: "建筑提取",
    model: "OCRNet",
    framework: "飞桨 PaddleSeg",
    desc: "城镇建筑物轮廓像素级分割",
    icon: Building2,
    color: "#fb7185",
    intent: "segment",
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
    intent: "segment",
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
    intent: "segment",
  },
  // 目标检测
  {
    id: "m-ship",
    category: "目标检测",
    cn: "船舶检测",
    model: "PP-YOLOE-R",
    framework: "飞桨 PaddleDetection",
    desc: "DOTA 旋转框：港口船舶识别",
    icon: Ship,
    color: "#fbbf24",
    intent: "detect",
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
    intent: "detect",
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
    intent: "detect",
  },
];

export const MODEL_CATEGORIES = ["基础处理", "指数分析", "地物分类", "目标检测"] as const;
