import type { ChatRequestBody, ConfigResponse } from "../types";
import { readErrorMessage } from "./errors";

export async function postChat(endpoint: string, body: ChatRequestBody, signal: AbortSignal) {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const apiMessage = readErrorMessage(payload);
    throw new Error(apiMessage ?? `${res.status} ${res.statusText}`);
  }

  return res;
}

export async function fetchConfig(configEndpoint: string) {
  const res = await fetch(configEndpoint, { credentials: "include" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as ConfigResponse;
}
