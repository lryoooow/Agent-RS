import { useState } from "react";
import { LogIn, UserPlus, Loader2 } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Logo } from "./Logo";
import type { useAuth } from "../hooks/useAuth";

type Auth = ReturnType<typeof useAuth>;

// 全屏登录门：auth_required 且未登录时由 App 渲染，挡在整个应用前。
// 与 AuthDialog 表单逻辑一致，但以独立全屏页呈现（强制登录场景没有"先进应用再登录"的入口）。
export function AuthGate({ auth, inviteRequired }: { auth: Auth; inviteRequired: boolean }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm rounded-2xl border border-border bg-card/80 p-6 shadow-xl backdrop-blur-xl">
        <div className="mb-5 flex flex-col items-center gap-2 text-center">
          <Logo size={44} rounded="rounded-xl" />
          <div className="text-[17px] tracking-tight text-foreground" style={{ fontFamily: "var(--font-display)" }}>
            Agent-RS
          </div>
          <p className="font-mono text-[11px] text-muted-foreground">遥感大模型应用智能体 · 登录后使用</p>
        </div>

        <Tabs defaultValue="login" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="login">登录</TabsTrigger>
            <TabsTrigger value="register">注册</TabsTrigger>
          </TabsList>
          <TabsContent value="login">
            <LoginForm auth={auth} />
          </TabsContent>
          <TabsContent value="register">
            <RegisterForm auth={auth} inviteRequired={inviteRequired} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function LoginForm({ auth }: { auth: Auth }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  return (
    <form
      className="flex flex-col gap-3 py-2"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await auth.signIn(email, password);
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

function RegisterForm({ auth, inviteRequired }: { auth: Auth; inviteRequired: boolean }) {
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
