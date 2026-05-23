import type { ChatMessage, ChatRequestBody, ProviderConfigBody } from "../types";

export function buildChatRequestBody({
  messages,
  model,
  systemPrompt,
  stream,
  providerConfig,
}: {
  messages: ChatMessage[];
  model: string;
  systemPrompt: string;
  stream: boolean;
  providerConfig: ProviderConfigBody;
}): ChatRequestBody {
  const body: ChatRequestBody = { messages, stream };
  if (model.trim()) body.model = model.trim();
  if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
  if (Object.keys(providerConfig).length > 0) body.provider_config = providerConfig;
  return body;
}
