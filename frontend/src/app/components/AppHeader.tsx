import { BookOpen, Brain, Clock3, RotateCcw, Settings2, UserCircle } from "lucide-react";

type AppHeaderProps = {
  isEmpty: boolean;
  loading: boolean;
  settingsOpen: boolean;
  knowledgeOpen: boolean;
  historyOpen: boolean;
  memoryOpen: boolean;
  authOpen: boolean;
  userLabel: string;
  authenticated: boolean;
  onReset: () => void;
  onToggleSettings: () => void;
  onToggleKnowledge: () => void;
  onToggleHistory: () => void;
  onToggleMemory: () => void;
  onToggleAuth: () => void;
};

export function AppHeader({
  isEmpty,
  loading,
  settingsOpen,
  knowledgeOpen,
  historyOpen,
  memoryOpen,
  authOpen,
  userLabel,
  authenticated,
  onReset,
  onToggleSettings,
  onToggleKnowledge,
  onToggleHistory,
  onToggleMemory,
  onToggleAuth,
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
        <button
          type="button"
          onClick={onToggleKnowledge}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border border-border transition-colors ${
            knowledgeOpen ? "bg-foreground text-background" : "hover:bg-muted"
          }`}
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          <BookOpen className="size-3" />
          knowledge
        </button>
        <button
          type="button"
          onClick={onToggleHistory}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border border-border transition-colors ${
            historyOpen ? "bg-foreground text-background" : "hover:bg-muted"
          }`}
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          <Clock3 className="size-3" />
          history
        </button>
        <button
          type="button"
          onClick={onToggleMemory}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border border-border transition-colors ${
            memoryOpen ? "bg-foreground text-background" : "hover:bg-muted"
          }`}
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          <Brain className="size-3" />
          memory
        </button>
        <button
          type="button"
          onClick={onToggleAuth}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border border-border transition-colors ${
            authOpen ? "bg-foreground text-background" : "hover:bg-muted"
          }`}
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
          title={userLabel}
        >
          <UserCircle className="size-3" />
          {authenticated ? "account" : "login"}
        </button>
      </div>
    </header>
  );
}
