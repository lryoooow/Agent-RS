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
export type AgentStatus =
  | "context_assembled"
  | "planning"
  | "planning_fallback"
  | "classifier_skip"
  | "classifier_force"
  | "cache_hit_skip"
  | "cache_hit_search"
  | "tool_requested"
  | "child_agent_running"
  | "tool_execution_started"
  | "tool_execution_completed"
  | "tool_execution_failed"
  | "tool_fallback_used"
  | "tool_context_ready"
  | "geospatial_result_ready"
  | "final_answering"
  | "direct_answer"
  | "tool_unavailable";

export type ToolExecutionInfo = {
  mode: "docker_mcp" | "local_subprocess" | "local_fallback" | "failed";
  fallback_used: boolean;
  error_code?: string | null;
};

type GeospatialBaseResult = {
  imagery_id: string;
  result_url: string;
  bounds: [number, number, number, number] | null;
};

export type GeospatialPreviewResult = GeospatialBaseResult & {
  type: "preview";
};

export type GeospatialNdviResult = GeospatialBaseResult & {
  type: "ndvi";
  stats: { min: number; max: number; mean: number; std: number };
  execution?: ToolExecutionInfo | null;
};

export type GeospatialResult = GeospatialPreviewResult | GeospatialNdviResult;

export type ChatTurn = ChatMessage & {
  id: string;
  analysisStatus?: AnalysisStatus;
  analysisLabel?: string;
  model?: string;
  provider?: string;
  usage?: Usage;
  finishReason?: string;
  retrievedChunks?: number;
  ragTrace?: Record<string, unknown> | null;
  agentStatus?: AgentStatus;
  agentLabel?: string;
  agentTrace?: Record<string, unknown> | null;
  geospatialResult?: GeospatialResult;
  error?: boolean;
};

export type ChatResponse = {
  content: string;
  model: string;
  provider: string;
  usage?: Usage;
  finish_reason?: string;
  conversation_id?: string;
  user_message_id?: string;
  assistant_message_id?: string;
  retrieved_chunks?: number;
  rag_trace?: Record<string, unknown> | null;
  agent_trace?: Record<string, unknown> | null;
  geospatial_result?: GeospatialResult;
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
  web_search_enabled: boolean;
  web_search_configured: boolean;
};

export type StoredConfig = {
  endpoint?: string;
  systemPrompt?: string;
  streamEnabled?: boolean;
  useRag?: boolean;
};

export type ChatRequestBody = {
  messages: ChatMessage[];
  stream: boolean;
  system_prompt?: string;
  conversation_id?: string;
  use_memory?: boolean;
  use_rag?: boolean;
};

export type KnowledgeDocument = {
  id: string;
  title: string;
  source_url?: string | null;
  doc_type?: string | null;
  metadata?: Record<string, unknown> | null;
  chunk_count: number;
  latest_job_id?: string | null;
  latest_job_status?: string | null;
  created_at: string;
  updated_at: string;
};

export type DocumentJob = {
  id: string;
  status: string;
  progress: number;
  filename?: string | null;
  doc_type?: string | null;
  file_size?: number | null;
  text_length?: number | null;
  chunk_count?: number | null;
  embedding_batches?: number | null;
  document_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  stage_timings?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type DocumentChunk = {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  char_count: number;
  token_count?: number | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
};

export type DocumentSearchResult = {
  id: string;
  document_id: string;
  content_preview: string;
  vector_score?: number | null;
  text_score?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
  selected_by_mmr: boolean;
};

export type DocumentSearchResponse = {
  results: DocumentSearchResult[];
  trace: Record<string, unknown>;
};
