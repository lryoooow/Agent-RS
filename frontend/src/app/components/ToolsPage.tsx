import { motion } from "motion/react";
import { X, Play, Boxes } from "lucide-react";
import { ScrollArea } from "./ui/scroll-area";
import { Badge } from "./ui/badge";
import { MODELS, MODEL_CATEGORIES, type ModelTool } from "../data/rs";

function ModelCard({ m, onRun }: { m: ModelTool; onRun: () => void }) {
  const Icon = m.icon;
  return (
    <button
      onClick={onRun}
      className="group flex flex-col rounded-2xl border border-border bg-card/70 p-3.5 text-left transition-colors hover:border-primary/40 hover:bg-card"
    >
      <div className="flex items-center gap-2.5">
        <span
          className="grid size-9 shrink-0 place-items-center rounded-xl"
          style={{ background: `${m.color}1f`, color: m.color }}
        >
          <Icon className="size-[18px]" />
        </span>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[13.5px] text-foreground">{m.cn}</div>
          <div className="truncate font-mono text-[10px] text-muted-foreground">{m.model}</div>
        </div>
        <Play className="ml-auto size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-hover:text-primary" />
      </div>
      <p className="mt-2.5 text-[12px] leading-relaxed text-muted-foreground">{m.desc}</p>
      <Badge
        variant="outline"
        className="mt-2.5 w-fit border-primary/20 bg-primary/5 px-2 py-0.5 font-mono text-[10px] font-normal text-primary"
      >
        {m.framework}
      </Badge>
    </button>
  );
}

export function ToolsPage({
  onClose,
  onRun,
}: {
  onClose: () => void;
  onRun: (intent: string, label: string) => void;
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
        className="flex max-h-[82vh] w-full max-w-[920px] flex-col overflow-hidden rounded-3xl border border-border bg-popover shadow-2xl shadow-black/50"
      >
        {/* header */}
        <div className="flex items-center gap-3 border-b border-border px-5 py-4">
          <span className="grid size-9 place-items-center rounded-xl bg-primary/12 text-primary">
            <Boxes className="size-5" />
          </span>
          <div className="leading-tight">
            <div className="text-[16px] text-foreground" style={{ fontFamily: "var(--font-display)" }}>
              模型工具
            </div>
            <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {MODELS.length} models · 按类别选择算法模型
            </div>
          </div>
          <button
            onClick={onClose}
            className="ml-auto grid size-8 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* body */}
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-6 p-5">
            {MODEL_CATEGORIES.map((cat) => {
              const items = MODELS.filter((m) => m.category === cat);
              if (!items.length) return null;
              return (
                <div key={cat}>
                  <div className="mb-3 flex items-center gap-2">
                    <span className="text-[13px] text-foreground">{cat}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {items.length}
                    </span>
                    <span className="h-px flex-1 bg-border" />
                  </div>
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                    {items.map((m) => (
                      <ModelCard
                        key={m.id}
                        m={m}
                        onRun={() => m.intent && onRun(m.intent, m.cn)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </motion.div>
    </motion.div>
  );
}
