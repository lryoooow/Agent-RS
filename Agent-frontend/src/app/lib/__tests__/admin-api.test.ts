import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createInvite,
  listInvites,
  revokeInvite,
  listAdminUsers,
  setUserActive,
} from "../admin-api";

// 验证 admin-api 各调用打到正确端点/方法/body，并带 credentials（cookie 鉴权）。
// fetch 用 mock，不触真实后端。

const ENDPOINT = "/api/chat";

function mockFetch(payload: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 403,
    statusText: ok ? "OK" : "Forbidden",
    json: async () => payload,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("admin-api", () => {
  it("createInvite POSTs to /admin/invites with body and credentials", async () => {
    const fn = mockFetch({ invite: { id: "1", label: "x", expires_at: null, max_uses: 1, used_count: 0, revoked: false, created_at: "" }, code: "RS-AAAA-BBBB-CCCC" });
    const res = await createInvite(ENDPOINT, { label: "x", maxUses: 1 });
    expect(res.code).toBe("RS-AAAA-BBBB-CCCC");
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/admin/invites");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(init.body)).toMatchObject({ label: "x", max_uses: 1 });
  });

  it("listInvites GETs /admin/invites", async () => {
    const fn = mockFetch({ invites: [] });
    const out = await listInvites(ENDPOINT);
    expect(out).toEqual([]);
    expect(fn.mock.calls[0][0]).toBe("/api/admin/invites");
  });

  it("revokeInvite POSTs to revoke path", async () => {
    const fn = mockFetch({ revoked: true });
    await revokeInvite(ENDPOINT, "abc");
    expect(fn.mock.calls[0][0]).toBe("/api/admin/invites/abc/revoke");
    expect(fn.mock.calls[0][1].method).toBe("POST");
  });

  it("listAdminUsers GETs /admin/users", async () => {
    const fn = mockFetch({ users: [] });
    await listAdminUsers(ENDPOINT);
    expect(fn.mock.calls[0][0]).toBe("/api/admin/users");
  });

  it("setUserActive(false) hits deactivate, (true) hits activate", async () => {
    const fn = mockFetch({ deactivated: true });
    await setUserActive(ENDPOINT, "u1", false);
    expect(fn.mock.calls[0][0]).toBe("/api/admin/users/u1/deactivate");

    mockFetch({ activated: true });
    await setUserActive(ENDPOINT, "u1", true);
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/admin/users/u1/activate",
    );
  });

  it("throws with server error message on non-ok", async () => {
    mockFetch({ error: { code: "ADMIN_REQUIRED", message: "需要管理员权限。" } }, false);
    await expect(listInvites(ENDPOINT)).rejects.toThrow("需要管理员权限。");
  });
});
