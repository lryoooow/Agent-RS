import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";

export function ReasoningPanel({ parts }: { parts: string[] }) {
  const [open, setOpen] = useState(true);
  const total = Math.max(parts.length, 1);

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="reasoning-panel max-w-[88%] rounded-lg border border-border/70 bg-muted/20 px-3 py-2"
    >
      <CollapsibleTrigger
        type="button"
        aria-expanded={open}
        aria-label={open ? "collapse thinking" : "expand thinking"}
        className="reasoning-trigger flex w-full items-center justify-between gap-3 text-left text-[10px] tracking-[0.18em] uppercase text-muted-foreground outline-none transition-colors hover:text-foreground/70 focus-visible:text-foreground"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        <span>thinking</span>
        <ChevronDown className="reasoning-chevron size-3.5" aria-hidden="true" />
      </CollapsibleTrigger>
      <CollapsibleContent forceMount aria-hidden={!open} className="reasoning-content">
        <div className="reasoning-content-inner">
          <div className="reasoning-stream whitespace-pre-wrap break-words text-sm leading-relaxed">
            {parts.map((part, index) => {
              const age = total - index - 1;
              const opacity = Math.max(0.42, 0.86 - age * 0.045);
              return (
                <span
                  key={`${index}-${part.length}`}
                  className="reasoning-piece"
                  style={{ color: `color-mix(in srgb, var(--muted-foreground) ${Math.round(opacity * 100)}%, transparent)` }}
                >
                  {part}
                </span>
              );
            })}
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
