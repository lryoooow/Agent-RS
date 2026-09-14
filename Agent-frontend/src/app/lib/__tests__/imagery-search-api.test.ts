// 端点拼装回归：检索/导入必须把聊天端点转成 API 基址再拼路径。
// 此前直接拼 `${endpoint}/scenes/...`（endpoint=/api/chat）导致所有检索 404。
import { describe, it, expect, vi, afterEach } from "vitest";
import { importScene, searchImagery } from "../imagery-search-api";

function lastFetchUrl(): string {
  return (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
}

afterEach(() => vi.unstubAllGlobals());

describe("imagery-search-api 端点拼装", () => {
  it("searchImagery 用 /api/chat 端点时请求 /api/scenes/search", async () => {
    const mock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ scenes: [], notes: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", mock);
    await searchImagery({ bbox: [0, 0, 1, 1] });
    expect(lastFetchUrl()).toBe("/api/scenes/search");
  });

  it("importScene 同样剥掉 /chat 后拼路径", async () => {
    const mock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ imagery_id: "a", item_id: "b", satellite: "S", band_roles: {} }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", mock);
    await importScene("ab12cd34ef56");
    expect(lastFetchUrl()).toBe("/api/scenes/ab12cd34ef56/import");
  });

  it("基址来自模块级 API_BASE（默认相对 /api）", async () => {
    const mock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ scenes: [], notes: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", mock);
    await searchImagery({});
    expect(lastFetchUrl()).toBe("/api/scenes/search");
  });
});
