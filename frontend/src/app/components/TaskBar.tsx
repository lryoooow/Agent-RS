import { LayoutDashboard, Boxes, Brain, Database, FileBarChart } from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface TaskItem {
  id: string;
  label: string;
  icon: LucideIcon;
  enabled: boolean;
}

// Task-bar entries. 「模型工具」 opens the models page; 「数据管理」 opens the
// knowledge base; 「记忆」 opens long-term memory. 「任务队列」/「分析报告」 are
// placeholders for backend features not yet exposed.
const ITEMS: TaskItem[] = [
  { id: "workspace", label: "工作台", icon: LayoutDashboard, enabled: true },
  { id: "tools", label: "模型工具", icon: Boxes, enabled: true },
  { id: "data", label: "数据管理", icon: Database, enabled: true },
  { id: "memory", label: "记忆", icon: Brain, enabled: true },
  { id: "reports", label: "分析报告", icon: FileBarChart, enabled: false },
];

export function TaskBar({
  onOpenTools,
  onOpenData,
  onOpenMemory,
}: {
  onOpenTools: () => void;
  onOpenData: () => void;
  onOpenMemory: () => void;
}) {
  const handle = (id: string) => {
    if (id === "tools") onOpenTools();
    else if (id === "data") onOpenData();
    else if (id === "memory") onOpenMemory();
  };

  return (
    <nav className="absolute inset-x-0 top-14 z-30 flex h-11 items-center gap-1 border-b border-border bg-background/60 px-3 backdrop-blur-xl">
      {ITEMS.map((it) => {
        const Icon = it.icon;
        const active = it.id === "workspace";
        return (
          <button
            key={it.id}
            onClick={() => it.enabled && handle(it.id)}
            disabled={!it.enabled}
            title={it.enabled ? it.label : `${it.label}（即将推出）`}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] transition-colors ${
              active
                ? "bg-card text-foreground"
                : "text-muted-foreground hover:bg-card/60 hover:text-foreground"
            } ${!it.enabled ? "cursor-not-allowed opacity-40 hover:bg-transparent" : ""}`}
          >
            <Icon className="size-3.5" />
            {it.label}
          </button>
        );
      })}

      <span className="ml-auto hidden items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground md:flex">
        <span className="size-1.5 rounded-full bg-primary" />
        就绪
      </span>
    </nav>
  );
}
