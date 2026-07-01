import { describe, it, expect } from "vitest";
import { resolveAppGate } from "../app-gate";
import type { ConfigResponse } from "../../types";

// resolveAppGate 纯函数测试：三态判定 + 历史 bug（首屏闪烁）回归。
// 闪烁根因：旧逻辑 `authRequired && !authed && !loading` 在 loading 期间为假 → 先渲染主应用再跳登录。
// 新逻辑把"未就绪"显式收敛为 splash，本套件锁死这一行为。

function cfg(overrides: Partial<ConfigResponse> = {}): ConfigResponse {
  return {
    provider: "openai-compatible",
    base_url_configured: true,
    api_key_configured: true,
    allow_client_provider_config: true,
    prompt_profile: "agent_rs_core_v1",
    prompt_dynamic_modules_enabled: true,
    system_prompt_language: "zh-CN",
    allow_user_extra_instructions: true,
    web_search_enabled: true,
    web_search_configured: true,
    auth_required: true,
    invite_required: false,
    ...overrides,
  };
}

describe("resolveAppGate", () => {
  it("【未就绪】serverConfig 为 null → splash（拿不到配置不预判）", () => {
    expect(resolveAppGate({ serverConfig: null, authLoading: false, authed: false })).toBe("splash");
    // 即便 config 已到，但会话仍在解析也应 splash
    expect(resolveAppGate({ serverConfig: null, authLoading: true, authed: true })).toBe("splash");
  });

  it("【历史闪烁回归】auth_required 且 authLoading=true → splash，绝不先渲染主应用", () => {
    // 旧逻辑此处会落到 app（因 !loading 为假使门控失效）→ 闪屏。新逻辑必须是 splash。
    const gate = resolveAppGate({ serverConfig: cfg(), authLoading: true, authed: false });
    expect(gate).toBe("splash");
  });

  it("【需登录】config 就绪 + 需登录 + 未认证 → login", () => {
    expect(resolveAppGate({ serverConfig: cfg(), authLoading: false, authed: false })).toBe("login");
  });

  it("【已登录】config 就绪 + 需登录 + 已认证 → app", () => {
    expect(resolveAppGate({ serverConfig: cfg(), authLoading: false, authed: true })).toBe("app");
  });

  it("【兜底】auth_required=false（如 DB 关闭）→ 直接 app，即便未认证", () => {
    const gate = resolveAppGate({
      serverConfig: cfg({ auth_required: false }),
      authLoading: false,
      authed: false,
    });
    expect(gate).toBe("app");
  });
});
