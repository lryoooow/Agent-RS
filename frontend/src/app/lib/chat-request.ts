import type { ChatMessage, ChatRequestBody } from "../types";

export function buildChatRequestBody({
  messages,
  systemPrompt,
  stream,
  conversationId,
  useRag,
}: {
  messages: ChatMessage[];
  systemPrompt: string;
  stream: boolean;
  conversationId?: string | null;
  useRag: boolean;
}): ChatRequestBody {
  const body: ChatRequestBody = { messages, stream, use_memory: true, use_rag: useRag };
  if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
  if (conversationId) body.conversation_id = conversationId;
  return body;
}
