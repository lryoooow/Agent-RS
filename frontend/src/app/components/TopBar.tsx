import { useEffect, useState } from "react";
import { Settings2, Cpu, KeyRound, ShieldCheck, Info } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
  DialogFooter,
  DialogClose,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Switch } from "./ui/switch";
import { Logo } from "./Logo";

export interface TopBarSettings {
  endpoint: string;
  systemPrompt: string;
  streamEnabled: boolean;
  useRag: boolean;
  modelLabel: string;
  webSearchEnabled: boolean;
  // 模型直连兜底配置
  baseUrl: string;
  apiKey: string;
  model: string;
  // 后端是否已配置 API Key（true→env 优先，前端直连不生效）
  apiKeyConfigured: boolean;
  // 后端是否允许客户端下发 provider_config
  allowClientProviderConfig: boolean;
}

export type TopBarSaved = Pick<
  TopBarSettings,
  "endpoint" | "systemPrompt" | "streamEnabled" | "useRag" | "baseUrl" | "apiKey" | "model"
>;

export function TopBar({
  settings,
  onSave,
  rightSlot,
}: {
  settings: TopBarSettings;
  onSave: (next: TopBarSaved) => void;
  rightSlot?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [endpoint, setEndpoint] = useState(settings.endpoint);
  const [systemPrompt, setSystemPrompt] = useState(settings.systemPrompt);
  const [streamEnabled, setStreamEnabled] = useState(settings.streamEnabled);
  const [useRag, setUseRag] = useState(settings.useRag);
  const [baseUrl, setBaseUrl] = useState(settings.baseUrl);
  const [apiKey, setApiKey] = useState(settings.apiKey);
  const [model, setModel] = useState(settings.model);

  // re-sync draft when dialog opens
  useEffect(() => {
    if (open) {
      setEndpoint(settings.endpoint);
      setSystemPrompt(settings.systemPrompt);
      setStreamEnabled(settings.streamEnabled);
      setUseRag(settings.useRag);
      setBaseUrl(settings.baseUrl);
      setApiKey(settings.apiKey);
      setModel(settings.model);
    }
  }, [open, settings]);

  // 兜底是否真正生效：后端未配置 key 且允许客户端配置。
  const fallbackActive = !settings.apiKeyConfigured && settings.allowClientProviderConfig;

  return (
    <header className="absolute inset-x-0 top-0 z-40 flex h-14 items-center gap-3 border-b border-border bg-background/70 px-4 backdrop-blur-xl">
      <div className="flex items-center gap-2.5">
        <Logo size={32} rounded="rounded-lg" />
        <div className="leading-tight">
          <div
            className="flex items-center gap-2 text-[15px] tracking-tight text-foreground"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Agent-RS
            <span className="rounded-md border border-primary/25 bg-primary/10 px-1.5 py-px font-mono text-[10px] font-normal text-primary">
              workbench
            </span>
          </div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            遥感大模型应用智能体
          </div>
        </div>
      </div>

      <div className="ml-auto hidden items-center gap-2 md:flex">
        <div className="flex items-center gap-1.5 rounded-full border border-border bg-card/60 px-3 py-1 font-mono text-[11px] text-muted-foreground">
          <Cpu className="size-3.5 text-primary" />
          <span className="text-foreground/85">{settings.modelLabel || "未配置模型"}</span>
        </div>
        {rightSlot}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto h-8 gap-1.5 border-border bg-card/60 text-[12px] md:ml-1"
          >
            <Settings2 className="size-3.5" />
            配置
          </Button>
        </DialogTrigger>
        <DialogContent className="max-h-[85vh] overflow-y-auto bg-card sm:max-w-md">
          <DialogHeader>
            <DialogTitle style={{ fontFamily: "var(--font-display)" }}>智能体配置</DialogTitle>
            <DialogDescription className="font-mono text-[11px]">
              后端接口、对话行为与模型直连兜底
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-1">
            <Field label="后端接口 (Chat Endpoint)">
              <Input
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
                placeholder="/api/chat"
                className="bg-input-background font-mono text-[12px]"
              />
            </Field>
            <Field label="System Prompt (附加指令)">
              <Textarea
                rows={3}
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="可选：附加到当前对话的额外系统指令"
                className="resize-none bg-input-background text-[12px]"
              />
            </Field>
            <div className="flex items-center justify-between rounded-lg border border-border bg-input-background px-3 py-2">
              <Label className="font-mono text-[11px] text-muted-foreground">流式回复</Label>
              <Switch checked={streamEnabled} onCheckedChange={setStreamEnabled} />
            </div>
            <div className="flex items-center justify-between rounded-lg border border-border bg-input-background px-3 py-2">
              <Label className="font-mono text-[11px] text-muted-foreground">
                知识库检索 (RAG)
              </Label>
              <Switch checked={useRag} onCheckedChange={setUseRag} />
            </div>

            <ProviderSection
              apiKeyConfigured={settings.apiKeyConfigured}
              allowClient={settings.allowClientProviderConfig}
              fallbackActive={fallbackActive}
              baseUrl={baseUrl}
              apiKey={apiKey}
              model={model}
              onBaseUrl={setBaseUrl}
              onApiKey={setApiKey}
              onModel={setModel}
            />
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost" size="sm">
                取消
              </Button>
            </DialogClose>
            <Button
              size="sm"
              className="bg-primary text-primary-foreground hover:bg-primary/90"
              onClick={() => {
                onSave({ endpoint, systemPrompt, streamEnabled, useRag, baseUrl, apiKey, model });
                setOpen(false);
              }}
            >
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </header>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

// 模型直连兜底配置区。三种状态：
// 1) 后端已配 key → env 优先，前端配置仅作备用、当前不生效（绿色提示）。
// 2) 后端未配 key 且允许客户端配置 → 兜底已启用，前端填的会真正下发（蓝色提示 + 必填校验）。
// 3) 后端未配 key 但不允许客户端配置 → 既没 env 也不收前端，无法对话（黄色警告）。
function ProviderSection({
  apiKeyConfigured,
  allowClient,
  fallbackActive,
  baseUrl,
  apiKey,
  model,
  onBaseUrl,
  onApiKey,
  onModel,
}: {
  apiKeyConfigured: boolean;
  allowClient: boolean;
  fallbackActive: boolean;
  baseUrl: string;
  apiKey: string;
  model: string;
  onBaseUrl: (v: string) => void;
  onApiKey: (v: string) => void;
  onModel: (v: string) => void;
}) {
  return (
    <div className="mt-1 flex flex-col gap-2.5 rounded-lg border border-border bg-input-background/60 p-3">
      <div className="flex items-center gap-1.5">
        <KeyRound className="size-3.5 text-primary" />
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          模型直连 (兜底)
        </span>
      </div>

      {apiKeyConfigured ? (
        <Banner tone="ok" icon={<ShieldCheck className="size-3.5" />}>
          后端 .env 已配置 API Key，<b>服务端配置优先</b>。下方仅作备用，当前不会下发。
        </Banner>
      ) : allowClient ? (
        <Banner tone="info" icon={<Info className="size-3.5" />}>
          后端未配置 API Key，将使用下方<b>前端直连配置</b>对话。请填写 Base URL、API Key 与模型。
        </Banner>
      ) : (
        <Banner tone="warn" icon={<Info className="size-3.5" />}>
          后端未配置 API Key，且未允许客户端配置。请在后端 .env 设置
          <code className="mx-1 font-mono">ALLOW_CLIENT_PROVIDER_CONFIG=true</code>
          后此处才生效。
        </Banner>
      )}

      <Field label="Base URL">
        <Input
          value={baseUrl}
          onChange={(e) => onBaseUrl(e.target.value)}
          placeholder="https://api.openai.com/v1"
          disabled={!fallbackActive}
          className="bg-input-background font-mono text-[12px] disabled:opacity-50"
        />
      </Field>
      <Field label="API Key">
        <Input
          type="password"
          value={apiKey}
          onChange={(e) => onApiKey(e.target.value)}
          placeholder="sk-..."
          autoComplete="off"
          disabled={!fallbackActive}
          className="bg-input-background font-mono text-[12px] disabled:opacity-50"
        />
      </Field>
      <Field label="模型 (Model)">
        <Input
          value={model}
          onChange={(e) => onModel(e.target.value)}
          placeholder="gpt-4.1-mini"
          disabled={!fallbackActive}
          className="bg-input-background font-mono text-[12px] disabled:opacity-50"
        />
      </Field>
    </div>
  );
}

function Banner({
  tone,
  icon,
  children,
}: {
  tone: "ok" | "info" | "warn";
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const cls =
    tone === "ok"
      ? "border-primary/25 bg-primary/5 text-foreground/85"
      : tone === "info"
        ? "border-sky-500/30 bg-sky-500/10 text-foreground/85"
        : "border-amber-500/30 bg-amber-500/10 text-foreground/85";
  return (
    <div className={`flex items-start gap-2 rounded-md border px-2.5 py-2 text-[11.5px] leading-relaxed ${cls}`}>
      <span className="mt-0.5 shrink-0 text-primary">{icon}</span>
      <span>{children}</span>
    </div>
  );
}
