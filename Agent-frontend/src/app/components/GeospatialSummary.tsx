import { BarChart3, Crosshair, Image as ImageIcon, Layers3 } from "lucide-react";
import type { ReactNode } from "react";
import type {
  GeospatialCompositeResult,
  GeospatialDetectionResult,
  GeospatialNdviResult,
  GeospatialResult,
  GeospatialSegmentationResult,
  GeospatialSpectralIndexResult,
} from "../types";

// 聊天气泡内的遥感结果摘要卡（紧凑版）。覆盖后端六种 geospatial_result 类型。
// 数据来自真实后端 done 事件解析（chat-events.ts），不再有任何 mock。
export function GeospatialSummary({ result }: { result: GeospatialResult }) {
  if (result.type === "preview") {
    return <Row icon={<ImageIcon className="size-3.5 text-primary" />} title="原图预览图层已添加" id={result.imagery_id} />;
  }
  if (result.type === "composite") {
    return <CompositeRow result={result} />;
  }
  if (result.type === "detection") {
    return <DetectionRow result={result} />;
  }
  if (result.type === "segmentation") {
    return <SegmentationRow result={result} />;
  }
  return <IndexRow result={result} />;
}

function Row({ icon, title, id }: { icon: ReactNode; title: string; id: string }) {
  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg border border-border bg-background/50 p-2.5 text-[12px]">
      {icon}
      <span className="text-foreground">{title}</span>
      <span className="ml-auto font-mono text-[10px] text-muted-foreground">{id.slice(0, 8)}</span>
    </div>
  );
}

function IndexRow({ result }: { result: GeospatialNdviResult | GeospatialSpectralIndexResult }) {  const label = result.type === "ndvi" ? "NDVI" : result.index_type.toUpperCase();
  return (
    <div className="mt-2 rounded-lg border border-border bg-background/50 p-2.5 text-[12px]">
      <div className="flex items-center gap-2">
        <BarChart3 className="size-3.5 text-primary" />
        <span className="text-foreground">{label} 图层已生成</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {result.imagery_id.slice(0, 8)}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] tabular-nums text-muted-foreground">
        <span>min {fmt(result.stats.min)}</span>
        <span>max {fmt(result.stats.max)}</span>
        <span>mean {fmt(result.stats.mean)}</span>
        <span>std {fmt(result.stats.std)}</span>
      </div>
    </div>
  );
}

function CompositeRow({ result }: { result: GeospatialCompositeResult }) {
  return (
    <div className="mt-2 rounded-lg border border-border bg-background/50 p-2.5 text-[12px]">
      <div className="flex items-center gap-2">
        <Layers3 className="size-3.5 text-primary" />
        <span className="text-foreground">{compositeLabel(result.mode)} 图层已生成</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {result.imagery_id.slice(0, 8)}
        </span>
      </div>
      <div className="mt-1.5 font-mono text-[11px] text-muted-foreground">
        波段 {result.bands_used.join(" / ")}
      </div>
    </div>
  );
}

function DetectionRow({ result }: { result: GeospatialDetectionResult }) {
  return (
    <div className="mt-2 rounded-lg border border-border bg-background/50 p-2.5 text-[12px]">
      <div className="flex items-center gap-2">
        <Crosshair className="size-3.5 text-primary" />
        <span className="text-foreground">目标检测完成 · {result.detection_count} 个目标</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {result.imagery_id.slice(0, 8)}
        </span>
      </div>
      {result.classes.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {result.classes.slice(0, 8).map((c) => (
            <span key={c.name} className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
              <span className="size-2 rounded-sm" style={{ backgroundColor: c.color }} />
              {c.label || c.name} {c.count}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function SegmentationRow({ result }: { result: GeospatialSegmentationResult }) {
  return (
    <div className="mt-2 rounded-lg border border-border bg-background/50 p-2.5 text-[12px]">
      <div className="flex items-center gap-2">
        <Layers3 className="size-3.5 text-primary" />
        <span className="text-foreground">地物分类完成 · {result.classes.length} 类</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {result.imagery_id.slice(0, 8)}
        </span>
      </div>
      {result.classes.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {result.classes.slice(0, 8).map((c) => (
            <span key={c.name} className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
              <span className="size-2 rounded-sm" style={{ backgroundColor: c.color }} />
              {c.label || c.name} {fmt(c.percentage)}%
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function compositeLabel(mode: string) {
  if (mode === "true_color") return "真彩色";
  if (mode === "false_color") return "假彩色";
  return "波段组合";
}

function fmt(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "N/A";
  if (Math.abs(value) >= 100) return value.toFixed(1);
  return value.toFixed(3).replace(/\.?0+$/, "");
}
