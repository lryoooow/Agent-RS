import type { StoredConfig } from "./types";

// 新前端固定走相对 /api/chat（靠 vite proxy 透到后端 3000，cookie 同源）。
// new URL("/api/chat") 在相对路径下抛错 → 下面各派生函数命中 catch 回退到固定 /api 系列，
// 函数体保持与老前端一致，零改动复用。
export const DEFAULT_ENDPOINT = "/api/chat";
export const DEFAULT_SYSTEM_PROMPT = "";
export const STORAGE_KEY = "agent-rs.config.v1";
// Legacy key kept so existing browsers migrate to the Agent-RS key on save.
const LEGACY_STORAGE_KEY = "chatbot.config.v1";

export function loadConfig(): StoredConfig {
  try {
    const raw =
      window.localStorage.getItem(STORAGE_KEY) ?? window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const safe: StoredConfig = {
      systemPrompt: typeof parsed.systemPrompt === "string" ? parsed.systemPrompt : undefined,
      streamEnabled: typeof parsed.streamEnabled === "boolean" ? parsed.streamEnabled : undefined,
      useRag: typeof parsed.useRag === "boolean" ? parsed.useRag : undefined,
      model: typeof parsed.model === "string" ? parsed.model : undefined,
      thinkingStrength:
        parsed.thinkingStrength === "low" ||
        parsed.thinkingStrength === "medium" ||
        parsed.thinkingStrength === "max"
          ? parsed.thinkingStrength
          : undefined,
    };
    // Rewrite legacy records immediately so provider/search secrets no longer
    // remain on disk until the next React render.
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(safe));
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    return safe;
  } catch {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    } catch {
      // Browser privacy mode may make storage unavailable.
    }
    return {};
  }
}

export function saveConfig(config: StoredConfig) {
  try {
    // Persist preferences only. Credentials live in React memory for this page
    // session and disappear on refresh or browser close.
    const safe: StoredConfig = {
      systemPrompt: config.systemPrompt,
      streamEnabled: config.streamEnabled,
      useRag: config.useRag,
      model: config.model,
      thinkingStrength: config.thinkingStrength,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(safe));
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch (err) {
    console.warn("Failed to save local config", err);
  }
}

export function clearStoredConfig() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch (err) {
    console.warn("Failed to clear local config", err);
  }
}

export function getConfigEndpoint(chatEndpoint: string) {
  try {
    const url = new URL(chatEndpoint);
    url.pathname = url.pathname.replace(/\/chat\/?$/, "/config");
    return url.toString();
  } catch {
    return "/api/config";
  }
}

export function getDocumentsEndpoint(chatEndpoint: string) {
  try {
    const url = new URL(chatEndpoint);
    url.pathname = url.pathname.replace(/\/chat\/?$/, "/documents");
    return url.toString();
  } catch {
    return "/api/documents";
  }
}

export function getModelsEndpoint(chatEndpoint: string) {
  try {
    const url = new URL(chatEndpoint);
    url.pathname = url.pathname.replace(/\/chat\/?$/, "/config/models");
    return url.toString();
  } catch {
    return "/api/config/models";
  }
}

export function getApiBaseEndpoint(chatEndpoint: string) {
  try {
    const url = new URL(chatEndpoint);
    url.pathname = url.pathname.replace(/\/chat\/?$/, "");
    return url.toString().replace(/\/$/, "");
  } catch {
    return "/api";
  }
}
