import { BarChart3, Crosshair, Download, FileText, Image as ImageIcon, Layers3, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import type {
  GeospatialCompositeResult,
  GeospatialDetectionResult,
  GeospatialNdviResult,
  GeospatialReportResult,
  GeospatialResult,
  GeospatialSegmentationResult,
  GeospatialSpectralIndexResult,
} from "../types";

// 聊天气泡内的遥感结果摘要卡（紧凑版）。覆盖后端各类 geospatial_result 类型。
// 数据来自真实后端 done 事件解析（chat-events.ts），不再有任何 mock。
// onGenerateReport：分析类结果卡上"生成 Word 报告"按钮的回调（由 useChatController 注入）。
export function GeospatialSummary({
  result,
  onGenerateReport,
  reportPending,
}: {
  result: GeospatialResult;
  onGenerateReport?: (imageryId: string) => void;
  reportPending?: boolean;
}) {
  if (result.type === "report") {
    return <ReportRow result={result} />;
  }
  // 报告按钮：仅对"有分析数据"的结果卡展示（preview 只是预览图层，无分析内容，不出按钮）。
  const reportButton =
    onGenerateReport && result.type !== "preview" ? (
      <ReportButton
        onClick={() => onGenerateReport(result.imagery_id)}
        pending={reportPending}
      />
    ) : null;

  if (result.type === "preview") {
    return <Row icon={<ImageIcon className="size-3.5 text-primary" />} title="原图预览图层已添加" id={result.imagery_id} />;
  }
  if (result.type === "composite") {
    return <CompositeRow result={result} footer={reportButton} />;
  }
  if (result.type === "detection") {
    return <DetectionRow result={result} footer={reportButton} />;
  }
  if (result.type === "segmentation") {
    return <SegmentationRow result={result} footer={reportButton} />;
  }
  return <IndexRow result={result} footer={reportButton} />;
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

function ReportButton({ onClick, pending }: { onClick: () => void; pending?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      className="mt-2 flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-50"
    >
      {pending ? <Loader2 className="size-3 animate-spin" /> : <FileText className="size-3" />}
      生成 Word 报告
    </button>
  );
}

function ReportRow({ result }: { result: GeospatialReportResult }) {
  return (
    <div className="mt-2 rounded-lg border border-primary/30 bg-primary/5 p-2.5 text-[12px]">
      <div className="flex items-center gap-2">
        <FileText className="size-3.5 text-primary" />
        <span className="text-foreground">分析报告已生成（Word）</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {result.imagery_id.slice(0, 8)}
        </span>
      </div>
      <a
        href={result.download_url}
        download={result.filename}
        className="mt-2 flex w-fit items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-2.5 py-1 text-[11px] text-primary transition-colors hover:bg-primary/20"
      >
        <Download className="size-3" />
        下载报告
      </a>
    </div>
  );
}

function IndexRow({
  result,
  footer,
}: {
  result: GeospatialNdviResult | GeospatialSpectralIndexResult;
  footer?: ReactNode;
}) {
  const label = result.type === "ndvi" ? "NDVI" : result.index_type.toUpperCase();
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
      {footer}
    </div>
  );
}

function CompositeRow({ result, footer }: { result: GeospatialCompositeResult; footer?: ReactNode }) {
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
      {footer}
    </div>
  );
}

function DetectionRow({ result, footer }: { result: GeospatialDetectionResult; footer?: ReactNode }) {
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
      {footer}
    </div>
  );
}

function SegmentationRow({ result, footer }: { result: GeospatialSegmentationResult; footer?: ReactNode }) {
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
      {footer}
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
