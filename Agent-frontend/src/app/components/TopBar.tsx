import { useState } from "react";
import { Settings2, Cpu } from "lucide-react";
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
import { AuthDialog } from "./AuthDialog";
import type { useSettings } from "../hooks/useSettings";
import type { useAuth } from "../hooks/useAuth";

type Settings = ReturnType<typeof useSettings>;
type Auth = ReturnType<typeof useAuth>;

export function TopBar({ settings, auth }: { settings: Settings; auth: Auth }) {
  const [open, setOpen] = useState(false);
  // 草稿态：仅在保存时写回 settings，取消则丢弃。
  const [model, setModel] = useState(settings.model);
  const [system, setSystem] = useState(settings.systemPrompt);
  const [stream, setStream] = useState(settings.streamEnabled);
  const [useRag, setUseRag] = useState(settings.useRag);
  const [baseUrl, setBaseUrl] = useState(settings.providerConfig?.base_url ?? "");
  const [apiKey, setApiKey] = useState(settings.providerConfig?.api_key ?? "");

  const displayModel = settings.model || settings.serverConfig?.default_model || "默认模型";

  const sync = () => {
    setModel(settings.model);
    setSystem(settings.systemPrompt);
    setStream(settings.streamEnabled);
    setUseRag(settings.useRag);
    setBaseUrl(settings.providerConfig?.base_url ?? "");
    setApiKey(settings.providerConfig?.api_key ?? "");
  };

  const save = () => {
    settings.setModel(model);
    settings.setSystemPrompt(system);
    settings.setStreamEnabled(stream);
    settings.setUseRag(useRag);
    // 输入框默认空：填了就透传，留空则后端按 client_xxx or env 链回落到 .env 配置。
    settings.setProviderConfig(
      baseUrl.trim() || apiKey.trim() ? { base_url: baseUrl, api_key: apiKey } : null,
    );
    setOpen(false);
  };

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

      <div className="ml-auto hidden items-center md:flex">
        <div className="flex items-center gap-1.5 rounded-full border border-border bg-card/60 px-3 py-1 font-mono text-[11px] text-muted-foreground">
          <Cpu className="size-3.5 text-primary" />
          <span className="text-foreground/85">{displayModel}</span>
        </div>
      </div>

      <div className="flex items-center gap-2 max-md:ml-auto md:ml-3">
        <AuthDialog auth={auth} />
        <Dialog
          open={open}
          onOpenChange={(o) => {
            if (o) sync();
            setOpen(o);
          }}
        >
          <DialogTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 border-border bg-card/60 text-[12px]"
            >
              <Settings2 className="size-3.5" />
              配置
            </Button>
          </DialogTrigger>
        <DialogContent className="bg-card sm:max-w-md">
          <DialogHeader>
            <DialogTitle style={{ fontFamily: "var(--font-display)" }}>智能体配置</DialogTitle>
            <DialogDescription className="font-mono text-[11px]">
              模型、系统提示词与运行选项
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-1">
            <Field label="Model（留空用服务端默认）">
              <Input
                value={model}
                placeholder={settings.serverConfig?.default_model ?? "默认模型"}
                onChange={(e) => setModel(e.target.value)}
                className="bg-input-background font-mono text-[12px]"
              />
            </Field>
            {/* API Key / Base URL 无条件常显，默认空。env 配了用 env，留空则用这里填的值，
                都没有时后端抛 CONFIG_ERROR 提醒。是否采用前端值由后端降级链决定，前端不门控。 */}
            <div className="grid grid-cols-2 gap-3">
              <Field label="API Key（留空用服务端 .env）">
                <Input
                  type="password"
                  value={apiKey}
                  placeholder="sk-..."
                  onChange={(e) => setApiKey(e.target.value)}
                  className="bg-input-background font-mono text-[12px]"
                />
              </Field>
              <Field label="Provider Base URL（留空用服务端 .env）">
                <Input
                  value={baseUrl}
                  placeholder="https://.../v1"
                  onChange={(e) => setBaseUrl(e.target.value)}
                  className="bg-input-background font-mono text-[12px]"
                />
              </Field>
            </div>
            <Field label="System Prompt">
              <Textarea
                rows={3}
                value={system}
                onChange={(e) => setSystem(e.target.value)}
                className="resize-none bg-input-background text-[12px]"
              />
            </Field>
            <div className="flex items-center justify-between rounded-lg border border-border bg-input-background px-3 py-2">
              <span className="text-[12px] text-foreground">流式输出</span>
              <Switch checked={stream} onCheckedChange={setStream} />
            </div>
            <div className="flex items-center justify-between rounded-lg border border-border bg-input-background px-3 py-2">
              <span className="text-[12px] text-foreground">知识库检索 (RAG)</span>
              <Switch checked={useRag} onCheckedChange={setUseRag} />
            </div>
            {settings.configError && (
              <p className="font-mono text-[11px] text-destructive">{settings.configError}</p>
            )}
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
              onClick={save}
            >
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      </div>
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
