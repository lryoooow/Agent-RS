import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Eye,
  EyeOff,
  Trash2,
  Image as ImageIcon,
  ChevronDown,
  Layers,
  PanelRightClose,
} from "lucide-react";
import { Slider } from "./ui/slider";
import { type RSLayer } from "../lib/layers";
import { useLayerPanelSize } from "../hooks/useLayerPanelSize";

function LegendRow({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex min-w-0 items-start gap-2 py-0.5">
      <span
        className="size-3 shrink-0 rounded-[3px] ring-1 ring-white/10"
        style={{ background: color }}
      />
      <span className="min-w-0 break-words font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">{label}</span>
    </div>
  );
}

function LayerCard({
  layer,
  onToggle,
  onOpacity,
  onRemove,
}: {
  layer: RSLayer;
  onToggle: () => void;
  onOpacity: (v: number) => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card">
      <div className="flex min-w-0 items-start gap-2 px-2.5 py-2">
        <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: layer.color }} />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="break-words text-[12.5px] text-foreground [overflow-wrap:anywhere]">{layer.name}</div>
          <div className="break-words font-mono text-[10px] text-muted-foreground [overflow-wrap:anywhere]">
            {layer.sublabel}
          </div>
        </div>
        <button
          onClick={onToggle}
          aria-label={`${layer.visible ? "隐藏" : "显示"}${layer.name} ${layer.id}`}
          className="grid size-6 place-items-center rounded text-muted-foreground transition-colors hover:text-primary"
        >
          {layer.visible ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
        </button>
        {layer.kind !== "imagery" && (
          <button
            onClick={onRemove}
            aria-label={`移除${layer.name} ${layer.id}`}
            className="grid size-6 place-items-center rounded text-muted-foreground transition-colors hover:text-destructive"
          >
            <Trash2 className="size-3.5" />
          </button>
        )}
      </div>

      <div className="px-2.5 pb-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-muted-foreground">不透明</span>
          <Slider
            aria-label={`${layer.name}不透明度`}
            value={[Math.round(layer.opacity * 100)]}
            max={100}
            step={1}
            onValueChange={(v) => onOpacity(v[0] / 100)}
            className="flex-1"
          />
          <span className="w-8 text-right font-mono text-[10px] tabular-nums text-foreground">
            {Math.round(layer.opacity * 100)}%
          </span>
        </div>

        {layer.legend && (
          <>
            <button
              onClick={() => setOpen((v) => !v)}
              className="mt-2 flex w-full items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronDown className={`size-3 transition-transform ${open ? "" : "-rotate-90"}`} />
              图例
            </button>
            {open && (
              <div className="mt-1 rounded-md bg-background/50 p-2">
                {layer.legend.map((l) => (
                  <LegendRow key={l.label} {...l} />
                ))}
              </div>
            )}
          </>
        )}

        {layer.meta && (
          <div className="mt-2 grid min-w-0 grid-cols-[minmax(0,0.85fr)_minmax(0,1.5fr)] gap-x-3 gap-y-1 rounded-md bg-background/50 p-2">
            {Object.entries(layer.meta).map(([k, v]) => (
              <div key={k} className="contents">
                <span className="min-w-0 break-words font-mono text-[10px] text-muted-foreground [overflow-wrap:anywhere]">{k}</span>
                <span className="min-w-0 break-words text-right font-mono text-[10px] text-foreground [overflow-wrap:anywhere]">{v}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function RightPanel({
  layers,
  onToggle,
  onOpacity,
  onRemove,
}: {
  layers: RSLayer[];
  onToggle: (id: string) => void;
  onOpacity: (id: string, v: number) => void;
  onRemove: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const panel = useLayerPanelSize();

  return (
    <motion.div
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1], delay: 0.12 }}
      className="absolute right-4 top-[108px] z-20 flex flex-col items-end"
    >
      <AnimatePresence mode="wait">
        {open ? (
          <motion.div
            key="panel"
            initial={{ opacity: 0, x: 20, scale: 0.985 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 20, scale: 0.985 }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
            data-testid="layer-panel"
            style={{ width: panel.size.width, height: panel.size.height }}
            className="relative flex max-h-[calc(100vh-124px)] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-border bg-sidebar/85 shadow-2xl shadow-black/40 backdrop-blur-xl"
          >
            <button type="button" aria-label="调整图层面板宽度" title="拖动左边缘调整宽度，方向键微调" {...panel.handle("width")}
              className="absolute bottom-5 left-0 top-12 z-30 w-2 touch-none cursor-ew-resize hover:bg-primary/20 focus-visible:bg-primary/30" />
            <button type="button" aria-label="调整图层面板高度" title="拖动底边调整高度，方向键微调" {...panel.handle("height")}
              className="absolute bottom-0 left-5 right-5 z-30 h-2 touch-none cursor-ns-resize hover:bg-primary/20 focus-visible:bg-primary/30" />
            <button type="button" aria-label="调整图层面板宽高" title="拖动调整宽高；双击恢复默认大小" {...panel.handle("both")} onDoubleClick={panel.reset}
              className="absolute bottom-0 left-0 z-40 flex size-5 touch-none cursor-nesw-resize items-center justify-center rounded-tr bg-card text-primary hover:bg-primary/20 focus-visible:outline-primary">◣</button>
            <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
              <Layers className="size-4 text-primary" />
              <span className="text-[13px] text-foreground">图层</span>
              <span className="font-mono text-[10px] text-muted-foreground">{layers.length}</span>
              <button
                onClick={() => setOpen(false)}
                className="ml-auto grid size-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
                title="收起面板"
              >
                <PanelRightClose className="size-4" />
              </button>
            </div>

            <div data-testid="layer-panel-scroll" className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
              <div className="flex min-w-0 flex-col gap-2 p-3 pr-4">
                {layers.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 py-8 text-center text-muted-foreground">
                    <ImageIcon className="size-7 opacity-40" />
                    <p className="text-[12px]">尚无图层</p>
                    <p className="font-mono text-[10px]">上传影像或运行模型后生成</p>
                  </div>
                ) : (
                  [...layers].reverse().map((l) => (
                    <LayerCard
                      key={l.id}
                      layer={l}
                      onToggle={() => onToggle(l.id)}
                      onOpacity={(v) => onOpacity(l.id, v)}
                      onRemove={() => onRemove(l.id)}
                    />
                  ))
                )}
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.button
            key="launcher"
            initial={{ opacity: 0, x: 20, scale: 0.9 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 20, scale: 0.9 }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
            onClick={() => setOpen(true)}
            className="flex items-center gap-2 rounded-xl border border-border bg-sidebar/85 px-3 py-2.5 shadow-2xl shadow-black/40 backdrop-blur-xl transition-colors hover:border-primary/40"
            title="展开图层面板"
          >
            <span className="grid size-7 place-items-center rounded-lg bg-primary/12 text-primary">
              <Layers className="size-4" />
            </span>
            <span className="leading-tight text-left">
              <span className="block text-[12px] text-foreground">图层</span>
              <span className="font-mono text-[10px] text-muted-foreground">{layers.length} 个</span>
            </span>
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
