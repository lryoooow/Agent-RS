import { RotateCcw, Settings2 } from "lucide-react";

type AppHeaderProps = {
  isEmpty: boolean;
  loading: boolean;
  settingsOpen: boolean;
  onReset: () => void;
  onToggleSettings: () => void;
};

export function AppHeader({
  isEmpty,
  loading,
  settingsOpen,
  onReset,
  onToggleSettings,
}: AppHeaderProps) {
  return (
    <header className="flex items-center justify-between px-6 md:px-10 py-5 border-b border-border">
      <div className="flex items-baseline gap-3">
        <span
          className="text-2xl tracking-tight"
          style={{ fontFamily: "'Instrument Serif', serif", fontStyle: "italic" }}
        >
          Atelier
        </span>
        <span
          className="text-[11px] tracking-[0.18em] uppercase text-muted-foreground"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          chat · python api
        </span>
      </div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onReset}
          disabled={isEmpty || loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border border-border hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          <RotateCcw className="size-3" />
          reset
        </button>
        <button
          type="button"
          onClick={onToggleSettings}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border border-border transition-colors ${
            settingsOpen ? "bg-foreground text-background" : "hover:bg-muted"
          }`}
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          <Settings2 className="size-3" />
          config
        </button>
      </div>
    </header>
  );
}
