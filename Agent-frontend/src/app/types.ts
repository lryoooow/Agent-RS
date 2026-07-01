export type Role = "user" | "assistant" | "system";

export type ChatMessage = {
  role: Role;
  content: string;
};

export type MapAnnotation = {
  type: "Feature";
  id?: string;
  geometry: {
    type: "Polygon" | "Point" | "LineString";
    coordinates: number[] | number[][] | number[][][];
  };
  properties?: Record<string, unknown>;
};

export type MapContext = {
  center: [number, number];
  zoom: number;
  annotations?: MapAnnotation[];
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
  | "planner_started"
  | "planner_completed"
  | "planner_invalid"
  | "planner_selected"
  | "planner_no_call"
  | "plan_validation_failed"
  | "capability_guard_rejected"
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

export type LegendInfo = {
  label: string;
  min: number;
  max: number;
  palette: string;
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
  legend?: LegendInfo | null;
};

export type GeospatialSpectralIndexResult = GeospatialBaseResult & {
  type: "spectral_index";
  index_type: string;
  stats: {
    index_type: string;
    min: number;
    max: number;
    mean: number;
    std: number;
    nodata_pct?: number;
  };
  execution?: ToolExecutionInfo | null;
  legend?: LegendInfo | null;
};

export type GeospatialCompositeResult = GeospatialBaseResult & {
  type: "composite";
  mode: string;
  bands_used: number[];
  execution?: ToolExecutionInfo | null;
};

export type DetectionClassInfo = {
  name: string;
  label: string;
  count: number;
  color: string;
};

export type GeospatialDetectionResult = GeospatialBaseResult & {
  type: "detection";
  detection_count: number;
  score_threshold: number;
  classes: DetectionClassInfo[];
  execution?: ToolExecutionInfo | null;
};

export type SegmentationClassInfo = {
  name: string;
  label: string;
  pixel_count: number;
  percentage: number;
  color: string;
};

export type GeospatialSegmentationResult = GeospatialBaseResult & {
  type: "segmentation";
  total_pixels: number;
  classes: SegmentationClassInfo[];
  execution?: ToolExecutionInfo | null;
};

// 报告结果：不是地图图层，而是一份可下载的 Word 文档（独立形态，无 result_url/bounds）。
export type GeospatialReportResult = {
  type: "report";
  imagery_id: string;
  filename: string;
  download_url: string;
};

export type GeospatialResult =
  | GeospatialPreviewResult
  | GeospatialNdviResult
  | GeospatialSpectralIndexResult
  | GeospatialCompositeResult
  | GeospatialDetectionResult
  | GeospatialSegmentationResult
  | GeospatialReportResult;

export type RasterBandStats = {
  band: number;
  min?: number | null;
  max?: number | null;
  mean?: number | null;
  std?: number | null;
};

export type RasterCapabilities = {
  has_blue: boolean;
  has_green: boolean;
  has_red: boolean;
  has_nir: boolean;
  has_swir: boolean;
};

export type RasterInspectResult = {
  type: "raster_inspect";
  imagery_id: string;
  width: number;
  height: number;
  band_count: number;
  crs?: string | null;
  bounds?: [number, number, number, number] | null;
  dtype?: string | null;
  pixel_size?: [number, number] | null;
  nodata?: number | string | null;
  capabilities: RasterCapabilities;
  per_band_stats: RasterBandStats[];
  execution?: ToolExecutionInfo | null;
};

export type ToolResult = RasterInspectResult;

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
  toolResult?: ToolResult;
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
  tool_result?: ToolResult;
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
  // 强制登录：未登录时前端全屏拦截到 AuthGate。
  auth_required: boolean;
  // 注册需邀请码：前端预留字段，当前后端已移除邀请码逻辑，恒为 false。
  invite_required: boolean;
};

export type StoredConfig = {
  endpoint?: string;
  systemPrompt?: string;
  streamEnabled?: boolean;
  useRag?: boolean;
  model?: string;
  // provider base_url / api_key 持久化到 localStorage：本地零配置场景刷新/重开浏览器免重填。
  // 默认空，用户自行填写；后端按 client or env 链取值（填了就用、留空回落 .env）。
  baseUrl?: string;
  apiKey?: string;
};

export type ProviderConfig = {
  base_url?: string;
  api_key?: string;
  model?: string;
};

export type ChatRequestBody = {
  messages: ChatMessage[];
  stream: boolean;
  model?: string;
  system_prompt?: string;
  conversation_id?: string;
  use_memory?: boolean;
  use_rag?: boolean;
  provider_config?: ProviderConfig;
  metadata?: Record<string, unknown>;
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
