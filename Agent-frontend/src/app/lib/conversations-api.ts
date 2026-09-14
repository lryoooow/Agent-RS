import { apiFetch } from "./http";

export type ConversationItem = {
  id: string;
  title: string;
  scenario_id?: string | null;
  model_name?: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type ConversationMessage = {
  id: string;
  role: string;
  content: string;
  status: string;
  // 后端 messages 接口随消息回传 metadata（含持久化的 geospatial_result/tool_result），
  // 会话重载时据此重现分析结果卡片，不再只剩纯文字。
  metadata?: Record<string, unknown> | null;
  created_at: string;
};

export async function listConversations(): Promise<ConversationItem[]> {
  const response = await apiFetch("/conversations", {});
  const payload = (await response.json().catch(() => null)) as { conversations?: ConversationItem[] } | null;
  return payload?.conversations ?? [];
}

export async function listConversationMessages(conversationId: string): Promise<ConversationMessage[]> {
  const response = await apiFetch(`/conversations/${conversationId}/messages`, {});
  const payload = (await response.json().catch(() => null)) as { messages?: ConversationMessage[] } | null;
  return payload?.messages ?? [];
}

// 后端已支持 PATCH 改名 / DELETE 删除（conversations.py），老前端 lib 未实现，这里补齐。
export async function renameConversation(conversationId: string, title: string): Promise<void> {
  await apiFetch(`/conversations/${conversationId}`, { method: "PATCH", json: { title } });
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await apiFetch(`/conversations/${conversationId}`, { method: "DELETE" });
}
