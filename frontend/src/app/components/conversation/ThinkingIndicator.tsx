export function ThinkingIndicator() {
  return (
    <div className="flex flex-col gap-2 items-start">
      <div
        className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        assistant
      </div>
      <div className="flex items-center gap-1.5 text-muted-foreground">
        <span className="size-1.5 rounded-full bg-foreground/40 animate-pulse" style={{ animationDelay: "0ms" }} />
        <span className="size-1.5 rounded-full bg-foreground/40 animate-pulse" style={{ animationDelay: "150ms" }} />
        <span className="size-1.5 rounded-full bg-foreground/40 animate-pulse" style={{ animationDelay: "300ms" }} />
      </div>
    </div>
  );
}
