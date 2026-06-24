import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { LogIn, UserPlus, Loader2, ShieldCheck, Sparkles, Layers } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Logo } from "./Logo";
import { fadeInUp, staggerContainer, baseTransition } from "../lib/motion";
import type { useAuth } from "../hooks/useAuth";

type Auth = ReturnType<typeof useAuth>;

// 独立品牌登录页：auth_required 且未登录时由 App 渲染，挡在整个应用前，确认"你是谁/有无权限"再进入。
// 左右分栏：左品牌/价值区（窄屏隐藏），右登录卡。表单逻辑复用 useAuth，与 AuthDialog 一致；
// 有效会话由 useAuth 自动恢复（自动进入），此页仅在未认证时出现。
export function AuthGate({ auth }: { auth: Auth }) {
  const reduce = useReducedMotion();
  return (
    <div className="fixed inset-0 z-[100] flex bg-background">
      {/* 左：品牌 / 价值区（lg 以上显示） */}
      <motion.div
        variants={reduce ? undefined : staggerContainer}
        initial={reduce ? false : "hidden"}
        animate="show"
        className="relative hidden w-[46%] flex-col justify-between overflow-hidden border-r border-border bg-sidebar/40 p-10 lg:flex"
      >
        {/* 背景光晕 */}
        <div className="pointer-events-none absolute -left-24 -top-24 size-72 rounded-full bg-primary/15 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 right-0 size-80 rounded-full bg-chart-2/10 blur-3xl" />

        <motion.div variants={fadeInUp} className="flex items-center gap-3">
          <Logo size={40} rounded="rounded-xl" />
          <div className="text-[18px] tracking-tight text-foreground" style={{ fontFamily: "var(--font-display)" }}>
            Agent-RS
          </div>
        </motion.div>

        <motion.div variants={fadeInUp} className="relative max-w-sm">
          <h1 className="text-[26px] font-semibold leading-tight tracking-tight text-foreground">
            用自然语言完成
            <br />
            专业遥感影像分析
          </h1>
          <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">
            上传卫星或航拍影像，像聊天一样做植被分析、水体提取、地物分类与目标检测，结果直接呈现为可交互的地图图层。
          </p>
        </motion.div>

        <motion.ul variants={fadeInUp} className="relative flex flex-col gap-2.5 text-[12px] text-muted-foreground">
          <Feature icon={<Layers className="size-3.5 text-primary" />}>两级规划 · 三域子智能体编排遥感工具</Feature>
          <Feature icon={<Sparkles className="size-3.5 text-primary" />}>对话 / 影像 / 分析一体化工作台</Feature>
          <Feature icon={<ShieldCheck className="size-3.5 text-primary" />}>邀请码准入 · 数据按账户隔离</Feature>
        </motion.ul>
      </motion.div>

      {/* 右：登录 / 注册卡 */}
      <div className="flex flex-1 items-center justify-center p-6">
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={baseTransition}
          className="w-full max-w-sm"
        >
          {/* 窄屏顶部品牌（左栏隐藏时的兜底） */}
          <div className="mb-6 flex flex-col items-center gap-2 text-center lg:hidden">
            <Logo size={44} rounded="rounded-xl" />
            <div className="text-[17px] tracking-tight text-foreground" style={{ fontFamily: "var(--font-display)" }}>
              Agent-RS
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-card/80 p-6 shadow-xl backdrop-blur-xl">
            <div className="mb-4">
              <div className="text-[16px] font-semibold tracking-tight text-foreground">登录以继续</div>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">遥感大模型应用智能体 · 确认身份后进入</p>
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
                <RegisterForm auth={auth} />
              </TabsContent>
            </Tabs>
          </div>
        </motion.div>
      </div>
    </div>
  );
}

function Feature({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      <span className="grid size-6 shrink-0 place-items-center rounded-md border border-border bg-card">{icon}</span>
      {children}
    </li>
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

function RegisterForm({ auth }: { auth: Auth }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  return (
    <form
      className="flex flex-col gap-3 py-2"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await auth.signUp(email, password, name);
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
