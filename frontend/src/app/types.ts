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

export type AnalysisStatus = "analyzing" | "preparing" | "answering" | "complete";

export type ChatTurn = ChatMessage & {
  id: string;
  analysisStatus?: AnalysisStatus;
  analysisLabel?: string;
  model?: string;
  provider?: string;
  usage?: Usage;
  finishReason?: string;
  error?: boolean;
};

export type ChatResponse = {
  content: string;
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
  prompt_profile: string;
  prompt_dynamic_modules_enabled: boolean;
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
