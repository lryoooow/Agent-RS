import { apiFetch } from "./http";

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  authenticated: boolean;
};

function isAuthUser(value: unknown): value is AuthUser {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.id === "string" && typeof v.email === "string" && typeof v.authenticated === "boolean";
}

async function userFrom(path: string, init: Parameters<typeof apiFetch>[1]): Promise<AuthUser> {
  const response = await apiFetch(path, init);
  const payload = (await response.json().catch(() => null)) as { user?: unknown } | null;
  const user = payload?.user;
  if (!isAuthUser(user)) {
    // 200 但载荷异常（代理劫持/网关页）：按未登录处理而不是崩成 undefined。
    return { id: "", email: "", name: "", authenticated: false };
  }
  return user;
}

export async function fetchMe(): Promise<AuthUser> {
  return userFrom("/auth/me", {});
}

export async function login(email: string, password: string): Promise<AuthUser> {
  return userFrom("/auth/login", { method: "POST", json: { email, password }, timeoutMs: 15_000 });
}

export async function register(email: string, password: string, name: string): Promise<AuthUser> {
  return userFrom("/auth/register", { method: "POST", json: { email, password, name }, timeoutMs: 15_000 });
}

export async function logout(): Promise<void> {
  await apiFetch("/auth/logout", { method: "POST" });
}
