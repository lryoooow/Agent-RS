import { beforeEach, describe, expect, it } from "vitest";
import { loadConfig, saveConfig, STORAGE_KEY } from "../config";
import type { StoredConfig } from "../types";

describe("browser configuration storage", () => {
  beforeEach(() => localStorage.clear());

  it("removes legacy provider and search credentials immediately", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        model: "model-a",
        apiKey: "provider-secret",
        baseUrl: "https://private-provider.example/v1",
        tavilyApiKey: "search-secret",
      }),
    );

    expect(loadConfig()).toEqual({
      systemPrompt: undefined,
      streamEnabled: undefined,
      useRag: undefined,
      model: "model-a",
      thinkingStrength: undefined,
    });
    const rewritten = localStorage.getItem(STORAGE_KEY) ?? "";
    expect(rewritten).not.toContain("provider-secret");
    expect(rewritten).not.toContain("search-secret");
    expect(rewritten).not.toContain("private-provider");
  });

  it("persists preferences but drops unexpected credential fields", () => {
    saveConfig({
      model: "model-b",
      thinkingStrength: "max",
      apiKey: "must-not-persist",
    } as StoredConfig & { apiKey: string });

    const raw = localStorage.getItem(STORAGE_KEY) ?? "";
    expect(raw).toContain("model-b");
    expect(raw).not.toContain("must-not-persist");
  });
});
