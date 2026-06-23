import { getApiBaseEndpoint } from "../config";
import { readErrorMessage } from "./errors";

export type InviteItem = {
  id: string;
  label: string;
  expires_at: string | null;
  max_uses: number;
  used_count: number;
  revoked: boolean;
  created_at: string;
};

export type AdminUserItem = {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
};

export type CreateInviteResult = { invite: InviteItem; code: string };

export async function createInvite(
  chatEndpoint: string,
  opts: { label?: string; expiresInDays?: number | null; maxUses?: number },
): Promise<CreateInviteResult> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/admin/invites`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      label: opts.label ?? "",
      expires_in_days: opts.expiresInDays ?? null,
      max_uses: opts.maxUses ?? 1,
    }),
  });
  if (!res.ok) throw await readApiError(res);
  return (await res.json()) as CreateInviteResult;
}

export async function listInvites(chatEndpoint: string): Promise<InviteItem[]> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/admin/invites`, {
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { invites: InviteItem[] };
  return payload.invites;
}

export async function revokeInvite(chatEndpoint: string, inviteId: string): Promise<void> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/admin/invites/${inviteId}/revoke`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
}

export async function listAdminUsers(chatEndpoint: string): Promise<AdminUserItem[]> {
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/admin/users`, {
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
  const payload = (await res.json()) as { users: AdminUserItem[] };
  return payload.users;
}

export async function setUserActive(
  chatEndpoint: string,
  userId: string,
  active: boolean,
): Promise<void> {
  const action = active ? "activate" : "deactivate";
  const res = await fetch(`${getApiBaseEndpoint(chatEndpoint)}/admin/users/${userId}/${action}`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw await readApiError(res);
}

async function readApiError(res: Response) {
  const payload = await res.json().catch(() => null);
  return new Error(readErrorMessage(payload) ?? `${res.status} ${res.statusText}`);
}
