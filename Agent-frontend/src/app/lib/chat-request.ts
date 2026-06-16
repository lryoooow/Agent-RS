import type { ChatRequestBody, ProviderConfig } from "../types";

export function buildChatRequestBody({
  messages,
  systemPrompt,
  stream,
  conversationId,
  useRag,
  model,
  providerConfig,
}: {
  messages: ChatRequestBody["messages"];
  systemPrompt: string;
  stream: boolean;
  conversationId?: string | null;
  useRag: boolean;
  model?: string | null;
  providerConfig?: ProviderConfig | null;
}): ChatRequestBody {
  const body: ChatRequestBody = { messages, stream, use_memory: true, use_rag: useRag };
  if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
  if (conversationId) body.conversation_id = conversationId;
  if (model?.trim()) body.model = model.trim();
  if (providerConfig) {
    const trimmed: ProviderConfig = {};
    if (providerConfig.base_url?.trim()) trimmed.base_url = providerConfig.base_url.trim();
    if (providerConfig.api_key?.trim()) trimmed.api_key = providerConfig.api_key.trim();
    if (providerConfig.model?.trim()) trimmed.model = providerConfig.model.trim();
    if (Object.keys(trimmed).length > 0) body.provider_config = trimmed;
  }
  return body;
}
