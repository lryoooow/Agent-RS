import type { ChatRequestBody, ProviderConfig, ThinkingStrength } from "../types";
import type { Roi } from "./roi";

export function buildChatRequestBody({
  messages,
  systemPrompt,
  stream,
  conversationId,
  useRag,
  model,
  providerConfig,
  metadata,
  thinkingStrength,
  tavilyApiKey,
  analysisRoi,
}: {
  messages: ChatRequestBody["messages"];
  systemPrompt: string;
  stream: boolean;
  conversationId?: string | null;
  useRag: boolean;
  model?: string | null;
  providerConfig?: ProviderConfig | null;
  metadata?: Record<string, unknown>;
  thinkingStrength?: ThinkingStrength | null;
  tavilyApiKey?: string | null;
  analysisRoi?: Roi | null;
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
  if (metadata && Object.keys(metadata).length > 0) {
    body.metadata = metadata;
  }
  if (thinkingStrength) body.thinking_strength = thinkingStrength;
  if (tavilyApiKey?.trim()) body.search_config = { api_key: tavilyApiKey.trim() };
  if (analysisRoi) body.analysis_roi = analysisRoi;
  return body;
}
