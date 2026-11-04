import { LayoutDashboard, Boxes, ListTodo, Database, FileBarChart, Satellite, Network } from "lucide-react";

const ITEMS = [
  { id: "workspace", label: "智能工作台", icon: LayoutDashboard },
  { id: "satellite", label: "星地协同", icon: Satellite },
  { id: "ontology", label: "功能图谱", icon: Network },
  { id: "tools", label: "模型工具", icon: Boxes },
  { id: "data", label: "数据管理", icon: Database },
  { id: "tasks", label: "任务中心", icon: ListTodo },
  { id: "reports", label: "分析报告", icon: FileBarChart },
] as const;

export function TaskBar({ activeSection, onOpenWorkspace, onOpenTools, onOpenData, onOpenTasks, onOpenReports, onOpenSearch, onOpenOntology }: {
  activeSection: "workspace" | "satellite" | "ontology";
  onOpenWorkspace: () => void; onOpenTools: () => void; onOpenData: () => void;
  onOpenTasks: () => void; onOpenReports: () => void; onOpenSearch: () => void; onOpenOntology: () => void;
}) {
  const actions = { workspace: onOpenWorkspace, satellite: onOpenSearch, ontology: onOpenOntology, tools: onOpenTools, data: onOpenData, tasks: onOpenTasks, reports: onOpenReports };
  return <nav aria-label="主导航" className="flex min-h-0 w-full flex-1 flex-col gap-2 overflow-y-auto py-5">
    {ITEMS.map(({ id, label, icon: Icon }) => <button key={id} type="button" title={label} aria-label={label} aria-current={activeSection === id ? "page" : undefined} onClick={actions[id]}
      className={`flex h-12 shrink-0 items-center justify-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors min-[1100px]:justify-start ${activeSection === id ? "bg-primary/10 text-primary ring-1 ring-primary/20" : "text-foreground/75 hover:bg-muted hover:text-foreground"}`}>
      <Icon className="size-5 shrink-0" /><span className="hidden min-[1100px]:inline">{label}</span>
    </button>)}
  </nav>;
}
