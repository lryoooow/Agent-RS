import { Sparkles } from "lucide-react";
import { SUGGESTIONS } from "../../config";

export function EmptyState({ onPick }: { onPick: (value: string) => void }) {
  return (
    <div className="flex flex-col items-start gap-8 pt-8">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Sparkles className="size-4" />
        <span
          className="text-[11px] uppercase tracking-[0.22em]"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          Agent-RS remote sensing workspace
        </span>
      </div>
      <h1
        className="max-w-xl text-5xl leading-[1.05] tracking-tight md:text-6xl"
        style={{ fontFamily: "'Instrument Serif', serif" }}
      >
        Analyze imagery, call tools, and keep the map in view.
      </h1>
      <p className="max-w-md leading-relaxed text-muted-foreground">
        上传 GeoTIFF 后，可以检查影像、计算 NDVI 或其他光谱指数，并在右侧地图查看结果图层。
      </p>
      <div className="grid w-full gap-2 pt-2 sm:grid-cols-2">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onPick(suggestion)}
            className="rounded-xl border border-border bg-card px-4 py-3 text-left text-sm leading-relaxed transition-colors hover:border-foreground/30 hover:bg-card"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
