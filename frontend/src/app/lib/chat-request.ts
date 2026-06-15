import type { ChatMessage, ChatRequestBody, ProviderConfig } from "../types";

export function buildChatRequestBody({
  messages,
  systemPrompt,
  stream,
  conversationId,
  useRag,
  providerConfig,
}: {
  messages: ChatMessage[];
  systemPrompt: string;
  stream: boolean;
  conversationId?: string | null;
  useRag: boolean;
  providerConfig?: ProviderConfig | null;
}): ChatRequestBody {
  const body: ChatRequestBody = { messages, stream, use_memory: true, use_rag: useRag };
  if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
  if (conversationId) body.conversation_id = conversationId;
  // 仅在前端兜底配置非空时附带，避免发送空对象触发后端无谓校验。
  const pc = sanitizeProviderConfig(providerConfig);
  if (pc) body.provider_config = pc;
  return body;
}

// 裁剪空白字段；全部为空则返回 null，调用方据此决定是否下发 provider_config。
function sanitizeProviderConfig(input?: ProviderConfig | null): ProviderConfig | null {
  if (!input) return null;
  const base_url = input.base_url?.trim() || undefined;
  const api_key = input.api_key?.trim() || undefined;
  const model = input.model?.trim() || undefined;
  if (!base_url && !api_key && !model) return null;
  const pc: ProviderConfig = {};
  if (base_url) pc.base_url = base_url;
  if (api_key) pc.api_key = api_key;
  if (model) pc.model = model;
  return pc;
}
