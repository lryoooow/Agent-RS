import { motion } from "motion/react";
import { X, Database, Brain } from "lucide-react";
import { ScrollArea } from "../ui/scroll-area";
import { KnowledgePanel } from "./KnowledgePanel";
import { MemoryPanel } from "./MemoryPanel";

// Full-screen modal shell matching ToolsPage's overlay pattern. Hosts the
// migrated KnowledgePanel / MemoryPanel (self-contained, endpoint-driven).
function ModalShell({
  title,
  subtitle,
  icon,
  onClose,
  children,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      className="absolute inset-0 z-50 grid place-items-center bg-background/60 p-6 backdrop-blur-md"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 12, scale: 0.98 }}
        transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[82vh] w-full max-w-[960px] flex-col overflow-hidden rounded-3xl border border-border bg-popover shadow-2xl shadow-black/50"
      >
        <div className="flex items-center gap-3 border-b border-border px-5 py-4">
          <span className="grid size-9 place-items-center rounded-xl bg-primary/12 text-primary">
            {icon}
          </span>
          <div className="leading-tight">
            <div className="text-[16px] text-foreground" style={{ fontFamily: "var(--font-display)" }}>
              {title}
            </div>
            <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {subtitle}
            </div>
          </div>
          <button
            onClick={onClose}
            className="ml-auto grid size-8 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>
        <ScrollArea className="min-h-0 flex-1">{children}</ScrollArea>
      </motion.div>
    </motion.div>
  );
}

export function DataModal({ endpoint, onClose }: { endpoint: string; onClose: () => void }) {
  return (
    <ModalShell
      title="数据管理 · 知识库"
      subtitle="文档上传 · 分块 · 向量检索"
      icon={<Database className="size-5" />}
      onClose={onClose}
    >
      <KnowledgePanel endpoint={endpoint} />
    </ModalShell>
  );
}

export function MemoryModal({ endpoint, onClose }: { endpoint: string; onClose: () => void }) {
  return (
    <ModalShell
      title="长期记忆"
      subtitle="对话沉淀的记忆条目"
      icon={<Brain className="size-5" />}
      onClose={onClose}
    >
      <MemoryPanel endpoint={endpoint} />
    </ModalShell>
  );
}
