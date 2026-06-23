import { useState } from "react";
import { FileBarChart, Copy, Check, ImageIcon } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "./ui/sheet";
import { ScrollArea } from "./ui/scroll-area";
import { reportsToMarkdown, type ReportEntry } from "../lib/reports";

// 分析报告抽屉：展示对话中每个遥感结果的结构化统计 + 执行信息，支持「复制为文本」。
// 数据来自真实结果（lib/reports.reportsFromTurns），无 mock。

function ExecBadge({ entry }: { entry: ReportEntry }) {
  if (!entry.execution) return null;
  const { mode, fallback_used } = entry.execution;
  return (
    <span className="rounded border border-border bg-background/50 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
      {mode}
      {fallback_used ? " · 回退" : ""}
    </span>
  );
}

export function AnalysisReportPanel({
  open,
  onOpenChange,
  entries,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entries: ReportEntry[];
}) {
  const [copied, setCopied] = useState(false);

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(reportsToMarkdown(entries));
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // 剪贴板不可用时静默失败（无 https/权限），不阻断面板。
    }
  };

  // 按影像分组展示。
  const groups = new Map<string, ReportEntry[]>();
  for (const e of entries) {
    const arr = groups.get(e.imageryId) ?? [];
    arr.push(e);
    groups.set(e.imageryId, arr);
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-[420px] flex-col gap-0 bg-sidebar p-0 sm:max-w-[420px]">
        <SheetHeader className="border-b border-border px-4 py-3">
          <SheetTitle className="flex items-center gap-2" style={{ fontFamily: "var(--font-display)" }}>
            <FileBarChart className="size-4 text-primary" />
            分析报告
          </SheetTitle>
          <SheetDescription className="flex items-center gap-2 font-mono text-[11px]">
            遥感结果汇总 · 共 {entries.length} 项
            {entries.length > 0 && (
              <button
                onClick={copyAll}
                className="ml-auto flex items-center gap-1 rounded border border-border bg-card px-2 py-0.5 text-foreground transition-colors hover:border-primary/50 hover:text-primary"
              >
                {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
                {copied ? "已复制" : "复制为文本"}
              </button>
            )}
          </SheetDescription>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-4 p-4">
            {entries.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
                <ImageIcon className="size-7 opacity-40" />
                <p className="text-[12px]">暂无分析结果</p>
                <p className="font-mono text-[10px]">运行 NDVI / 检测 / 分割等工具后，结果统计会汇总在这里</p>
              </div>
            ) : (
              [...groups.entries()].map(([imageryId, items]) => (
                <div key={imageryId} className="flex flex-col gap-2">
                  <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    <span className="size-1.5 rounded-full bg-primary" />
                    影像 {imageryId.slice(0, 8)}
                    <span className="h-px flex-1 bg-border" />
                  </div>
                  {items.map((e) => (
                    <div key={e.id} className="rounded-xl border border-border bg-card p-3">
                      <div className="flex items-center gap-2">
                        <span className="text-[12.5px] text-foreground">{e.title}</span>
                        <span className="ml-auto">
                          <ExecBadge entry={e} />
                        </span>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
                        {e.stats.map((s, i) => (
                          <div key={`${e.id}-${i}`} className="flex justify-between gap-2 border-b border-border/40 py-0.5">
                            <span className="font-mono text-[10px] text-muted-foreground">{s.label}</span>
                            <span className="truncate font-mono text-[10px] tabular-nums text-foreground">{s.value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
