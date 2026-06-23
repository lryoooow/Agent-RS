import { useEffect, useState } from "react";
import { ShieldCheck, Plus, Copy, Check, Ban, RotateCcw, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "./ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import {
  createInvite,
  listInvites,
  revokeInvite,
  listAdminUsers,
  setUserActive,
  type InviteItem,
  type AdminUserItem,
} from "../lib/admin-api";

// 管理面板：仅 is_admin 用户在 TopBar 可见。签发邀请码（明文仅展示一次）、邀请列表、用户停用/启用。
// 复用既有 ui/ 组件，零新增依赖。所有写操作后刷新对应列表。
export function AdminPanel({ endpoint }: { endpoint: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 gap-1.5 border-border bg-card/60 text-[12px]">
          <ShieldCheck className="size-3.5 text-primary" />
          管理
        </Button>
      </DialogTrigger>
      <DialogContent className="bg-card sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle style={{ fontFamily: "var(--font-display)" }}>管理控制台</DialogTitle>
          <DialogDescription className="font-mono text-[11px]">签发邀请码、管理用户</DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="invites" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="invites">邀请码</TabsTrigger>
            <TabsTrigger value="users">用户</TabsTrigger>
          </TabsList>
          <TabsContent value="invites">
            <InvitesTab endpoint={endpoint} active={open} />
          </TabsContent>
          <TabsContent value="users">
            <UsersTab endpoint={endpoint} active={open} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function InvitesTab({ endpoint, active }: { endpoint: string; active: boolean }) {
  const [invites, setInvites] = useState<InviteItem[]>([]);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [freshCode, setFreshCode] = useState("");
  const [copied, setCopied] = useState(false);

  async function refresh() {
    try {
      setError("");
      setInvites(await listInvites(endpoint));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (active) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  async function onCreate() {
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      const result = await createInvite(endpoint, { label });
      setFreshCode(result.code);
      setLabel("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke(id: string) {
    try {
      await revokeInvite(endpoint, id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="flex flex-col gap-3 py-2">
      <div className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-1.5">
          <label className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">备注（可选）</label>
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="发给谁/用途" className="bg-input-background text-[13px]" />
        </div>
        <Button size="sm" disabled={busy} onClick={onCreate} className="gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90">
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
          生成邀请码
        </Button>
      </div>

      {freshCode && (
        <div className="rounded-lg border border-primary/30 bg-primary/10 px-3 py-2.5">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            新邀请码（仅显示这一次，请立即复制保存）
          </div>
          <div className="flex items-center justify-between gap-2">
            <code className="font-mono text-[14px] text-foreground">{freshCode}</code>
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5"
              onClick={async () => {
                await navigator.clipboard.writeText(freshCode);
                setCopied(true);
              }}
            >
              {copied ? <Check className="size-3.5 text-primary" /> : <Copy className="size-3.5" />}
              {copied ? "已复制" : "复制"}
            </Button>
          </div>
        </div>
      )}

      {error && <p className="font-mono text-[11px] text-destructive">{error}</p>}

      <div className="max-h-64 overflow-y-auto rounded-lg border border-border">
        {invites.length === 0 ? (
          <p className="px-3 py-4 text-center font-mono text-[11px] text-muted-foreground">暂无邀请</p>
        ) : (
          invites.map((inv) => (
            <div key={inv.id} className="flex items-center justify-between gap-2 border-b border-border px-3 py-2 last:border-b-0">
              <div className="min-w-0">
                <div className="truncate text-[12px] text-foreground">{inv.label || "（无备注）"}</div>
                <div className="font-mono text-[10px] text-muted-foreground">
                  用量 {inv.used_count}/{inv.max_uses}
                  {inv.revoked ? " · 已撤销" : inv.used_count >= inv.max_uses ? " · 已用满" : " · 可用"}
                  {inv.expires_at ? ` · 过期 ${inv.expires_at.slice(0, 10)}` : ""}
                </div>
              </div>
              {!inv.revoked && inv.used_count < inv.max_uses && (
                <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-destructive" onClick={() => onRevoke(inv.id)}>
                  <Ban className="size-3.5" />
                  撤销
                </Button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function UsersTab({ endpoint, active }: { endpoint: string; active: boolean }) {
  const [users, setUsers] = useState<AdminUserItem[]>([]);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setError("");
      setUsers(await listAdminUsers(endpoint));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (active) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  async function onToggle(user: AdminUserItem) {
    try {
      await setUserActive(endpoint, user.id, !user.is_active);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="flex flex-col gap-3 py-2">
      {error && <p className="font-mono text-[11px] text-destructive">{error}</p>}
      <div className="max-h-72 overflow-y-auto rounded-lg border border-border">
        {users.length === 0 ? (
          <p className="px-3 py-4 text-center font-mono text-[11px] text-muted-foreground">暂无用户</p>
        ) : (
          users.map((user) => (
            <div key={user.id} className="flex items-center justify-between gap-2 border-b border-border px-3 py-2 last:border-b-0">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-[12px] text-foreground">{user.name || user.email}</span>
                  {user.is_admin && (
                    <span className="rounded border border-primary/25 bg-primary/10 px-1 font-mono text-[9px] text-primary">管理员</span>
                  )}
                  {!user.is_active && (
                    <span className="rounded border border-destructive/25 bg-destructive/10 px-1 font-mono text-[9px] text-destructive">已停用</span>
                  )}
                </div>
                <div className="font-mono text-[10px] text-muted-foreground">{user.email}</div>
              </div>
              {!user.is_admin && (
                <Button
                  variant="ghost"
                  size="sm"
                  className={`h-7 gap-1.5 ${user.is_active ? "text-destructive" : "text-primary"}`}
                  onClick={() => onToggle(user)}
                >
                  {user.is_active ? <Ban className="size-3.5" /> : <RotateCcw className="size-3.5" />}
                  {user.is_active ? "停用" : "启用"}
                </Button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
