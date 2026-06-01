import type { ReactNode } from "react";

export function StatusPill({ label, icon }: { label: string; icon?: ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1 border border-border rounded-full px-2 py-1 text-[10px] text-muted-foreground"
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    >
      {icon}
      {label}
    </span>
  );
}
