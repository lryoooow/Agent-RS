export type Role = "user" | "assistant" | "system";

export type ChatMessage = {
  role: Role;
  content: string;
};

export type Usage = {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
};

export type ChatTurn = ChatMessage & {
  id: string;
  reasoning?: string;
  reasoningParts?: string[];
  model?: string;
  provider?: string;
  usage?: Usage;
  finishReason?: string;
  error?: boolean;
};

export type ChatResponse = {
  content: string;
  reasoning?: string;
  model: string;
  provider: string;
  usage?: Usage;
  finish_reason?: string;
};

export type ConfigResponse = {
  provider: string;
  base_url_configured: boolean;
  api_key_configured: boolean;
  default_model?: string;
  allow_client_provider_config: boolean;
  system_prompt_template: string;
  system_prompt_language: string;
  allow_user_extra_instructions: boolean;
};

export type StoredConfig = {
  endpoint?: string;
  baseURL?: string;
  apiKey?: string;
  model?: string;
  systemPrompt?: string;
  streamEnabled?: boolean;
};

export type ProviderConfigBody = {
  base_url?: string;
  api_key?: string;
  model?: string;
};

export type ChatRequestBody = {
  messages: ChatMessage[];
  stream: boolean;
  model?: string;
  system_prompt?: string;
  provider_config?: ProviderConfigBody;
};
