import { useEffect, useState } from "react";
import { Brain, Trash2, RefreshCw } from "lucide-react";
import { Button } from "./ui/button";
import { ScrollArea } from "./ui/scroll-area";
import { listMemories, deleteMemory, type MemoryItem } from "../lib/memories-api";

export function MemoryPanel({ endpoint }: { endpoint: string }) {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await listMemories(endpoint));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint]);

  const remove = async (id: string) => {
    try {
      await deleteMemory(endpoint, id);
      setItems((prev) => prev.filter((m) => m.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" onClick={refresh} disabled={loading} className="gap-1.5">
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
          刷新
        </Button>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">{items.length} 条</span>
      </div>

      {error && <p className="font-mono text-[11px] text-destructive">{error}</p>}

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2">
          {items.map((m) => (
            <div key={m.id} className="flex items-start gap-2 rounded-lg border border-border bg-card p-2.5">
              <Brain className="mt-0.5 size-4 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] leading-relaxed text-foreground">{m.content}</p>
                <div className="mt-1 flex flex-wrap gap-x-3 font-mono text-[10px] text-muted-foreground">
                  <span>{m.memory_type}</span>
                  <span>重要度 {m.importance.toFixed(2)}</span>
                  <span>{m.created_at.slice(0, 10)}</span>
                </div>
              </div>
              <button
                onClick={() => remove(m.id)}
                className="grid size-6 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:text-destructive"
                title="删除记忆"
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
          {!loading && items.length === 0 && (
            <p className="py-8 text-center text-[12px] text-muted-foreground">
              暂无长期记忆，对话中会自动沉淀
            </p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
