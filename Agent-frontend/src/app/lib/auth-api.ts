import { getApiBaseEndpoint } from "../config";
import { readErrorMessage } from "./errors";

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  authenticated: boolean;
};

export async function fetchMe(chatEndpoint: string): Promise<AuthUser> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/auth/me`, {
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { user: AuthUser };
  return payload.user;
}

export async function login(
  chatEndpoint: string,
  email: string,
  password: string,
): Promise<AuthUser> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { user: AuthUser };
  return payload.user;
}

export async function register(
  chatEndpoint: string,
  email: string,
  password: string,
  name: string,
): Promise<AuthUser> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password, name }),
  });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { user: AuthUser };
  return payload.user;
}

export async function logout(chatEndpoint: string): Promise<void> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
}

async function readApiError(res: Response) {
  const payload = await res.json().catch(() => null);
  return new Error(readErrorMessage(payload) ?? `${res.status} ${res.statusText}`);
}
