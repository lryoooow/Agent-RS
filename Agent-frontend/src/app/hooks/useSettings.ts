import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearStoredConfig,
  DEFAULT_ENDPOINT,
  DEFAULT_SYSTEM_PROMPT,
  loadConfig,
  saveConfig,
} from "../config";
import { fetchBootstrapConfig, fetchConfig, fetchModels } from "../lib/chat-api";
import type {
  AvailableModel,
  BootstrapConfigResponse,
  ConfigResponse,
  ProviderConfig,
  ThinkingStrength,
} from "../types";

export function useSettings(authenticated = false, principalId: string | null = null) {
  const [stored] = useState(() => loadConfig());
  const endpoint = DEFAULT_ENDPOINT;
  const [systemPrompt, setSystemPrompt] = useState(stored.systemPrompt ?? DEFAULT_SYSTEM_PROMPT);
  const [streamEnabled, setStreamEnabled] = useState(stored.streamEnabled ?? true);
  const [useRag, setUseRag] = useState(stored.useRag ?? false);
  const [model, setModel] = useState(stored.model ?? "");
  // Credentials deliberately live only in React memory. Reloading the page clears
  // them; saveConfig never writes them to browser storage.
  const [providerConfig, setProviderConfig] = useState<ProviderConfig | null>(null);
  const [thinkingStrength, setThinkingStrength] = useState<ThinkingStrength>(
    stored.thinkingStrength ?? "medium",
  );
  const [tavilyApiKey, setTavilyApiKey] = useState("");
  const [bootstrapConfig, setBootstrapConfig] = useState<BootstrapConfigResponse | null>(null);
  const [serverConfig, setServerConfig] = useState<ConfigResponse | null>(null);
  const [configError, setConfigError] = useState("");
  const [availableModels, setAvailableModels] = useState<AvailableModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const [configRevision, setConfigRevision] = useState(0);
  const retryConfig = useCallback(() => setConfigRevision((value) => value + 1), []);
  const modelsRequestRef = useRef<{ controller: AbortController; owner: string | null; provider: ProviderConfig | null } | null>(null);
  const providerRef = useRef(providerConfig);
  providerRef.current = providerConfig;
  const credentialOwnerRef = useRef<string | null>(principalId);

  // Provider 与搜索密钥只属于当前登录主体和当前页面会话。退出登录或切换账号时
  // 立即清空，避免同一浏览器中后登录的用户继承前一用户的凭据。
  useEffect(() => {
    if (credentialOwnerRef.current === principalId) return;
    credentialOwnerRef.current = principalId;
    setProviderConfig(null);
    setTavilyApiKey("");
    setAvailableModels([]);
    setModelsError("");
  }, [principalId]);

  useEffect(() => {
    const pending = modelsRequestRef.current;
    modelsRequestRef.current = null;
    pending?.controller.abort();
    setAvailableModels([]);
    setModelsLoading(false);
    setModelsError("");
    return () => {
      modelsRequestRef.current?.controller.abort();
      modelsRequestRef.current = null;
    };
  }, [principalId, providerConfig]);

  useEffect(() => {
    saveConfig({
      systemPrompt,
      streamEnabled,
      useRag,
      model,
      thinkingStrength,
    });
  }, [systemPrompt, streamEnabled, useRag, model, thinkingStrength]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    async function loadBootstrap() {
      try {
        setConfigError("");
        const data = await fetchBootstrapConfig(controller.signal);
        if (!cancelled) setBootstrapConfig(data);
      } catch (err) {
        if (!cancelled) {
          setBootstrapConfig(null);
          setConfigError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    void loadBootstrap();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [configRevision]);

  useEffect(() => {
    if (!bootstrapConfig) return;
    if (bootstrapConfig.auth_required && !authenticated) {
      setServerConfig(null);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    async function loadServerConfig() {
      try {
        setConfigError("");
        const data = await fetchConfig(controller.signal);
        if (!cancelled) setServerConfig(data);
      } catch (err) {
        if (!cancelled) {
          setServerConfig(null);
          setConfigError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    void loadServerConfig();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [authenticated, principalId, bootstrapConfig, configRevision]);

  const refreshModels = useCallback(async () => {
    if (modelsRequestRef.current || credentialOwnerRef.current !== principalId) return;
    const pending = { controller: new AbortController(), owner: principalId, provider: providerConfig };
    modelsRequestRef.current = pending;
    const current = () => modelsRequestRef.current === pending &&
      credentialOwnerRef.current === pending.owner && providerRef.current === pending.provider;
    setModelsLoading(true);
    setModelsError("");
    try {
      const data = await fetchModels(providerConfig, model || serverConfig?.default_model, pending.controller.signal);
      if (current()) setAvailableModels(data.models);
    } catch (err) {
      if (current()) setModelsError(err instanceof Error ? err.message : String(err));
    } finally {
      if (current()) {
        modelsRequestRef.current = null;
        setModelsLoading(false);
      }
    }
  }, [principalId, model, providerConfig, serverConfig?.default_model]);

  function clearSettings() {
    modelsRequestRef.current?.controller.abort();
    modelsRequestRef.current = null;
    setModelsLoading(false);
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
    bootstrapConfig,
    serverConfig,
    configError,
    retryConfig,
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
