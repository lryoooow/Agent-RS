import { ListTodo, Loader2, Check, AlertTriangle, ImageIcon } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "./ui/sheet";
import { ScrollArea } from "./ui/scroll-area";
import type { QueueTask } from "../lib/tasks";

// 任务队列抽屉：展示对话中每次工具执行（running/done/failed + 耗时 + 关联影像）。
// 数据来自真实执行轨迹（lib/tasks.tasksFromTurns），无 mock。

function fmtElapsed(ms?: number): string {
  if (ms == null || !Number.isFinite(ms)) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function StatusIcon({ status }: { status: QueueTask["status"] }) {
  if (status === "running") return <Loader2 className="size-3.5 animate-spin text-primary" />;
  if (status === "failed") return <AlertTriangle className="size-3.5 text-destructive" />;
  return <Check className="size-3.5 text-primary" />;
}

export function TaskQueuePanel({
  open,
  onOpenChange,
  tasks,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tasks: QueueTask[];
}) {
  const ordered = [...tasks].reverse(); // 最新在上
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-[420px] flex-col gap-0 bg-sidebar p-0 sm:max-w-[420px]">
        <SheetHeader className="border-b border-border px-4 py-3">
          <SheetTitle className="flex items-center gap-2" style={{ fontFamily: "var(--font-display)" }}>
            <ListTodo className="size-4 text-primary" />
            任务队列
          </SheetTitle>
          <SheetDescription className="font-mono text-[11px]">
            工具执行记录 · 共 {tasks.length} 项
          </SheetDescription>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-2 p-4">
            {ordered.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
                <ImageIcon className="size-7 opacity-40" />
                <p className="text-[12px]">暂无任务</p>
                <p className="font-mono text-[10px]">上传影像并发起遥感分析后，执行记录会出现在这里</p>
              </div>
            ) : (
              ordered.map((t) => (
                <div
                  key={t.id}
                  className={`rounded-xl border bg-card px-3 py-2.5 ${
                    t.status === "failed" ? "border-destructive/40" : "border-border"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <StatusIcon status={t.status} />
                    <span className="text-[12.5px] text-foreground">{t.label}</span>
                    {t.elapsedMs != null && (
                      <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground">
                        {fmtElapsed(t.elapsedMs)}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
                    {t.toolName && <span>{t.toolName}</span>}
                    {t.imageryId && <span className="ml-auto">{t.imageryId.slice(0, 8)}</span>}
                  </div>
                  {t.error && (
                    <div className="mt-1 rounded-md bg-destructive/5 px-2 py-1 font-mono text-[10px] text-destructive">
                      {t.error}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
