import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import {
  listConversationMessages,
  listConversations,
  type ConversationItem,
  type ConversationMessage,
} from "../../lib/conversations-api";

type HistoryPanelProps = {
  endpoint: string;
};

export function HistoryPanel({ endpoint }: HistoryPanelProps) {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      setConversations(await listConversations(endpoint));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function selectConversation(id: string) {
    setSelectedId(id);
    setError("");
    try {
      setMessages(await listConversationMessages(endpoint, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    refresh();
  }, [endpoint]);

  return (
    <div className="border-b border-border bg-card/60 px-6 md:px-10 py-5">
      <div className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
        <section className="border border-border rounded-md">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <div className="text-[11px] tracking-[0.18em] uppercase text-muted-foreground">history</div>
            <button type="button" onClick={refresh} disabled={loading}>
              <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
          <div className="max-h-80 overflow-y-auto divide-y divide-border">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                onClick={() => selectConversation(conversation.id)}
                className={`block w-full px-3 py-3 text-left hover:bg-muted ${
                  selectedId === conversation.id ? "bg-muted" : ""
                }`}
              >
                <div className="truncate text-sm">{conversation.title}</div>
                <div className="mt-1 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  {conversation.message_count} messages · {formatDate(conversation.updated_at)}
                </div>
              </button>
            ))}
          </div>
        </section>
        <section className="max-h-80 overflow-y-auto border border-border rounded-md p-3">
          {error && <div className="mb-2 text-xs text-destructive">{error}</div>}
          {messages.map((message) => (
            <div key={message.id} className="mb-4">
              <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                {message.role} · {message.status} · {formatDate(message.created_at)}
              </div>
              <div className="mt-1 whitespace-pre-wrap text-sm">{message.content}</div>
            </div>
          ))}
          {selectedId && messages.length === 0 && (
            <div className="py-8 text-center text-xs text-muted-foreground">no messages</div>
          )}
        </section>
      </div>
    </div>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
