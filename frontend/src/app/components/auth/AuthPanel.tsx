import { LogIn, LogOut, UserPlus } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";
import type { AuthUser } from "../../lib/auth-api";

type AuthPanelProps = {
  user: AuthUser | null;
  loading: boolean;
  error: string;
  onLogin: (email: string, password: string) => Promise<void>;
  onRegister: (email: string, password: string, name: string) => Promise<void>;
  onLogout: () => Promise<void>;
};

export function AuthPanel({
  user,
  loading,
  error,
  onLogin,
  onRegister,
  onLogout,
}: AuthPanelProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (mode === "login") {
      await onLogin(email, password);
    } else {
      await onRegister(email, password, name);
    }
    setPassword("");
  }

  return (
    <div className="border-b border-border bg-card/60 px-6 md:px-10 py-5">
      <div className="mx-auto max-w-3xl border border-border rounded-md p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-[11px] tracking-[0.18em] uppercase text-muted-foreground">account</div>
            <div className="mt-1 text-sm">
              {user?.authenticated ? `${user.name || user.email} · ${user.email}` : "未登录时使用默认本地用户"}
            </div>
          </div>
          {user?.authenticated && (
            <button
              type="button"
              onClick={onLogout}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
            >
              <LogOut className="size-3.5" />
              logout
            </button>
          )}
        </div>

        {!user?.authenticated && (
          <form onSubmit={submit} className="mt-4 grid gap-3">
            <div className="inline-flex w-fit rounded-md border border-border p-1 text-xs">
              <button
                type="button"
                onClick={() => setMode("login")}
                className={`rounded px-3 py-1 ${mode === "login" ? "bg-foreground text-background" : ""}`}
              >
                login
              </button>
              <button
                type="button"
                onClick={() => setMode("register")}
                className={`rounded px-3 py-1 ${mode === "register" ? "bg-foreground text-background" : ""}`}
              >
                register
              </button>
            </div>
            {mode === "register" && (
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="name"
                className="rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground"
              />
            )}
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="email"
              className="rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground"
            />
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="password"
              className="rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground"
            />
            {error && <div className="text-xs text-destructive">{error}</div>}
            <button
              type="submit"
              disabled={loading || !email.trim() || !password}
              className="inline-flex w-fit items-center gap-1.5 rounded-md bg-foreground px-3 py-2 text-xs text-background disabled:opacity-50"
            >
              {mode === "login" ? <LogIn className="size-3.5" /> : <UserPlus className="size-3.5" />}
              {mode}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
