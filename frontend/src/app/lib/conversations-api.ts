import { getApiBaseEndpoint } from "../config";
import { readErrorMessage } from "./errors";

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
  created_at: string;
};

export async function listConversations(chatEndpoint: string): Promise<ConversationItem[]> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/conversations`, {
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { conversations?: ConversationItem[] };
  return payload.conversations ?? [];
}

export async function listConversationMessages(
  chatEndpoint: string,
  conversationId: string,
): Promise<ConversationMessage[]> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/conversations/${conversationId}/messages`, {
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { messages?: ConversationMessage[] };
  return payload.messages ?? [];
}

async function readApiError(res: Response) {
  const payload = await res.json().catch(() => null);
  return new Error(readErrorMessage(payload) ?? `${res.status} ${res.statusText}`);
}
