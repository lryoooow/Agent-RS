import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSettings } from "../useSettings";

describe("useSettings provider credential ownership", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("退出登录或切换用户时清除当前页面中的供应商密钥", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/config/bootstrap")) {
        return Promise.resolve(new Response(JSON.stringify({ auth_required: true, invite_required: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return Promise.resolve(new Response(JSON.stringify({
        provider: "openai-compatible",
        base_url_configured: true,
        api_key_configured: true,
        default_model: "deepseek-v4-pro",
        allow_client_provider_config: true,
        prompt_profile: "default",
        prompt_dynamic_modules_enabled: true,
        system_prompt_language: "zh-CN",
        allow_user_extra_instructions: false,
        auth_required: true,
        invite_required: false,
        web_search_enabled: true, web_search_configured: true,
        agent_framework: "autogen", available_flows: [], auto_flow_enabled: true,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(
      ({ principalId }) => useSettings(Boolean(principalId), principalId),
      { initialProps: { principalId: "user-a" as string | null } },
    );
    await waitFor(() => expect(result.current.serverConfig).not.toBeNull());

    act(() => {
      result.current.setProviderConfig({
        api_key: "user-a-secret",
        base_url: "https://api.deepseek.com/v1",
      });
      result.current.setTavilyApiKey("user-a-search-secret");
    });
    expect(result.current.providerConfig?.api_key).toBe("user-a-secret");

    rerender({ principalId: "user-b" });

    await waitFor(() => expect(result.current.providerConfig).toBeNull());
    expect(result.current.tavilyApiKey).toBe("");
    expect(result.current.availableModels).toEqual([]);
  });
});
