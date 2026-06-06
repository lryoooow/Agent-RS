import { AlertTriangle, BarChart3, FileSearch, Image as ImageIcon, Layers3 } from "lucide-react";
import type {
  ChatTurn,
  GeospatialCompositeResult,
  GeospatialNdviResult,
  GeospatialResult,
  GeospatialSpectralIndexResult,
  RasterInspectResult,
} from "../../types";
import { AnalysisStatusLine } from "./AnalysisStatusLine";

export function MessageTurn({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === "user";
  const showAnalysis = !isUser && turn.analysisStatus != null && !turn.content;

  if (turn.error) return <ErrorTurn turn={turn} />;

  return (
    <div className={`flex flex-col gap-2 ${isUser ? "items-end" : "items-start"}`}>
      <div
        className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {isUser ? "you" : "assistant"}
      </div>
      {showAnalysis && (
        <AnalysisStatusLine status={turn.analysisStatus!} label={turn.analysisLabel} />
      )}
      {(isUser || turn.content) && (
        <div
          className={`max-w-[88%] whitespace-pre-wrap break-words leading-relaxed ${
            isUser ? "bg-foreground text-background rounded-2xl rounded-tr-sm px-4 py-3" : "text-foreground"
          }`}
        >
          {turn.content}
        </div>
      )}
      {!isUser && turn.toolResult?.type === "raster_inspect" && (
        <RasterInspectCard result={turn.toolResult} />
      )}
      {!isUser && turn.geospatialResult && <GeospatialResultCard result={turn.geospatialResult} />}
      {!isUser && (turn.model || turn.usage) && <MessageMeta turn={turn} />}
    </div>
  );
}

function ErrorTurn({ turn }: { turn: ChatTurn }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4">
      <div
        className="flex items-center gap-2 text-[10px] tracking-[0.18em] uppercase text-destructive"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        <AlertTriangle className="size-3.5" /> request failed
      </div>
      <p
        className="mt-2 text-sm whitespace-pre-wrap break-words"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {turn.content}
      </p>
    </div>
  );
}

function RasterInspectCard({ result }: { result: RasterInspectResult }) {
  const capabilityLabels = [
    result.capabilities.has_blue && "Blue",
    result.capabilities.has_green && "Green",
    result.capabilities.has_red && "Red",
    result.capabilities.has_nir && "NIR",
    result.capabilities.has_swir && "SWIR",
  ].filter(Boolean);
  return (
    <div className="w-full max-w-[88%] rounded-lg border border-border bg-card px-4 py-3 text-sm">
      <div className="flex items-center gap-2 text-foreground">
        <FileSearch className="size-4 text-emerald-500" />
        <span className="font-medium">影像质检完成</span>
        <span className="text-xs text-muted-foreground">{result.imagery_id.slice(0, 8)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground sm:grid-cols-3">
        <Metric label="尺寸" value={`${result.width} x ${result.height}px`} />
        <Metric label="波段" value={`${result.band_count}`} />
        <Metric label="坐标系" value={result.crs ?? "未识别"} />
        <Metric label="分辨率" value={result.pixel_size ? result.pixel_size.join(" x ") : "未知"} />
        <Metric label="类型" value={result.dtype ?? "未知"} />
        <Metric label="NoData" value={result.nodata == null ? "无" : String(result.nodata)} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {capabilityLabels.map((label) => (
          <span key={label} className="rounded border border-emerald-500/30 px-2 py-0.5 text-xs text-emerald-600">
            {label}
          </span>
        ))}
      </div>
      {result.per_band_stats.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-left text-xs text-muted-foreground">
            <thead>
              <tr className="border-b border-border">
                <th className="py-1 pr-3 font-medium">Band</th>
                <th className="py-1 pr-3 font-medium">Min</th>
                <th className="py-1 pr-3 font-medium">Max</th>
                <th className="py-1 pr-3 font-medium">Mean</th>
                <th className="py-1 pr-3 font-medium">Std</th>
              </tr>
            </thead>
            <tbody>
              {result.per_band_stats.slice(0, 8).map((band) => (
                <tr key={band.band} className="border-b border-border/50 last:border-0">
                  <td className="py-1 pr-3">{band.band}</td>
                  <td className="py-1 pr-3">{formatNumber(band.min)}</td>
                  <td className="py-1 pr-3">{formatNumber(band.max)}</td>
                  <td className="py-1 pr-3">{formatNumber(band.mean)}</td>
                  <td className="py-1 pr-3">{formatNumber(band.std)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function GeospatialResultCard({ result }: { result: GeospatialResult }) {
  if (result.type === "preview") {
    return <LayerSummary icon="image" title="原图预览图层已添加" subtitle={result.imagery_id} />;
  }
  if (result.type === "composite") {
    return <CompositeCard result={result} />;
  }
  return <IndexCard result={result} />;
}

function IndexCard({ result }: { result: GeospatialNdviResult | GeospatialSpectralIndexResult }) {
  const label = result.type === "ndvi" ? "NDVI" : result.index_type.toUpperCase();
  const nodataPct = result.type === "spectral_index" ? result.stats.nodata_pct : undefined;
  return (
    <div className="w-full max-w-[88%] rounded-lg border border-border bg-card px-4 py-3 text-sm">
      <div className="flex items-center gap-2">
        <BarChart3 className="size-4 text-emerald-500" />
        <span className="font-medium">{label} 图层已生成</span>
        <span className="text-xs text-muted-foreground">{result.imagery_id.slice(0, 8)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground sm:grid-cols-5">
        <Metric label="Min" value={formatNumber(result.stats.min)} />
        <Metric label="Max" value={formatNumber(result.stats.max)} />
        <Metric label="Mean" value={formatNumber(result.stats.mean)} />
        <Metric label="Std" value={formatNumber(result.stats.std)} />
        {nodataPct != null && <Metric label="NoData" value={`${formatNumber(nodataPct)}%`} />}
      </div>
    </div>
  );
}

function CompositeCard({ result }: { result: GeospatialCompositeResult }) {
  return (
    <div className="w-full max-w-[88%] rounded-lg border border-border bg-card px-4 py-3 text-sm">
      <div className="flex items-center gap-2">
        <Layers3 className="size-4 text-emerald-500" />
        <span className="font-medium">{compositeLabel(result.mode)} 图层已生成</span>
        <span className="text-xs text-muted-foreground">{result.imagery_id.slice(0, 8)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
        <Metric label="模式" value={compositeLabel(result.mode)} />
        <Metric label="波段" value={result.bands_used.join(" / ")} />
      </div>
    </div>
  );
}

function LayerSummary({ icon, title, subtitle }: { icon: "image"; title: string; subtitle: string }) {
  return (
    <div className="flex max-w-[88%] items-center gap-2 rounded-lg border border-border bg-card px-4 py-3 text-sm">
      {icon === "image" && <ImageIcon className="size-4 text-emerald-500" />}
      <span className="font-medium">{title}</span>
      <span className="text-xs text-muted-foreground">{subtitle.slice(0, 8)}</span>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground/70">{label}</div>
      <div className="truncate text-foreground">{value}</div>
    </div>
  );
}

function MessageMeta({ turn }: { turn: ChatTurn }) {
  return (
    <div
      className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] tracking-[0.14em] uppercase text-muted-foreground pt-1"
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    >
      {turn.model && <span>model / {turn.model}</span>}
      {turn.provider && <span>provider / {turn.provider}</span>}
      {turn.usage?.total_tokens != null && (
        <span>
          tokens / {turn.usage.input_tokens ?? "?"} → {turn.usage.output_tokens ?? "?"} →{" "}
          {turn.usage.total_tokens}
        </span>
      )}
      {turn.finishReason && <span>finish / {turn.finishReason}</span>}
      {turn.retrievedChunks != null && turn.retrievedChunks > 0 && (
        <span>参考了 {turn.retrievedChunks} 段文档</span>
      )}
      {turn.ragTrace && (
        <details className="basis-full pt-1 normal-case tracking-normal">
          <summary className="cursor-pointer">RAG trace</summary>
          <pre className="mt-1 max-w-[88vw] overflow-x-auto text-[10px] leading-relaxed">
            {JSON.stringify(turn.ragTrace, null, 2)}
          </pre>
        </details>
      )}
      {turn.agentTrace && (
        <details className="basis-full pt-1 normal-case tracking-normal">
          <summary className="cursor-pointer">Agent trace</summary>
          <pre className="mt-1 max-w-[88vw] overflow-x-auto text-[10px] leading-relaxed">
            {JSON.stringify(turn.agentTrace, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function compositeLabel(mode: string) {
  if (mode === "true_color") return "真彩色";
  if (mode === "false_color") return "假彩色";
  return "波段组合";
}

function formatNumber(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "N/A";
  if (Math.abs(value) >= 100) return value.toFixed(1);
  return value.toFixed(4).replace(/\.?0+$/, "");
}
