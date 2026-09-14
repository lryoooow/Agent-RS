import type { ChatRequestBody, ConfigResponse, ModelListResponse, ProviderConfig } from "../types";
import { apiFetch } from "./http";
import { ApiError } from "./http";

// 聊天是 SSE 长连接：不设整体超时（流式可能合法地跑几分钟），
// 由调用方的 AbortSignal 控制（用户停止/组件卸载）；SSE 空闲超时在
// useChatController 的读循环里单独兜底（P2 加固项）。
export async function postChat(body: ChatRequestBody, signal: AbortSignal) {
  return apiFetch("/chat", { method: "POST", json: body, signal, timeoutMs: 3_600_000 });
}

export async function fetchConfig() {
  const response = await apiFetch("/config", {});
  return (await response.json()) as ConfigResponse;
}

export async function fetchModels(providerConfig?: ProviderConfig | null, model?: string) {
  const response = await apiFetch("/config/models", {
    method: "POST",
    json: {
      provider_config: providerConfig ?? undefined,
      model: model?.trim() || undefined,
    },
    // 模型列表探测上游可能慢，放宽到 45s。
    timeoutMs: 45_000,
  });
  return (await response.json()) as ModelListResponse;
}

export { ApiError };
