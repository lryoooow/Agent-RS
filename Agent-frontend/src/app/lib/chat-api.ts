import type { BootstrapConfigResponse, ChatRequestBody, ConfigResponse, ModelListResponse, ProviderConfig } from "../types";
import { apiFetch } from "./http";
import { ApiError } from "./http";

// 聊天是 SSE 长连接：不设整体超时（流式可能合法地跑几分钟），
// 由调用方的 AbortSignal 控制（用户停止/组件卸载）；SSE 空闲超时在
// useChatController 的读循环里单独兜底（P2 加固项）。
export async function postChat(body: ChatRequestBody, signal: AbortSignal) {
  return apiFetch("/chat", { method: "POST", json: body, signal, timeoutMs: 3_600_000 });
}

export async function fetchBootstrapConfig(signal?: AbortSignal) {
  const response = await apiFetch("/config/bootstrap", { signal, timeoutMs: 10_000 });
  const data = await response.json();
  if (!data || typeof data.auth_required !== "boolean") throw new ApiError(0,"BAD_PAYLOAD","工作台配置格式异常，请重新加载。");
  return data as BootstrapConfigResponse;
}

export async function fetchConfig(signal?: AbortSignal) {
  const response = await apiFetch("/config", { signal, timeoutMs: 10_000 });
  const data = await response.json();
  const booleans = ["base_url_configured", "api_key_configured", "allow_client_provider_config",
    "prompt_dynamic_modules_enabled", "allow_user_extra_instructions", "web_search_enabled",
    "web_search_configured", "auth_required", "invite_required", "auto_flow_enabled"];
  const strings = ["provider", "prompt_profile", "system_prompt_language"];
  if (!data || typeof data !== "object" || booleans.some((key) => typeof data[key] !== "boolean") ||
      strings.some((key) => typeof data[key] !== "string") || data.agent_framework !== "autogen" ||
      !Array.isArray(data.available_flows) || data.available_flows.some((flow: unknown) => typeof flow !== "string") ||
      (data.default_model !== undefined && typeof data.default_model !== "string")) {
    throw new ApiError(0,"BAD_PAYLOAD","工作台配置格式异常，请重新加载。");
  }
  return data as ConfigResponse;
}

export async function fetchModels(providerConfig?: ProviderConfig | null, model?: string, signal?: AbortSignal) {
  const response = await apiFetch("/config/models", {
    method: "POST",
    json: {
      provider_config: providerConfig ?? undefined,
      model: model?.trim() || undefined,
    },
    // 模型列表探测上游可能慢，放宽到 45s。
    timeoutMs: 45_000,
    signal,
  });
  const data = await response.json();
  if (!data || !Array.isArray(data.models) || data.models.some((row: unknown) =>
    !row || typeof row !== "object" || typeof (row as { id?: unknown }).id !== "string") ||
    typeof data.current_model !== "string") throw new ApiError(0,"BAD_PAYLOAD","模型列表格式异常，请重新加载。");
  return data as ModelListResponse;
}

export { ApiError };
