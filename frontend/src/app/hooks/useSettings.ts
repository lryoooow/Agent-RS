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
import type { ConfigResponse, ProviderConfigBody } from "../types";

export function useSettings() {
  const [stored] = useState(() => loadConfig());
  const [endpoint, setEndpoint] = useState(stored.endpoint ?? DEFAULT_ENDPOINT);
  const [baseURL, setBaseURL] = useState(stored.baseURL ?? "");
  const [apiKey, setApiKey] = useState(stored.apiKey ?? "");
  const [model, setModel] = useState(stored.model ?? "");
  const [systemPrompt, setSystemPrompt] = useState(stored.systemPrompt ?? DEFAULT_SYSTEM_PROMPT);
  const [streamEnabled, setStreamEnabled] = useState(stored.streamEnabled ?? true);
  const [serverConfig, setServerConfig] = useState<ConfigResponse | null>(null);
  const [configError, setConfigError] = useState("");

  useEffect(() => {
    saveConfig({ endpoint, baseURL, apiKey, model, systemPrompt, streamEnabled });
  }, [endpoint, baseURL, apiKey, model, systemPrompt, streamEnabled]);

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

  function clearSettings() {
    clearStoredConfig();
    setEndpoint(DEFAULT_ENDPOINT);
    setBaseURL("");
    setApiKey("");
    setModel("");
    setSystemPrompt(DEFAULT_SYSTEM_PROMPT);
    setStreamEnabled(true);
  }

  function buildProviderConfig(): ProviderConfigBody {
    const providerConfig: ProviderConfigBody = {};
    if (baseURL.trim()) providerConfig.base_url = baseURL.trim();
    if (apiKey.trim()) providerConfig.api_key = apiKey.trim();
    if (model.trim()) providerConfig.model = model.trim();
    return providerConfig;
  }

  return {
    endpoint,
    baseURL,
    apiKey,
    model,
    systemPrompt,
    streamEnabled,
    serverConfig,
    configError,
    hasProviderOverride: Boolean(baseURL.trim() || apiKey.trim() || model.trim()),
    setEndpoint,
    setBaseURL,
    setApiKey,
    setModel,
    setSystemPrompt,
    setStreamEnabled,
    clearSettings,
    buildProviderConfig,
  };
}
