import { BarChart3, CheckCircle2, Crosshair, Download, Eye, FileText, Image as ImageIcon, Layers3, Loader2, PlusCircle, Satellite } from "lucide-react";
import { useState, type ReactNode } from "react";
import type {
  GeospatialCompositeResult,
  GeospatialDetectionResult,
  GeospatialInstanceSegmentationResult,
  GeospatialNdviResult,
  GeospatialReportResult,
  GeospatialResult,
  GeospatialSceneSearchResult,
  GeospatialSegmentationResult,
  GeospatialSpectralIndexResult,
  SceneCardInfo,
} from "../types";
import { absoluteUrl, downloadSceneTif } from "../lib/imagery-search-api";

// 聊天气泡内的遥感结果摘要卡（紧凑版）。覆盖后端各类 geospatial_result 类型。
// 数据来自真实后端 done 事件解析（chat-events.ts），不再有任何 mock。
// onGenerateReport：分析类结果卡上"生成 Word 报告"按钮的回调（由 useChatController 注入）。
export function GeospatialSummary({
  result,
  onGenerateReport,
  reportPending,
  onScenePreview,
  onSceneImport,
}: {
  result: GeospatialResult;
  onGenerateReport?: (imageryId: string) => void;
  reportPending?: boolean;
  // 影像检索卡片：预览定位 / 导入平台的回调（由 App 注入，经 AgentChat 穿线）。
  onScenePreview?: (scene: SceneCardInfo) => void;
  onSceneImport?: (sceneKey: string) => Promise<string | null>;
}) {
  if (result.type === "report") {
    return <ReportRow result={result} />;
  }
  if (result.type === "scene_search") {
    return <SceneSearchRow result={result} onPreview={onScenePreview} onImport={onSceneImport} />;
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
  if (result.type === "instance_segmentation") {
    return <InstanceSegmentationRow result={result} footer={reportButton} />;
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
      {result.model_name && <div className="mt-1.5 text-[11px] text-muted-foreground">{result.model_name} · RGB {result.bands_used?.join(" / ")}</div>}
      <div className="mt-2 flex flex-wrap gap-3 text-primary">
        {result.vector_url?.startsWith(`/api/imagery/${result.imagery_id}/results/`) && <a href={result.vector_url} download className="underline">下载检测矢量</a>}
        {result.detections_url?.startsWith(`/api/imagery/${result.imagery_id}/results/`) && <a href={result.detections_url} download className="underline">下载检测明细</a>}
        <a href="/open-source/index.html" target="_blank" rel="noreferrer" className="text-muted-foreground underline">开源许可</a>
      </div>
      {footer}
    </div>
  );
}

function SegmentationRow({ result, footer }: { result: GeospatialSegmentationResult; footer?: ReactNode }) {
  return (
    <div className="mt-2 rounded-lg border border-border bg-background/50 p-2.5 text-[12px]">
      <div className="flex items-center gap-2">
        <Layers3 className="size-3.5 text-primary" />
        <span className="text-foreground">{result.target_class === "building" ? "建筑提取完成" : `地物分类完成 · ${result.classes.length} 类`}</span>
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
      <div className="mt-2 flex flex-wrap gap-3 text-primary">
        {result.building_mask_url?.startsWith(`/api/imagery/${result.imagery_id}/results/`) && <a href={result.building_mask_url} download className="underline">下载建筑掩膜</a>}
        {result.raster_url?.startsWith(`/api/imagery/${result.imagery_id}/results/`) && <a href={result.raster_url} download className="underline">下载完整分类</a>}
      </div>
      {footer}
    </div>
  );
}

function InstanceSegmentationRow({ result, footer }: { result: GeospatialInstanceSegmentationResult; footer?: ReactNode }) {
  const safe = (url: string | null | undefined) => url?.startsWith(`/api/imagery/${result.imagery_id}/results/`);
  return (
    <div className="mt-2 rounded-lg border border-primary/30 bg-primary/5 p-2.5 text-[12px]">
      <div className="flex items-center gap-2">
        <Layers3 className="size-3.5 text-primary" />
        <span className="text-foreground">SAM3 实例分割完成 · {result.instance_count} 个目标</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">{result.imagery_id.slice(0, 8)}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-2 font-mono text-[10px] text-muted-foreground">
        {Object.entries(result.counts).map(([concept, count]) => <span key={concept}>{concept} {count}</span>)}
        {result.area_m2 != null && <span>掩膜面积约 {fmt(result.area_m2)} m²</span>}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-primary">
        {safe(result.mask_url) && <a href={result.mask_url!} download className="underline">下载合并掩膜</a>}
        {safe(result.instance_raster_url) && <a href={result.instance_raster_url!} download className="underline">下载实例栅格</a>}
        {safe(result.vector_url) && <a href={result.vector_url!} download className="underline">下载实例矢量</a>}
        {safe(result.instances_url) && <a href={result.instances_url!} download className="underline">下载实例明细</a>}
      </div>
      <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">SAM3 开放词汇识别结果，数量、轮廓和面积需结合原始影像复核。</p>
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


function SceneSearchRow({
  result,
  onPreview,
  onImport,
}: {
  result: GeospatialSceneSearchResult;
  onPreview?: (scene: SceneCardInfo) => void;
  onImport?: (sceneKey: string) => Promise<string | null>;
}) {
  const [importing, setImporting] = useState<string | null>(null);
  const [imported, setImported] = useState<Record<string, string>>({});
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState<Record<string, string>>({});

  const runDownload = async (scene: SceneCardInfo) => {
    setDownloading(scene.key);
    try {
      const result = await downloadSceneTif(scene.key, scene.item_id);
      const sizeMb = (result.sizeBytes / 1024 / 1024).toFixed(1);
      setDownloaded((prev) => ({ ...prev, [scene.key]: `${result.filename}（${sizeMb} MB）` }));
    } catch (exc) {
      setDownloaded((prev) => ({
        ...prev,
        [scene.key]: `下载失败：${exc instanceof Error ? exc.message : "未知错误"}`,
      }));
    } finally {
      setDownloading(null);
    }
  };

  const runImport = async (scene: SceneCardInfo) => {
    if (!onImport) return;
    setImporting(scene.key);
    try {
      const imageryId = await onImport(scene.key);
      if (imageryId) setImported((prev) => ({ ...prev, [scene.key]: imageryId }));
    } finally {
      setImporting(null);
    }
  };

  return (
    <div className="mt-2 rounded-lg border border-primary/30 bg-primary/5 p-2.5 text-[12px]">
      <div className="flex items-center gap-2">
        <Satellite className="size-3.5 text-primary" />
        <span className="text-foreground">
          找到 {result.scenes.length} 景卫星影像（可预览 / 下载 TIF / 导入分析）
        </span>
      </div>
      {result.notes && result.notes.length > 0 && (
        <p className="mt-1 text-[10px] text-muted-foreground">{result.notes.join("；")}</p>
      )}
      <div className="mt-2 flex flex-col gap-1.5">
        {result.scenes.map((scene) => {
          const done = imported[scene.key];
          return (
            <div
              key={scene.key}
              className="flex flex-wrap items-center gap-2.5 rounded-lg border border-border bg-background/50 p-2"
            >
              <img
                src={absoluteUrl(scene.preview_url)}
                alt={scene.display_name || scene.item_id}
                loading="lazy"
                className="size-11 shrink-0 rounded-md border border-border object-cover"
              />
              <div className="min-w-[100px] flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-[11.5px] font-medium">{scene.satellite}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {scene.resolution_m ?? "?"}m
                  </span>
                </div>
                <p className="truncate font-mono text-[10px] text-muted-foreground">
                  {scene.datetime.slice(0, 10)} · 云量{" "}
                  {scene.cloud_cover != null ? `${scene.cloud_cover}%` : "—"} · {scene.item_id}
                </p>
              </div>
              <div className="ml-auto flex shrink-0 flex-wrap items-center gap-1">
                <button
                  type="button"
                  onClick={() => onPreview?.(scene)}
                  className="flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[10.5px] transition-colors hover:border-primary/50 hover:text-primary"
                >
                  <Eye className="size-3" /> 预览
                </button>
                <button
                  type="button"
                  disabled={downloading === scene.key}
                  onClick={() => runDownload(scene)}
                  className="flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[10.5px] transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-50"
                >
                  {downloading === scene.key ? (
                    <Loader2 className="size-3 animate-spin" />
                  ) : (
                    <Download className="size-3" />
                  )}
                  {downloading === scene.key ? "合成中" : "TIF"}
                </button>
                {done ? (
                  <span className="flex items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-[10.5px] text-primary">
                    <CheckCircle2 className="size-3" /> 已导入
                  </span>
                ) : (
                  <button
                    type="button"
                    disabled={!onImport || importing === scene.key}
                    onClick={() => runImport(scene)}
                    className="flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[10.5px] transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-50"
                  >
                    {importing === scene.key ? (
                      <Loader2 className="size-3 animate-spin" />
                    ) : (
                      <PlusCircle className="size-3" />
                    )}
                    导入
                  </button>
                )}
              </div>
              {downloaded[scene.key] && (
                <p className="font-mono text-[10px] text-muted-foreground">
                  {downloaded[scene.key]}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
