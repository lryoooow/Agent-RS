import { useState } from "react";
import { User, LogIn, LogOut, UserPlus, Loader2 } from "lucide-react";
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
import { Label } from "./ui/label";
import type { useAuth } from "../hooks/useAuth";

type Auth = ReturnType<typeof useAuth>;

// 账户面板：登录 / 注册 / 登出。复用 useAuth（封装 auth-api 的 me/login/register/logout）。
// DB 关闭时后端走默认用户，auth.user 仍可能为"未认证"的默认身份——按钮显示「默认用户」。
// inviteRequired 由 serverConfig 透传，决定注册表单是否显示邀请码输入框。
export function AuthDialog({ auth, inviteRequired = true }: { auth: Auth; inviteRequired?: boolean }) {
  const [open, setOpen] = useState(false);
  const authed = auth.user?.authenticated === true;
  const buttonLabel = authed ? auth.user?.name || auth.user?.email || "账户" : "登录";

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 border-border bg-card/60 text-[12px]"
        >
          <User className="size-3.5" />
          <span className="max-w-[120px] truncate">{buttonLabel}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="bg-card sm:max-w-md">
        <DialogHeader>
          <DialogTitle style={{ fontFamily: "var(--font-display)" }}>账户</DialogTitle>
          <DialogDescription className="font-mono text-[11px]">
            {authed ? "已登录，可管理你的会话、文档与记忆" : "登录后会话/文档/记忆将与账户绑定"}
          </DialogDescription>
        </DialogHeader>

        {authed ? (
          <SignedIn auth={auth} onDone={() => setOpen(false)} />
        ) : (
          <Tabs defaultValue="login" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="login">登录</TabsTrigger>
              <TabsTrigger value="register">注册</TabsTrigger>
            </TabsList>
            <TabsContent value="login">
              <LoginForm auth={auth} onDone={() => setOpen(false)} />
            </TabsContent>
            <TabsContent value="register">
              <RegisterForm auth={auth} inviteRequired={inviteRequired} onDone={() => setOpen(false)} />
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}

function SignedIn({ auth, onDone }: { auth: Auth; onDone: () => void }) {
  return (
    <div className="flex flex-col gap-3 py-1">
      <div className="rounded-lg border border-border bg-input-background px-3 py-2.5">
        <div className="text-[13px] text-foreground">{auth.user?.name || "用户"}</div>
        <div className="font-mono text-[11px] text-muted-foreground">{auth.user?.email}</div>
      </div>
      <Button
        variant="outline"
        className="gap-1.5"
        disabled={auth.loading}
        onClick={async () => {
          await auth.signOut();
          onDone();
        }}
      >
        {auth.loading ? <Loader2 className="size-4 animate-spin" /> : <LogOut className="size-4" />}
        退出登录
      </Button>
    </div>
  );
}

function LoginForm({ auth, onDone }: { auth: Auth; onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  return (
    <form
      className="flex flex-col gap-3 py-2"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await auth.signIn(email, password);
          onDone();
        } catch {
          /* error shown via auth.error */
        }
      }}
    >
      <Field label="邮箱">
        <Input value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="email" className="bg-input-background text-[13px]" />
      </Field>
      <Field label="密码">
        <Input value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="current-password" className="bg-input-background text-[13px]" />
      </Field>
      {auth.error && <p className="font-mono text-[11px] text-destructive">{auth.error}</p>}
      <Button type="submit" disabled={auth.loading} className="gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90">
        {auth.loading ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />}
        登录
      </Button>
    </form>
  );
}

function RegisterForm({
  auth,
  inviteRequired,
  onDone,
}: {
  auth: Auth;
  inviteRequired: boolean;
  onDone: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  return (
    <form
      className="flex flex-col gap-3 py-2"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await auth.signUp(email, password, name, inviteCode);
          onDone();
        } catch {
          /* error shown via auth.error */
        }
      }}
    >
      <Field label="昵称">
        <Input value={name} onChange={(e) => setName(e.target.value)} className="bg-input-background text-[13px]" />
      </Field>
      <Field label="邮箱">
        <Input value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="email" className="bg-input-background text-[13px]" />
      </Field>
      <Field label="密码">
        <Input value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="new-password" className="bg-input-background text-[13px]" />
      </Field>
      {inviteRequired && (
        <Field label="邀请码">
          <Input
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            placeholder="RS-XXXX-XXXX-XXXX"
            autoComplete="off"
            className="bg-input-background font-mono text-[13px]"
          />
        </Field>
      )}
      {auth.error && <p className="font-mono text-[11px] text-destructive">{auth.error}</p>}
      <Button type="submit" disabled={auth.loading} className="gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90">
        {auth.loading ? <Loader2 className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
        注册并登录
      </Button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}
