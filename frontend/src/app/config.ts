import type { StoredConfig } from "./types";

export const DEFAULT_ENDPOINT = "/api/chat";
export const DEFAULT_SYSTEM_PROMPT = "";
export const STORAGE_KEY = "chatbot.config.v1";

export const SUGGESTIONS = [
  "用三句话解释一下 Transformer 的注意力机制。",
  "帮我写一段关于秋天清晨的散文。",
  "Node.js 中 EventLoop 的阶段有哪些？",
  "What should I cook with eggs, miso, and rice?",
];

export function loadConfig(): StoredConfig {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function saveConfig(config: StoredConfig) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

export function clearStoredConfig() {
  window.localStorage.removeItem(STORAGE_KEY);
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

export function getApiBaseEndpoint(chatEndpoint: string) {
  try {
    const url = new URL(chatEndpoint);
    url.pathname = url.pathname.replace(/\/chat\/?$/, "");
    return url.toString().replace(/\/$/, "");
  } catch {
    return "/api";
  }
}
