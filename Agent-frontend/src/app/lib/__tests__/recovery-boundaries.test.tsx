import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Markdown } from "../../components/Markdown";
import { useSettings } from "../../hooks/useSettings";
import { automaticMarkdownImage } from "../markdown-media";
import { advanceAuthEpoch, currentAuthEpoch, notifyAuthFailure, subscribeAuthExpiry } from "../auth-session";
import { apiFetch } from "../http";
import { toModelHistory, exceedsMessageLimit } from "../turns";

const validConfig = { provider:"test", base_url_configured:true, api_key_configured:true,
  allow_client_provider_config:false, prompt_profile:"default", prompt_dynamic_modules_enabled:true,
  system_prompt_language:"zh-CN", allow_user_extra_instructions:true, web_search_enabled:false,
  web_search_configured:false, auth_required:false, invite_required:false, agent_framework:"autogen",
  available_flows:[], auto_flow_enabled:false };
afterEach(() => vi.unstubAllGlobals());
it("external Markdown images produce no img resource; explicit links remain available", () => {
  const { container } = render(<Markdown>{"![bad](https://example.org/collect?private=1)"}</Markdown>);
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText("打开图片")).toHaveAttribute("rel", "noopener noreferrer");
});
it("only owned-result routes can be automatically loaded", () => {
  expect(automaticMarkdownImage("/api/imagery/aaaaaaaaaaaa/results/image.png", "https://local.test")).toBe("https://local.test/api/imagery/aaaaaaaaaaaa/results/image.png");
  for (const value of ["//local.test/api/imagery/aaaaaaaaaaaa/results/a.png", "data:image/svg+xml,a", "blob:foo", "https://u:p@local.test/api/imagery/aaaaaaaaaaaa/results/a.png", "/api/auth/logout", "https://foreign.test/a.png"]) {
    expect(automaticMarkdownImage(value,"https://local.test")).toBeNull();
  }
});
it("Unicode limits match Python characters and old rejected messages do not poison history", () => {
  expect(exceedsMessageLimit("😀".repeat(16000))).toBe(false);
  expect(exceedsMessageLimit("😀".repeat(16001))).toBe(true);
  const rows = Array.from({ length: 70 }, (_, i) => ({ id: String(i), role: "user" as const, content: String(i) }));
  rows.push({ id: "bad", role: "user", content: "x".repeat(16001) });
  const history = toModelHistory(rows, "new");
  expect(history).toHaveLength(64);
  expect(history[history.length-1]?.content).toBe("new");
  expect(history.some((m) => m.content.length > 16000)).toBe(false);
});
it("one session-expiry notification; provider401 and stale requests do not log out new sessions", async () => {
  advanceAuthEpoch();
  const listener = vi.fn(); const unsubscribe = subscribeAuthExpiry(listener);
  try {
    const old=currentAuthEpoch();
    notifyAuthFailure("AUTH_ERROR",old);
    expect(listener).not.toHaveBeenCalled();
    advanceAuthEpoch();
    notifyAuthFailure("AUTH_REQUIRED",old);
    expect(listener).not.toHaveBeenCalled();
    notifyAuthFailure("AUTHENTICATION_REQUIRED",currentAuthEpoch());
    notifyAuthFailure("AUTHENTICATION_REQUIRED",currentAuthEpoch());
    expect(listener).toHaveBeenCalledTimes(1);
  } finally { unsubscribe(); }
});
it("late HTTP401 cannot expire a newer sign-in", async () => {
  advanceAuthEpoch(); let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch",vi.fn(() => new Promise<Response>((r) => { resolve=r; })));
  const listener=vi.fn(); const unsubscribe=subscribeAuthExpiry(listener);
  const request=apiFetch("/imagery").catch((error) => error);
  advanceAuthEpoch();
  resolve(new Response(JSON.stringify({ error: { code: "AUTH_REQUIRED", message: "expired" } }),{status:401}));
  await request; expect(listener).not.toHaveBeenCalled(); unsubscribe();
});
it("bootstrap failure is visible and retry can recover", async () => {
  const fetch=vi.fn().mockResolvedValueOnce(new Response("error",{status:500})).mockImplementation((input) => Promise.resolve(new Response(JSON.stringify(String(input).includes("bootstrap") ? {auth_required:false} : validConfig),{status:200})));
  vi.stubGlobal("fetch",fetch);
  const { result } = renderHook(() => useSettings(false,null));
  await waitFor(() => expect(result.current.configError).not.toBe(""));
  act(() => result.current.retryConfig());
  await waitFor(() => expect(result.current.bootstrapConfig).toEqual({auth_required:false}));
  expect(result.current.configError).toBe("");
});


it("an invalid HTTP200 configuration is recoverable and never treated as ready", async () => {
  vi.stubGlobal("fetch", vi.fn((input) => Promise.resolve(new Response(JSON.stringify(
    String(input).includes("bootstrap") ? {auth_required:false} : {auth_required:"false"}),{status:200}))));
  const { result } = renderHook(() => useSettings(false,null));
  await waitFor(() => expect(result.current.configError).toContain("格式异常"));
  expect(result.current.serverConfig).toBeNull();
});

it("old model discovery cannot overwrite another user's models or loading state", async () => {
  const pending: Array<(r:Response)=>void> = [];
  vi.stubGlobal("fetch",vi.fn((input) => {
    if (String(input).includes("models")) return new Promise<Response>((resolve) => pending.push(resolve));
    return Promise.resolve(new Response(JSON.stringify(String(input).includes("bootstrap") ? {auth_required:false} : validConfig),{status:200}));
  }));
  const { result, rerender } = renderHook(({owner}) => useSettings(true,owner),{initialProps:{owner:"a"}});
  await waitFor(() => expect(result.current.serverConfig).not.toBeNull());
  let old!:Promise<void>;
  act(() => {old=result.current.refreshModels();});
  rerender({owner:"b"});
  let next!:Promise<void>;
  act(() => {next=result.current.refreshModels();});
  await act(async () => { pending[0](new Response(JSON.stringify({models:[{id:"old-user-model"}],current_model:"old"}))); await old; });
  expect(result.current.availableModels).toEqual([]);
  expect(result.current.modelsLoading).toBe(true);
  await act(async () => { pending[1](new Response(JSON.stringify({models:[{id:"new-user-model"}],current_model:"new"}))); await next; });
  expect(result.current.availableModels).toEqual([{id:"new-user-model"}]);
  expect(result.current.modelsLoading).toBe(false);
});

it("the actual backend authentication error expires an active session", async () => {
  advanceAuthEpoch();const listener=vi.fn();const unsubscribe=subscribeAuthExpiry(listener);
  vi.stubGlobal("fetch",vi.fn(() => Promise.resolve(new Response(JSON.stringify({error:{code:"AUTHENTICATION_REQUIRED",message:"login required"}}),{status:401}))));
  try { await expect(apiFetch("/imagery")).rejects.toThrow("login required"); expect(listener).toHaveBeenCalledTimes(1); }
  finally {unsubscribe();}
});
