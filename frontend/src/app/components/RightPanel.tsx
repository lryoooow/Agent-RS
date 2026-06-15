import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Eye,
  EyeOff,
  Image as ImageIcon,
  ChevronDown,
  Layers,
  PanelRightClose,
  Crosshair,
} from "lucide-react";
import { ScrollArea } from "./ui/scroll-area";
import { Slider } from "./ui/slider";
import type { GeospatialResult, LegendInfo } from "../types";
import { layerKeyOf, type LayerUiState } from "./MapView";

// ---- per-result presentation helpers (ported from old MapPanel) ----------
function layerLabel(result: GeospatialResult): string {
  const id = result.imagery_id.slice(0, 8);
  if (result.type === "preview") return `原图预览 · ${id}`;
  if (result.type === "ndvi") return `NDVI · ${id}`;
  if (result.type === "spectral_index") return `${result.index_type.toUpperCase()} · ${id}`;
  if (result.type === "composite") return `${compositeLabel(result.mode)} · ${id}`;
  if (result.type === "detection") return `目标检测 · ${id}`;
  if (result.type === "segmentation") return `地物分类 · ${id}`;
  return `图层 · ${id}`;
}

function layerSublabel(result: GeospatialResult): string {
  if (result.type === "ndvi") return `植被指数 · 均值 ${result.stats.mean.toFixed(2)}`;
  if (result.type === "spectral_index") return `${result.index_type.toUpperCase()} · 均值 ${result.stats.mean.toFixed(2)}`;
  if (result.type === "composite") return `波段 ${result.bands_used.join("-")}`;
  if (result.type === "detection") return `${result.detection_count} 个目标 · ${result.classes.length} 类`;
  if (result.type === "segmentation") return `${result.classes.length} 类地物`;
  if (result.type === "preview") return "GeoTIFF 原图";
  return "结果图层";
}

const TYPE_COLOR: Record<GeospatialResult["type"], string> = {
  preview: "#2dd4bf",
  ndvi: "#a3e635",
  spectral_index: "#38bdf8",
  composite: "#a78bfa",
  detection: "#fbbf24",
  segmentation: "#fb7185",
};

function compositeLabel(mode: string) {
  if (mode === "true_color") return "真彩色";
  if (mode === "false_color") return "假彩色";
  return "波段组合";
}

function defaultLegend(result: GeospatialResult): LegendInfo {
  if (result.type === "spectral_index") {
    const t = result.index_type.toLowerCase();
    if (t === "ndbi" || t === "bsi") return { label: t.toUpperCase(), min: -1, max: 1, palette: "built" };
    if (t === "nbr") return { label: "NBR", min: -1, max: 1, palette: "burn" };
    if (t === "ndmi" || t === "ndwi" || t === "mndwi")
      return { label: t.toUpperCase(), min: -1, max: 1, palette: "water" };
    return { label: t.toUpperCase(), min: -1, max: 1, palette: "vegetation" };
  }
  return { label: "NDVI", min: -1, max: 1, palette: "vegetation" };
}

function gradientForPalette(palette: string) {
  if (palette === "water") return "linear-gradient(to right, #7f3b08, #f6e8c3, #67a9cf, #053061)";
  if (palette === "built") return "linear-gradient(to right, #2c7bb6, #ffffbf, #fdae61, #a6611a)";
  if (palette === "burn") return "linear-gradient(to right, #006837, #ffffbf, #fdae61, #a60026)";
  return "linear-gradient(to right, #a60026, #f46d43, #ffffbf, #66bd63, #006837)";
}

function formatTick(v: number) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

function ResultLegend({ result }: { result: GeospatialResult }) {
  if (result.type === "detection") {
    if (!result.classes.length) return <p className="font-mono text-[10px] text-muted-foreground">未检测到目标</p>;
    return (
      <div className="space-y-0.5">
        {result.classes.map((c) => (
          <div key={c.name} className="flex items-center gap-2 py-0.5">
            <span className="size-3 shrink-0 rounded-[3px] ring-1 ring-white/10" style={{ background: c.color }} />
            <span className="font-mono text-[11px] text-muted-foreground">
              {c.label} ({c.count})
            </span>
          </div>
        ))}
      </div>
    );
  }
  if (result.type === "segmentation") {
    if (!result.classes.length) return <p className="font-mono text-[10px] text-muted-foreground">未识别到地物</p>;
    return (
      <div className="space-y-0.5">
        {result.classes.map((c) => (
          <div key={c.name} className="flex items-center gap-2 py-0.5">
            <span className="size-3 shrink-0 rounded-[3px] ring-1 ring-white/10" style={{ background: c.color }} />
            <span className="font-mono text-[11px] text-muted-foreground">
              {c.label} ({c.percentage.toFixed(1)}%)
            </span>
          </div>
        ))}
      </div>
    );
  }
  if (result.type === "ndvi" || result.type === "spectral_index") {
    const legend = result.legend ?? defaultLegend(result);
    return (
      <div className="flex items-center gap-1">
        <span className="w-8 text-right font-mono text-[10px] text-muted-foreground">{formatTick(legend.min)}</span>
        <div className="h-2 flex-1 rounded" style={{ background: gradientForPalette(legend.palette) }} />
        <span className="w-8 font-mono text-[10px] text-muted-foreground">{formatTick(legend.max)}</span>
      </div>
    );
  }
  return null;
}

function hasLegend(result: GeospatialResult) {
  return (
    result.type === "ndvi" ||
    result.type === "spectral_index" ||
    result.type === "detection" ||
    result.type === "segmentation"
  );
}

// ---- layer entry shown in the panel --------------------------------------
export type PanelLayer = {
  key: string;
  result: GeospatialResult;
  hasGeo: boolean;
};

function LayerCard({
  layer,
  ui,
  onToggle,
  onOpacity,
  onFocus,
}: {
  layer: PanelLayer;
  ui: { visible: boolean; opacity: number };
  onToggle: () => void;
  onOpacity: (v: number) => void;
  onFocus: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { result } = layer;
  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: TYPE_COLOR[result.type] }} />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-[12.5px] text-foreground">{layerLabel(result)}</div>
          <div className="truncate font-mono text-[10px] text-muted-foreground">{layerSublabel(result)}</div>
        </div>
        {layer.hasGeo && (
          <button
            onClick={onFocus}
            className="grid size-6 place-items-center rounded text-muted-foreground transition-colors hover:text-primary"
            title="定位到此图层"
          >
            <Crosshair className="size-3.5" />
          </button>
        )}
        <button
          onClick={onToggle}
          className="grid size-6 place-items-center rounded text-muted-foreground transition-colors hover:text-primary"
          title={ui.visible ? "隐藏图层" : "显示图层"}
        >
          {ui.visible ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
        </button>
      </div>

      <div className="px-2.5 pb-2">
        {layer.hasGeo ? (
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-muted-foreground">不透明</span>
            <Slider
              value={[Math.round(ui.opacity * 100)]}
              max={100}
              step={1}
              onValueChange={(v) => onOpacity(v[0] / 100)}
              className="flex-1"
            />
            <span className="w-8 text-right font-mono text-[10px] tabular-nums text-foreground">
              {Math.round(ui.opacity * 100)}%
            </span>
          </div>
        ) : (
          <p className="font-mono text-[10px] text-muted-foreground">无地理坐标 · 以缩略图展示</p>
        )}

        {hasLegend(result) && (
          <>
            <button
              onClick={() => setOpen((v) => !v)}
              className="mt-2 flex w-full items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronDown className={`size-3 transition-transform ${open ? "" : "-rotate-90"}`} />
              图例
            </button>
            {open && (
              <div className="mt-1 rounded-md bg-background/50 p-2">
                <ResultLegend result={result} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function RightPanel({
  results,
  layerUi,
  onToggle,
  onOpacity,
  onFocus,
}: {
  results: GeospatialResult[];
  layerUi: LayerUiState;
  onToggle: (key: string) => void;
  onOpacity: (key: string, v: number) => void;
  onFocus: (result: GeospatialResult) => void;
}) {
  const [open, setOpen] = useState(true);

  const layers: PanelLayer[] = results.map((result, idx) => ({
    key: layerKeyOf(result, idx),
    result,
    hasGeo: Array.isArray(result.bounds) && result.bounds.length === 4,
  }));

  return (
    <motion.div
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1], delay: 0.12 }}
      className="absolute right-4 top-[108px] z-20 flex flex-col items-end"
    >
      <AnimatePresence mode="wait">
        {open ? (
          <motion.div
            key="panel"
            initial={{ opacity: 0, x: 20, scale: 0.985 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 20, scale: 0.985 }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
            className="flex max-h-[calc(100vh-128px)] w-[300px] flex-col overflow-hidden rounded-2xl border border-border bg-sidebar/85 shadow-2xl shadow-black/40 backdrop-blur-xl"
          >
            <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
              <Layers className="size-4 text-primary" />
              <span className="text-[13px] text-foreground">图层</span>
              <span className="font-mono text-[10px] text-muted-foreground">{layers.length}</span>
              <button
                onClick={() => setOpen(false)}
                className="ml-auto grid size-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
                title="收起面板"
              >
                <PanelRightClose className="size-4" />
              </button>
            </div>

            <ScrollArea className="min-h-0 flex-1">
              <div className="flex flex-col gap-2 p-3">
                {layers.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 py-8 text-center text-muted-foreground">
                    <ImageIcon className="size-7 opacity-40" />
                    <p className="text-[12px]">尚无图层</p>
                    <p className="font-mono text-[10px]">上传影像或运行模型后生成</p>
                  </div>
                ) : (
                  layers.map((l) => (
                    <LayerCard
                      key={l.key}
                      layer={l}
                      ui={layerUi[l.key] ?? { visible: true, opacity: 0.85 }}
                      onToggle={() => onToggle(l.key)}
                      onOpacity={(v) => onOpacity(l.key, v)}
                      onFocus={() => onFocus(l.result)}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </motion.div>
        ) : (
          <motion.button
            key="launcher"
            initial={{ opacity: 0, x: 20, scale: 0.9 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 20, scale: 0.9 }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
            onClick={() => setOpen(true)}
            className="flex items-center gap-2 rounded-xl border border-border bg-sidebar/85 px-3 py-2.5 shadow-2xl shadow-black/40 backdrop-blur-xl transition-colors hover:border-primary/40"
            title="展开图层面板"
          >
            <span className="grid size-7 place-items-center rounded-lg bg-primary/12 text-primary">
              <Layers className="size-4" />
            </span>
            <span className="leading-tight text-left">
              <span className="block text-[12px] text-foreground">图层</span>
              <span className="font-mono text-[10px] text-muted-foreground">{layers.length} 个</span>
            </span>
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
