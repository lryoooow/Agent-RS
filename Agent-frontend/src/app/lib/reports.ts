import type {
  ChatTurn,
  GeospatialResult,
  RasterInspectResult,
  ToolExecutionInfo,
} from "../types";

// 分析报告：把对话中每个遥感结果投影成一条结构化报告项。纯函数、可单测、零 mock。
// 数据来源是真实的 turn.geospatialResult / turn.toolResult（后端 done 事件解析所得）。
// 不做任何意图判断，只把已有结果整理成「可读 + 可导出」的报告。

export type ReportStat = { label: string; value: string };

export type ReportEntry = {
  id: string;
  turnId: string;
  imageryId: string;
  kind: string; // 中文类型名
  title: string;
  stats: ReportStat[];
  execution?: ToolExecutionInfo | null;
};

function fmt(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "N/A";
  if (Math.abs(value) >= 100) return value.toFixed(1);
  return value.toFixed(3).replace(/\.?0+$/, "");
}

function entryFromGeospatial(turn: ChatTurn, r: GeospatialResult): ReportEntry | null {
  const base = { id: `${turn.id}-geo`, turnId: turn.id, imageryId: r.imagery_id };
  switch (r.type) {
    case "preview":
      return null; // 预览不算分析结果
    case "report":
      return null; // 报告本身是导出成果物，不作为报告项再列入
    case "ndvi":
      return {
        ...base,
        kind: "NDVI 植被指数",
        title: "NDVI 计算",
        stats: [
          { label: "min", value: fmt(r.stats.min) },
          { label: "max", value: fmt(r.stats.max) },
          { label: "mean", value: fmt(r.stats.mean) },
          { label: "std", value: fmt(r.stats.std) },
        ],
        execution: r.execution,
      };
    case "spectral_index":
      return {
        ...base,
        kind: `光谱指数 · ${r.index_type.toUpperCase()}`,
        title: `${r.index_type.toUpperCase()} 计算`,
        stats: [
          { label: "min", value: fmt(r.stats.min) },
          { label: "max", value: fmt(r.stats.max) },
          { label: "mean", value: fmt(r.stats.mean) },
          { label: "std", value: fmt(r.stats.std) },
          ...(r.stats.nodata_pct != null
            ? [{ label: "nodata%", value: fmt(r.stats.nodata_pct) }]
            : []),
        ],
        execution: r.execution,
      };
    case "composite":
      return {
        ...base,
        kind: "波段组合",
        title: r.mode === "true_color" ? "真彩色合成" : r.mode === "false_color" ? "假彩色合成" : "波段组合",
        stats: [{ label: "波段", value: r.bands_used.join(" / ") }],
        execution: r.execution,
      };
    case "detection":
      return {
        ...base,
        kind: "目标检测",
        title: `目标检测 · ${r.detection_count} 个目标`,
        stats: [
          { label: "目标总数", value: String(r.detection_count) },
          { label: "阈值", value: fmt(r.score_threshold) },
          ...r.classes.map((c) => ({ label: c.label || c.name, value: `${c.count}` })),
        ],
        execution: r.execution,
      };
    case "segmentation":
      return {
        ...base,
        kind: "地物分类",
        title: `地物分类 · ${r.classes.length} 类`,
        stats: [
          { label: "总像元", value: String(r.total_pixels) },
          ...r.classes.map((c) => ({ label: c.label || c.name, value: `${fmt(c.percentage)}%` })),
        ],
        execution: r.execution,
      };
  }
}

function entryFromToolResult(turn: ChatTurn, r: RasterInspectResult): ReportEntry {
  return {
    id: `${turn.id}-tool`,
    turnId: turn.id,
    imageryId: r.imagery_id,
    kind: "影像质检",
    title: "影像质检",
    stats: [
      { label: "尺寸", value: `${r.width} × ${r.height}` },
      { label: "波段数", value: String(r.band_count) },
      { label: "坐标系", value: r.crs ?? "无" },
      { label: "数据类型", value: r.dtype ?? "N/A" },
    ],
    execution: r.execution,
  };
}

/** 汇总所有 turn 的分析结果为报告项列表（按出现顺序）。 */
export function reportsFromTurns(turns: ChatTurn[]): ReportEntry[] {
  const out: ReportEntry[] = [];
  for (const turn of turns) {
    if (turn.geospatialResult) {
      const entry = entryFromGeospatial(turn, turn.geospatialResult);
      if (entry) out.push(entry);
    }
    if (turn.toolResult) {
      out.push(entryFromToolResult(turn, turn.toolResult));
    }
  }
  return out;
}

/** 把报告项导出为 Markdown 文本（前端「复制为文本」用，不引依赖）。 */
export function reportsToMarkdown(entries: ReportEntry[]): string {
  if (entries.length === 0) return "（暂无分析结果）";
  const blocks = entries.map((e) => {
    const head = `## ${e.title}\n\n- 影像：${e.imageryId.slice(0, 8)}\n- 类型：${e.kind}`;
    const exec = e.execution
      ? `\n- 执行：${e.execution.mode}${e.execution.fallback_used ? "（本地回退）" : ""}`
      : "";
    const table =
      "\n\n| 指标 | 值 |\n| --- | --- |\n" +
      e.stats.map((s) => `| ${s.label} | ${s.value} |`).join("\n");
    return head + exec + table;
  });
  return blocks.join("\n\n");
}
