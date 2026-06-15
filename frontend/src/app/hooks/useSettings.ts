import { useEffect, useState } from "react";
import {
  clearStoredConfig,
  DEFAULT_ENDPOINT,
  DEFAULT_SYSTEM_PROMPT,
  getConfigEndpoint,
  loadConfig,
  saveConfig,
} from "../config";
import { fetchConfig } from "../lib/chat-api";
import type { ConfigResponse, ProviderConfig } from "../types";

export function useSettings() {
  const [stored] = useState(() => loadConfig());
  const [endpoint, setEndpoint] = useState(stored.endpoint ?? DEFAULT_ENDPOINT);
  const [systemPrompt, setSystemPrompt] = useState(stored.systemPrompt ?? DEFAULT_SYSTEM_PROMPT);
  const [streamEnabled, setStreamEnabled] = useState(stored.streamEnabled ?? true);
  const [useRag, setUseRag] = useState(stored.useRag ?? false);
  // 模型直连兜底配置（后端未配置 AI_API_KEY 时启用）
  const [baseUrl, setBaseUrl] = useState(stored.baseUrl ?? "");
  const [apiKey, setApiKey] = useState(stored.apiKey ?? "");
  const [model, setModel] = useState(stored.model ?? "");
  const [serverConfig, setServerConfig] = useState<ConfigResponse | null>(null);
  const [configError, setConfigError] = useState("");

  useEffect(() => {
    saveConfig({ endpoint, systemPrompt, streamEnabled, useRag, baseUrl, apiKey, model });
  }, [endpoint, systemPrompt, streamEnabled, useRag, baseUrl, apiKey, model]);

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

  // ".env 优先，前端兜底" 的判定核心：
  // 只有在后端「确认」未配置 API Key 且允许客户端配置时，前端直连配置才生效下发。
  // 后端已配置 API Key（api_key_configured=true）→ 一律不下发，env 优先。
  const providerFallbackEligible = Boolean(
    serverConfig &&
      serverConfig.api_key_configured === false &&
      serverConfig.allow_client_provider_config === true,
  );

  const effectiveProviderConfig: ProviderConfig | null = (() => {
    if (!providerFallbackEligible) return null;
    const b = baseUrl.trim();
    const k = apiKey.trim();
    const m = model.trim();
    if (!b && !k && !m) return null;
    const pc: ProviderConfig = {};
    if (b) pc.base_url = b;
    if (k) pc.api_key = k;
    if (m) pc.model = m;
    return pc;
  })();

  function clearSettings() {
    clearStoredConfig();
    setEndpoint(DEFAULT_ENDPOINT);
    setSystemPrompt(DEFAULT_SYSTEM_PROMPT);
    setStreamEnabled(true);
    setUseRag(false);
    setBaseUrl("");
    setApiKey("");
    setModel("");
  }

  return {
    endpoint,
    systemPrompt,
    streamEnabled,
    useRag,
    baseUrl,
    apiKey,
    model,
    serverConfig,
    configError,
    // 兜底是否可用（后端未配 key 且允许客户端配置）
    providerFallbackEligible,
    // 实际下发的 provider_config（不满足兜底条件时为 null）
    effectiveProviderConfig,
    setEndpoint,
    setSystemPrompt,
    setStreamEnabled,
    setUseRag,
    setBaseUrl,
    setApiKey,
    setModel,
    clearSettings,
  };
}
