import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearStoredConfig,
  DEFAULT_ENDPOINT,
  DEFAULT_SYSTEM_PROMPT,
  getConfigEndpoint,
  getModelsEndpoint,
  loadConfig,
  saveConfig,
} from "../config";
import { fetchConfig, fetchModels } from "../lib/chat-api";
import type { AvailableModel, ConfigResponse, ProviderConfig, ThinkingStrength } from "../types";

export function useSettings() {
  const [stored] = useState(() => loadConfig());
  const endpoint = DEFAULT_ENDPOINT; // 固定 /api/chat（新设计已隐藏后端地址输入）
  const [systemPrompt, setSystemPrompt] = useState(stored.systemPrompt ?? DEFAULT_SYSTEM_PROMPT);
  const [streamEnabled, setStreamEnabled] = useState(stored.streamEnabled ?? true);
  const [useRag, setUseRag] = useState(stored.useRag ?? false);
  const [model, setModel] = useState(stored.model ?? "");
  // provider_config（base_url/api_key）按本地零配置需求持久化到 localStorage，刷新后自动回填。
  // 默认空，由用户在配置页自行填写；后端 resolve_ai_config 按 client or env 链取值（填了就用、空则回落 .env）。
  const [providerConfig, setProviderConfig] = useState<ProviderConfig | null>(() =>
    stored.baseUrl || stored.apiKey
      ? { base_url: stored.baseUrl ?? "", api_key: stored.apiKey ?? "" }
      : null,
  );
  // 思考强度 low/medium/max（默认 medium）；持久化到 localStorage，随请求体发往后端。
  const [thinkingStrength, setThinkingStrength] = useState<ThinkingStrength>(
    stored.thinkingStrength ?? "medium",
  );
  const [tavilyApiKey, setTavilyApiKey] = useState(stored.tavilyApiKey ?? "");
  const [serverConfig, setServerConfig] = useState<ConfigResponse | null>(null);
  const [configError, setConfigError] = useState("");
  const [availableModels, setAvailableModels] = useState<AvailableModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const modelsRequestRef = useRef(false);

  useEffect(() => {
    saveConfig({
      systemPrompt,
      streamEnabled,
      useRag,
      model,
      baseUrl: providerConfig?.base_url,
      apiKey: providerConfig?.api_key,
      tavilyApiKey,
      thinkingStrength,
    });
  }, [systemPrompt, streamEnabled, useRag, model, providerConfig, tavilyApiKey, thinkingStrength]);

  useEffect(() => {
    let cancelled = false;

    async function loadServerConfig() {
      try {
        setConfigError("");
        const data = await fetchConfig(getConfigEndpoint(endpoint));
        if (!cancelled) setServerConfig(data);
      } catch (err) {
        if (!cancelled) {
          setServerConfig(null);
          setConfigError(err instanceof Error ? err.message : String(err));
        }
      }
    }

    loadServerConfig();
    return () => {
      cancelled = true;
    };
  }, [endpoint]);

  const refreshModels = useCallback(async () => {
    if (modelsRequestRef.current) return;
    modelsRequestRef.current = true;
    setModelsLoading(true);
    setModelsError("");
    try {
      const data = await fetchModels(
        getModelsEndpoint(endpoint),
        providerConfig,
        model || serverConfig?.default_model,
      );
      setAvailableModels(data.models);
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : String(err));
    } finally {
      modelsRequestRef.current = false;
      setModelsLoading(false);
    }
  }, [endpoint, model, providerConfig, serverConfig?.default_model]);

  function clearSettings() {
    clearStoredConfig();
    setSystemPrompt(DEFAULT_SYSTEM_PROMPT);
    setStreamEnabled(true);
    setUseRag(false);
    setModel("");
    setProviderConfig(null);
    setTavilyApiKey("");
    setThinkingStrength("medium");
    setAvailableModels([]);
    setModelsError("");
  }

  return {
    endpoint,
    systemPrompt,
    streamEnabled,
    useRag,
    model,
    providerConfig,
    thinkingStrength,
    tavilyApiKey,
    serverConfig,
    configError,
    availableModels,
    modelsLoading,
    modelsError,
    setSystemPrompt,
    setStreamEnabled,
    setUseRag,
    setModel,
    setProviderConfig,
    setThinkingStrength,
    setTavilyApiKey,
    refreshModels,
    clearSettings,
  };
}
