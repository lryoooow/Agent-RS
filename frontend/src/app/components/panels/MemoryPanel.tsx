import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { deleteMemory, listMemories, type MemoryItem } from "../../lib/memories-api";

type MemoryPanelProps = {
  endpoint: string;
};

export function MemoryPanel({ endpoint }: MemoryPanelProps) {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      setMemories(await listMemories(endpoint));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function remove(memoryId: string) {
    setError("");
    try {
      await deleteMemory(endpoint, memoryId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    refresh();
  }, [endpoint]);

  return (
    <div className="border-b border-border bg-card/60 px-6 md:px-10 py-5">
      <div className="border border-border rounded-md">
        <div className="px-3 py-2 border-b border-border text-[11px] tracking-[0.18em] uppercase text-muted-foreground">
          long-term memory · {memories.length}
        </div>
        {error && <div className="px-3 py-2 text-xs text-destructive">{error}</div>}
        <div className="max-h-80 overflow-y-auto divide-y divide-border">
          {memories.map((memory) => (
            <div key={memory.id} className="flex items-start justify-between gap-3 px-3 py-3">
              <div className="min-w-0">
                <div className="whitespace-pre-wrap text-sm">{memory.content}</div>
                <div className="mt-1 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  {memory.memory_type} · importance {memory.importance.toFixed(2)} ·{" "}
                  {formatDate(memory.created_at)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => remove(memory.id)}
                className="shrink-0 inline-flex size-8 items-center justify-center border border-border rounded-md hover:bg-muted"
                aria-label="delete memory"
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
          {memories.length === 0 && (
            <div className="py-8 text-center text-xs text-muted-foreground">no memories</div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
