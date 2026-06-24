import { LayoutDashboard, Boxes, ListTodo, Database, FileBarChart } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { slideDown } from "../lib/motion";

interface TaskItem {
  id: string;
  label: string;
  icon: LucideIcon;
}

// Scaffolded task-bar entries. 「模型工具」 opens the models page; the rest are
// placeholders for you to wire up later.
const ITEMS: TaskItem[] = [
  { id: "workspace", label: "工作台", icon: LayoutDashboard },
  { id: "tools", label: "模型工具", icon: Boxes },
  { id: "tasks", label: "任务队列", icon: ListTodo },
  { id: "data", label: "数据管理", icon: Database },
  { id: "reports", label: "分析报告", icon: FileBarChart },
];

export function TaskBar({
  onOpenTools,
  onOpenData,
  onOpenTasks,
  onOpenReports,
}: {
  onOpenTools: () => void;
  onOpenData: () => void;
  onOpenTasks: () => void;
  onOpenReports: () => void;
}) {
  const handle = (id: string) => {
    if (id === "tools") onOpenTools();
    else if (id === "data") onOpenData();
    else if (id === "tasks") onOpenTasks();
    else if (id === "reports") onOpenReports();
    // 「工作台」为当前主视图，无需额外动作
  };

  const reduce = useReducedMotion();

  return (
    <motion.nav
      variants={reduce ? undefined : slideDown}
      initial={reduce ? false : "hidden"}
      animate="show"
      className="absolute inset-x-0 top-14 z-30 flex h-11 items-center gap-1 border-b border-border bg-background/60 px-3 backdrop-blur-xl"
    >
      {ITEMS.map((it) => {
        const Icon = it.icon;
        const active = it.id === "workspace";
        return (
          <button
            key={it.id}
            onClick={() => handle(it.id)}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] transition-colors ${
              active
                ? "bg-card text-foreground"
                : "text-muted-foreground hover:bg-card/60 hover:text-foreground"
            }`}
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
    </motion.nav>
  );
}
