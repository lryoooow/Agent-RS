import { useState, type FormEvent } from "react";
import { LogIn, LogOut, UserPlus, User } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { useAuth } from "../../hooks/useAuth";

// Auth entry for the top bar. Unauthenticated users fall back to the backend's
// default user, so the app stays usable without login.
export function AuthDialog({ endpoint }: { endpoint: string }) {
  const auth = useAuth(endpoint);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");

  const authed = auth.user?.authenticated ?? false;

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      if (mode === "login") {
        await auth.signIn(email, password);
      } else {
        await auth.signUp(email, password, name);
      }
      setPassword("");
      setOpen(false);
    } catch {
      // error surfaced via auth.error
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          className="flex items-center gap-1.5 rounded-full border border-border bg-card/60 px-3 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
          title="账户"
        >
          <User className="size-3.5 text-primary" />
          <span className="max-w-[120px] truncate text-foreground/85">
            {authed ? auth.user?.name || auth.user?.email : "默认用户"}
          </span>
        </button>
      </DialogTrigger>
      <DialogContent className="bg-card sm:max-w-sm">
        <DialogHeader>
          <DialogTitle style={{ fontFamily: "var(--font-display)" }}>账户</DialogTitle>
          <DialogDescription className="font-mono text-[11px]">
            {authed ? "已登录" : "未登录时使用后端默认用户，登录后会话与知识库归属你的账户"}
          </DialogDescription>
        </DialogHeader>

        {authed ? (
          <div className="flex flex-col gap-3 py-1">
            <div className="rounded-lg border border-border bg-background/50 px-3 py-2.5 text-sm">
              <div className="text-foreground">{auth.user?.name || auth.user?.email}</div>
              <div className="font-mono text-[11px] text-muted-foreground">{auth.user?.email}</div>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={auth.loading}
              onClick={async () => {
                await auth.signOut();
                setOpen(false);
              }}
              className="gap-1.5"
            >
              <LogOut className="size-3.5" />
              退出登录
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3 py-1">
            <div className="inline-flex w-fit rounded-lg border border-border p-1 text-xs">
              <button
                type="button"
                onClick={() => setMode("login")}
                className={`rounded px-3 py-1 ${mode === "login" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
              >
                登录
              </button>
              <button
                type="button"
                onClick={() => setMode("register")}
                className={`rounded px-3 py-1 ${mode === "register" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
              >
                注册
              </button>
            </div>
            {mode === "register" && (
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="昵称"
                className="bg-input-background text-[13px]"
              />
            )}
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="邮箱"
              className="bg-input-background text-[13px]"
            />
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="密码"
              className="bg-input-background text-[13px]"
            />
            {auth.error && <p className="text-[12px] text-destructive">{auth.error}</p>}
            <Button
              type="submit"
              size="sm"
              disabled={auth.loading || !email.trim() || !password}
              className="w-fit gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
            >
              {mode === "login" ? <LogIn className="size-3.5" /> : <UserPlus className="size-3.5" />}
              {mode === "login" ? "登录" : "注册"}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
