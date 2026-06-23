import { useEffect, useState } from "react";
import { MessageSquare, Trash2, RefreshCw, Pencil, Check, X, FolderOpen } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { ScrollArea } from "./ui/scroll-area";
import {
  listConversations,
  listConversationMessages,
  renameConversation,
  deleteConversation,
  type ConversationItem,
} from "../lib/conversations-api";

export function HistoryPanel({
  endpoint,
  onOpen,
  activeConversationId,
  onActiveDeleted,
}: {
  endpoint: string;
  onOpen: (
    id: string,
    messages: { role: string; content: string; metadata?: Record<string, unknown> | null }[],
  ) => void;
  // 当前正在聊的会话 id（来自 useChatController）；用于判断删除的是否为激活会话。
  activeConversationId?: string | null;
  // 删除的恰好是激活会话时回调，让上层重置对话状态（清空 conversationId/turns），
  // 杜绝"删了当前会话却仍带死 id 发消息 → 后端查不到 → 静默新建空会话 → 上下文断裂"。
  onActiveDeleted?: () => void;
}) {
  const [items, setItems] = useState<ConversationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await listConversations(endpoint));
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

  const open = async (id: string) => {
    setError("");
    try {
      const messages = await listConversationMessages(endpoint, id);
      onOpen(
        id,
        // 透传 metadata：loadConversation 据此还原 geospatial_result/tool_result，
        // 让分析结果卡片（NDVI/检测/分类等）在重开历史会话时重现，而非只剩文字。
        messages.map((m) => ({ role: m.role, content: m.content, metadata: m.metadata })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const saveRename = async (id: string) => {
    const title = draft.trim();
    if (!title) {
      setEditingId(null);
      return;
    }
    try {
      await renameConversation(endpoint, id, title);
      setItems((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setEditingId(null);
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteConversation(endpoint, id);
      setItems((prev) => prev.filter((c) => c.id !== id));
      // 删的若是当前激活会话，通知上层重置（否则下条消息仍带已删 id 发出 → 上下文断裂）。
      if (id === activeConversationId) onActiveDeleted?.();
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
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">{items.length} 个会话</span>
      </div>

      {error && <p className="font-mono text-[11px] text-destructive">{error}</p>}

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2">
          {items.map((c) => (
            <div key={c.id} className="flex items-center gap-2 rounded-lg border border-border bg-card p-2.5">
              <MessageSquare className="size-4 shrink-0 text-primary" />
              {editingId === c.id ? (
                <>
                  <Input
                    value={draft}
                    autoFocus
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveRename(c.id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="h-7 flex-1 bg-input-background text-[12px]"
                  />
                  <button onClick={() => saveRename(c.id)} className="grid size-6 place-items-center rounded text-primary hover:bg-background" title="保存">
                    <Check className="size-3.5" />
                  </button>
                  <button onClick={() => setEditingId(null)} className="grid size-6 place-items-center rounded text-muted-foreground hover:bg-background" title="取消">
                    <X className="size-3.5" />
                  </button>
                </>
              ) : (
                <>
                  <button onClick={() => open(c.id)} className="min-w-0 flex-1 text-left" title="载入此会话">
                    <div className="truncate text-[12.5px] text-foreground">{c.title || "未命名会话"}</div>
                    <div className="font-mono text-[10px] text-muted-foreground">
                      {c.message_count} 条 · {c.updated_at.slice(0, 10)}
                    </div>
                  </button>
                  <button onClick={() => open(c.id)} className="grid size-6 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:text-primary" title="载入会话">
                    <FolderOpen className="size-3.5" />
                  </button>
                  <button
                    onClick={() => {
                      setEditingId(c.id);
                      setDraft(c.title);
                    }}
                    className="grid size-6 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:text-foreground"
                    title="重命名"
                  >
                    <Pencil className="size-3.5" />
                  </button>
                  <button onClick={() => remove(c.id)} className="grid size-6 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:text-destructive" title="删除会话">
                    <Trash2 className="size-3.5" />
                  </button>
                </>
              )}
            </div>
          ))}
          {!loading && items.length === 0 && (
            <p className="py-8 text-center text-[12px] text-muted-foreground">
              暂无历史会话（需开启数据库）
            </p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
