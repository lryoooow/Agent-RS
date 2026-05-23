import { Sparkles } from "lucide-react";
import { SUGGESTIONS } from "../../config";

export function EmptyState({ onPick }: { onPick: (value: string) => void }) {
  return (
    <div className="flex flex-col items-start gap-8 pt-8">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Sparkles className="size-4" />
        <span
          className="text-[11px] tracking-[0.22em] uppercase"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          a quiet place to think out loud
        </span>
      </div>
      <h1
        className="text-5xl md:text-6xl leading-[1.05] tracking-tight max-w-xl"
        style={{ fontFamily: "'Instrument Serif', serif" }}
      >
        Start a <em className="text-accent">conversation</em>, see where the thread leads.
      </h1>
      <p className="text-muted-foreground max-w-md leading-relaxed">
        本应用通过{" "}
        <code className="text-foreground" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          POST /api/chat
        </code>{" "}
        与 Python 后端对接。可在右上 <span className="text-foreground">config</span>{" "}
        处填写备用 base URL、API key、模型与额外要求。
      </p>
      <div className="grid sm:grid-cols-2 gap-2 w-full pt-2">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onPick(suggestion)}
            className="text-left text-sm leading-relaxed border border-border rounded-xl px-4 py-3 bg-card hover:border-foreground/30 hover:bg-card transition-colors"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
