import { useEffect, useState } from "react";
import type { Roi } from "../lib/roi";
import { apiFetch } from "../lib/http";

export type RoiAnalysisSource = "current_map" | "selected_imagery";
type Readiness = { status: "ready" | "blocked" | "choose_imagery" | "missing_roi"; message: string; source: RoiAnalysisSource };

export function RoiAnalysisPanel({ roi, source, activeImageryId, loading, onSourceChange, onRun, onSearch, onClear }: {
  roi: Roi; source: RoiAnalysisSource; activeImageryId: string | null; loading: boolean;
  onSourceChange: (source: RoiAnalysisSource) => void;
  onRun: (target: "building" | "all") => void; onSearch: () => void; onClear: () => void;
}) {
  const [result, setResult] = useState<{key: string; value?: Readiness; error?: string} | null>(null);
  const key = JSON.stringify([roi, source, activeImageryId]);
  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/imagery/roi-buildings/readiness", {method: "POST", signal: controller.signal,
      json: {roi, source, active_imagery_id: activeImageryId}})
      .then((r) => r.json()).then((value: Readiness) => {if (!controller.signal.aborted) setResult({key, value});})
      .catch((e: unknown) => {if (!controller.signal.aborted) setResult({key, error: e instanceof Error ? e.message : "选区检查失败，请重新框选。"});});
    return () => controller.abort();
  }, [key]);
  const current = result?.key === key ? result : null;
  const ready = current?.value?.status === "ready" && !loading;
  return <section aria-label="选区分析" data-testid="roi-analysis-panel"
    className="absolute bottom-[84px] right-4 z-30 w-[min(28rem,calc(100vw-2rem))] max-h-[40vh] overflow-y-auto rounded-xl border border-primary/40 bg-sidebar/95 p-3 text-[12px] shadow-xl backdrop-blur-md">
    <div className="mb-2 flex items-center justify-between gap-2">
      <strong className="text-[14px]">选区已就绪</strong>
      <button onClick={onClear} disabled={loading} className="text-muted-foreground hover:text-foreground disabled:opacity-40">清除选区</button>
    </div>
    <label className="flex items-center gap-2">分析数据
      <select aria-label="选区分析数据" value={source} disabled={loading} onChange={(e) => onSourceChange(e.target.value as RoiAnalysisSource)}
        className="min-w-0 flex-1 rounded border border-border bg-card px-2 py-1">
        <option value="current_map" disabled={roi.kind !== "geo"}>当前地图卫星底图</option>
        <option value="selected_imagery" disabled={!activeImageryId}>当前已选影像</option>
      </select>
    </label>
    <p role="status" className="my-2 break-words leading-relaxed text-muted-foreground">
      {loading ? "正在处理选区，请在对话中查看进度。" : current?.error ?? current?.value?.message ?? "正在检查选区…"}
    </p>
    <div className="flex flex-wrap gap-2">
      <button disabled={!ready} onClick={() => onRun("building")} className="rounded-lg bg-primary px-3 py-2 font-medium text-primary-foreground disabled:opacity-40">提取建筑</button>
      <button disabled={!ready} onClick={() => onRun("all")} className="rounded-lg border border-border px-3 py-2 disabled:opacity-40">地物分类</button>
      <button disabled={roi.kind !== "geo" || loading} onClick={onSearch} className="rounded-lg border border-border px-3 py-2 disabled:opacity-40">搜索此区域影像</button>
    </div>
  </section>;
}
