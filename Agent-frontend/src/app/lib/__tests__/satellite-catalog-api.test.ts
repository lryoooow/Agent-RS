import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchSatelliteCatalog, parseSatelliteCatalog } from "../satellite-catalog-api";

const data = () => ({ updated: "2026-10-10T02:04:00Z", groups: ["active", "resource", "weather"].map((name) => ({ name, count: 12, updated: "2026-10-10T02:04:00Z" })), stale: true, refreshing: false });
afterEach(() => vi.unstubAllGlobals());
describe("卫星目录状态", () => {
  it("保留更新时间和陈旧状态，不把多个重复分组相加", () => {
    expect(parseSatelliteCatalog(data())).toEqual(data());
  });
  it.each([null, {}, { groups: [] }, { ...data(), updated: "bad-date" }, { ...data(), groups: [{ name: "resource", count: 0, updated: "2026-10-10" }] }, { ...data(), groups: [data().groups[0], data().groups[0]] }])("拒绝空目录和无效响应 %#", (value) => {
    expect(parseSatelliteCatalog(value)).toBeUndefined();
  });
  it("请求与 SatVis 相同的同源接口", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(data())));
    vi.stubGlobal("fetch", fetch);
    expect(await fetchSatelliteCatalog()).toEqual(data());
    expect(fetch.mock.calls[0][0]).toBe("/api/groups.json");
    expect(fetch.mock.calls[0][1].credentials).toBe("include");
  });
  it("404 应呈现错误而不是成功的空列表", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Not Found", { status: 404 })));
    await expect(fetchSatelliteCatalog()).rejects.toMatchObject({ status: 404 });
  });
  it("200 空目录也必须报错", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ updated: "2026-10-10", groups: [] }))));
    await expect(fetchSatelliteCatalog()).rejects.toMatchObject({ code: "BAD_PAYLOAD" });
  });
});
