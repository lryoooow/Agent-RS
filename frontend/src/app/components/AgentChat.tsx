import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { motion } from "motion/react";
import {
  Bot,
  User,
  Send,
  Upload,
  Sparkles,
  Check,
  Loader2,
  Terminal,
  ChevronLeft,
  AlertTriangle,
} from "lucide-react";
import { ScrollArea } from "./ui/scroll-area";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Badge } from "./ui/badge";
import { Logo } from "./Logo";
import { useImageryUpload, type ImageryMeta } from "../hooks/useImageryUpload";
import type { ChatTurn, GeospatialResult } from "../types";

const SUGGESTIONS = [
  "对当前影像计算 NDVI 评估植被长势",
  "用 MNDWI 提取影像中的水体范围",
  "检测影像中的船舶、车辆等目标",
  "对影像做地物语义分类",
];

// Agent-status → tool card. The backend streams agent_status events; we surface
// the latest as a single live tool card under the assistant turn.
function ToolCallCard({ label, done }: { label: string; done: boolean }) {
  return (
    <div className="mt-2 rounded-lg border border-border bg-background/50 p-2.5">
      <div className="flex items-center gap-2">
        <Terminal className="size-3.5 text-primary" />
        <span className="font-mono text-[12px] text-foreground">agent</span>
        <Badge
          variant="outline"
          className="ml-auto border-primary/25 bg-primary/10 px-1.5 py-0 font-mono text-[10px] font-normal text-primary"
        >
          两级规划
        </Badge>
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-[12px] text-muted-foreground">
        {done ? (
          <Check className="size-3.5 text-primary" />
        ) : (
          <Loader2 className="size-3.5 animate-spin text-primary" />
        )}
        <span>{label}</span>
      </div>
    </div>
  );
}

function GeoResultBadge({ result }: { result: GeospatialResult }) {
  const text =
    result.type === "detection"
      ? `目标检测 · ${result.detection_count} 个目标`
      : result.type === "segmentation"
        ? `地物分类 · ${result.classes.length} 类`
        : result.type === "ndvi"
          ? `NDVI · 均值 ${result.stats.mean.toFixed(2)}`
          : result.type === "spectral_index"
            ? `${result.index_type.toUpperCase()} · 均值 ${result.stats.mean.toFixed(2)}`
            : result.type === "composite"
              ? "波段合成图层"
              : "原图已加载";
  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg border border-primary/25 bg-primary/5 p-2 text-[12px] text-foreground">
      <Sparkles className="size-3.5 text-primary" />
      <span>{text}</span>
      <span className="ml-auto font-mono text-[10px] text-muted-foreground">已叠加到地图</span>
    </div>
  );
}

export function AgentChat({
  turns,
  loading,
  activeStream,
  endpoint,
  hasImagery,
  onSend,
  onImageryUploaded,
  onBack,
}: {
  turns: ChatTurn[];
  loading: boolean;
  activeStream: boolean;
  endpoint: string;
  hasImagery: boolean;
  onSend: (text: string) => void;
  onImageryUploaded: (msg: string, result: GeospatialResult) => void;
  onBack: () => void;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const isComposingRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imagery = useImageryUpload(endpoint);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const submit = () => {
    const v = text.trim();
    if (!v || loading) return;
    setText("");
    onSend(v);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (isComposingRef.current || e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  async function handleFileSelect() {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;
    const meta = await imagery.upload(file);
    if (meta) {
      onImageryUploaded(
        `已上传影像 ${meta.filename} · ${meta.band_count} 波段 · ${meta.width}×${meta.height}px`,
        buildPreviewResult(meta),
      );
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const lastAssistantId = [...turns].reverse().find((t) => t.role === "assistant")?.id;

  return (
    <motion.div
      initial={{ opacity: 0, x: -28, scale: 0.985 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: -28, scale: 0.985 }}
      transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
      className="absolute left-4 top-[108px] bottom-4 z-20 flex w-[440px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-border bg-sidebar/85 shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-border px-3 py-2.5">
        <button
          onClick={onBack}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
          title="返回主页查看历史"
        >
          <ChevronLeft className="size-4" />
        </button>
        <Logo size={28} rounded="rounded-lg" />
        <div className="leading-tight">
          <div className="text-[13px] text-foreground" style={{ fontFamily: "var(--font-display)" }}>
            RS Agent
          </div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            两级规划 · 三域子智能体
          </div>
        </div>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-primary">
          <span className="size-1.5 rounded-full bg-primary" />
          online
        </span>
      </div>

      {/* messages */}
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-4 p-3.5">
          {turns.map((t) =>
            t.role === "system" ? (
              <div
                key={t.id}
                className="mx-auto max-w-full rounded-2xl border border-border bg-card/60 px-3 py-1.5 text-center"
              >
                <span className="font-mono text-[10px] text-muted-foreground">{t.content}</span>
                {t.geospatialResult && <GeoResultBadge result={t.geospatialResult} />}
              </div>
            ) : (
              <div key={t.id} className={`flex gap-2.5 ${t.role === "user" ? "flex-row-reverse" : ""}`}>
                <div
                  className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg ${
                    t.role === "user" ? "bg-secondary text-secondary-foreground" : "bg-primary/12 text-primary"
                  }`}
                >
                  {t.role === "user" ? <User className="size-4" /> : <Bot className="size-4" />}
                </div>
                <div className={`max-w-[85%] ${t.role === "user" ? "items-end" : ""}`}>
                  {t.error ? (
                    <div className="flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                      <span className="whitespace-pre-wrap break-words">{t.content || "请求失败"}</span>
                    </div>
                  ) : (
                    <div
                      className={`whitespace-pre-wrap break-words rounded-xl px-3 py-2 text-[13px] leading-relaxed ${
                        t.role === "user"
                          ? "bg-secondary text-secondary-foreground"
                          : "border border-border bg-card text-card-foreground"
                      }`}
                    >
                      {t.content}
                      {t.role === "assistant" &&
                        !t.content &&
                        activeStream &&
                        t.id === lastAssistantId && (
                          <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-primary align-middle" />
                        )}
                    </div>
                  )}
                  {t.role === "assistant" && t.agentLabel && (
                    <ToolCallCard
                      label={t.agentLabel}
                      done={t.analysisStatus === "complete" || Boolean(t.content)}
                    />
                  )}
                  {t.geospatialResult && <GeoResultBadge result={t.geospatialResult} />}
                </div>
              </div>
            ),
          )}
          <div ref={endRef} />
        </div>
      </ScrollArea>

      {/* suggestions */}
      {hasImagery && (
        <div className="flex flex-wrap gap-1.5 border-t border-border px-3.5 pt-3">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              disabled={loading}
              onClick={() => onSend(s)}
              className="flex items-center gap-1 rounded-full border border-border bg-card px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-40"
            >
              <Sparkles className="size-3" />
              {s}
            </button>
          ))}
        </div>
      )}

      {/* input */}
      <div className="border-t border-border p-3">
        <div className="rounded-xl border border-border bg-input-background focus-within:border-primary/50">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            placeholder={hasImagery ? "用自然语言描述分析任务…" : "可直接对话，或先上传影像再做遥感分析"}
            className="resize-none border-0 bg-transparent px-3 py-2.5 text-[13px] shadow-none focus-visible:ring-0"
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            onKeyDown={onKeyDown}
          />
          <div className="flex items-center gap-2 px-2 pb-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".tif,.tiff"
              className="hidden"
              onChange={handleFileSelect}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={imagery.uploading}
              className="h-7 gap-1.5 border-border bg-card px-2.5 text-[12px]"
            >
              {imagery.uploading ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Upload className="size-3.5" />
              )}
              {hasImagery ? "替换影像" : "上传影像"}
            </Button>
            <span className="font-mono text-[10px] text-muted-foreground">GeoTIFF</span>
            <Button
              size="sm"
              onClick={submit}
              disabled={loading}
              className="ml-auto h-7 gap-1.5 bg-primary px-3 text-[12px] text-primary-foreground hover:bg-primary/90"
            >
              {loading ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
              发送
            </Button>
          </div>
        </div>
        {imagery.error && <p className="mt-1.5 px-1 text-[11px] text-destructive">{imagery.error}</p>}
      </div>
    </motion.div>
  );
}

function buildPreviewResult(meta: ImageryMeta): GeospatialResult {
  return {
    type: "preview",
    imagery_id: meta.imagery_id,
    result_url: meta.preview_url ?? `/api/imagery/${meta.imagery_id}/results/preview.png`,
    bounds: normalizeBounds(meta.bounds),
  };
}

function normalizeBounds(bounds: number[] | null): [number, number, number, number] | null {
  if (!Array.isArray(bounds) || bounds.length !== 4) return null;
  const [west, south, east, north] = bounds;
  if (![west, south, east, north].every(Number.isFinite)) return null;
  return [west, south, east, north];
}
