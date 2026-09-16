import { LayoutDashboard, Boxes, ListTodo, Database, FileBarChart, Satellite, ChevronDown } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "./ui/dropdown-menu";

interface TaskItem {
  id: string;
  label: string;
  icon: LucideIcon;
}

// Main navigation shares the header row with the platform brand.
const ITEMS: TaskItem[] = [
  { id: "workspace", label: "工作台", icon: LayoutDashboard },
  { id: "search", label: "卫星影像", icon: Satellite },
  { id: "tools", label: "模型工具", icon: Boxes },
  { id: "tasks", label: "任务队列", icon: ListTodo },
  { id: "data", label: "数据管理", icon: Database },
  { id: "reports", label: "分析报告", icon: FileBarChart },
];

export function TaskBar({
  activeSection,
  onOpenWorkspace,
  onOpenTools,
  onOpenData,
  onOpenTasks,
  onOpenReports,
  onOpenSearch,
}: {
  activeSection: "workspace" | "satellite";
  onOpenWorkspace: () => void;
  onOpenTools: () => void;
  onOpenData: () => void;
  onOpenTasks: () => void;
  onOpenReports: () => void;
  onOpenSearch: () => void;
}) {
  const handle = (id: string) => {
    if (id === "workspace") onOpenWorkspace();
    else if (id === "tools") onOpenTools();
    else if (id === "data") onOpenData();
    else if (id === "tasks") onOpenTasks();
    else if (id === "reports") onOpenReports();
    else if (id === "search") onOpenSearch();
  };

  const activeItem = ITEMS.find((item) => item.id === (activeSection === "satellite" ? "search" : "workspace")) ?? ITEMS[0];
  const ActiveIcon = activeItem.icon;

  return (
    <nav aria-label="主导航" className="min-w-0">
      <div className="hidden items-center gap-1 xl:flex">
      {ITEMS.map((it) => {
        const Icon = it.icon;
        const active = it.id === (activeSection === "satellite" ? "search" : "workspace");
        return (
          <button
            key={it.id}
            type="button"
            onClick={() => handle(it.id)}
            aria-current={active ? "page" : undefined}
            className={`flex h-11 shrink-0 items-center gap-2 whitespace-nowrap rounded-xl px-3 text-[16px] font-medium transition-colors ${
              active
                ? "bg-primary/12 text-primary ring-1 ring-primary/25"
                : "text-foreground/75 hover:bg-card hover:text-foreground"
            }`}
          >
            <Icon className="size-[18px] shrink-0" />
            {it.label}
          </button>
        );
      })}
      </div>
      <div className="xl:hidden">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" aria-label="打开主导航" className="flex h-11 items-center gap-2 whitespace-nowrap rounded-xl bg-primary/10 px-3 text-[16px] font-medium text-primary ring-1 ring-primary/25">
              <ActiveIcon className="size-[18px]" />{activeItem.label}<ChevronDown className="size-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="center" className="w-48">
            {ITEMS.map(({id,label,icon:Icon}) => (
              <DropdownMenuItem key={id} onSelect={() => handle(id)} className="gap-3 py-2.5 text-[15px]">
                <Icon className="size-[18px]" />{label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </nav>
  );
}
