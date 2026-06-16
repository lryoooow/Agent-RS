import { useEffect, useRef, useState } from "react";
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
  AlertTriangle,
  ChevronLeft,
} from "lucide-react";
import { ScrollArea } from "./ui/scroll-area";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Logo } from "./Logo";
import { SUGGESTIONS } from "../data/rs";
import type { ChatTurn } from "../types";
import { toolBubbleForTurn, type ToolBubble } from "../lib/agent-status";
import { GeospatialSummary } from "./GeospatialSummary";

const ANALYSIS_FALLBACK: Record<string, string> = {
  analyzing: "正在解析问题...",
  preparing: "正在整理内容...",
  answering: "正在组织回复...",
  complete: "思考完成",
};

function ToolBubbleCard({ bubble }: { bubble: ToolBubble }) {
  const isError = bubble.status === "error";
  return (
    <div
      className={`mt-2 rounded-lg border p-2.5 ${
        isError ? "border-destructive/40 bg-destructive/5" : "border-border bg-background/50"
      }`}
    >
      <div className="flex items-center gap-2">
        {isError ? (
          <AlertTriangle className="size-3.5 text-destructive" />
        ) : (
          <Terminal className="size-3.5 text-primary" />
        )}
        <span className="font-mono text-[12px] text-foreground">agent</span>
        <span className="ml-auto flex items-center gap-1.5 text-[12px] text-muted-foreground">
          {bubble.status === "running" ? (
            <Loader2 className="size-3.5 animate-spin text-primary" />
          ) : isError ? (
            <AlertTriangle className="size-3.5 text-destructive" />
          ) : (
            <Check className="size-3.5 text-primary" />
          )}
          <span className={isError ? "text-destructive" : ""}>{bubble.label}</span>
        </span>
      </div>
    </div>
  );
}

function AssistantTurn({ turn, streaming }: { turn: ChatTurn; streaming: boolean }) {
  const bubble = toolBubbleForTurn(turn);
  const showAnalysis = turn.analysisStatus != null && !turn.content && turn.analysisStatus !== "complete";
  const analysisText = turn.analysisLabel ?? ANALYSIS_FALLBACK[turn.analysisStatus ?? ""] ?? "";

  return (
    <div className="flex gap-2.5">
      <div
        className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg ${
          turn.error ? "bg-destructive/12 text-destructive" : "bg-primary/12 text-primary"
        }`}
      >
        <Bot className="size-4" />
      </div>
      <div className="max-w-[85%]">
        {showAnalysis && (
          <div className="rounded-xl border border-border bg-card px-3 py-2 text-[12px] italic text-muted-foreground">
            {analysisText}
          </div>
        )}
        {turn.content && (
          <div
            className={`rounded-xl px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap break-words ${
              turn.error
                ? "border border-destructive/30 bg-destructive/5 text-foreground"
                : "border border-border bg-card text-card-foreground"
            }`}
          >
            {turn.content}
            {streaming && (
              <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-primary align-middle" />
            )}
          </div>
        )}
        {bubble && <ToolBubbleCard bubble={bubble} />}
        {turn.geospatialResult && <GeospatialSummary result={turn.geospatialResult} />}
      </div>
    </div>
  );
}

export function AgentChat({
  turns,
  loading,
  activeStream,
  hasImagery,
  uploading,
  onSend,
  onUpload,
  onBack,
}: {
  turns: ChatTurn[];
  loading: boolean;
  activeStream: boolean;
  hasImagery: boolean;
  uploading: boolean;
  onSend: (text: string) => void;
  onUpload: () => void;
  onBack: () => void;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const lastId = turns.length > 0 ? turns[turns.length - 1].id : null;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, lastId]);

  const submit = () => {
    const v = text.trim();
    if (!v || loading) return;
    setText("");
    onSend(v);
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -28, scale: 0.985 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: -28, scale: 0.985 }}
      transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
      className="absolute left-4 top-[108px] bottom-4 z-20 flex w-[360px] flex-col overflow-hidden rounded-2xl border border-border bg-sidebar/85 shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-border px-3 py-2.5">
        <button
          onClick={onBack}
          className="flex h-8 shrink-0 items-center gap-1 rounded-lg border border-border bg-card px-2 text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary"
          title="返回主页查看历史"
        >
          <ChevronLeft className="size-4" />
          <span className="text-[11px]">返回</span>
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
        <div className="flex flex-col gap-4 p-3.5">          {turns.map((turn) => {
            if (turn.role === "system") {
              return (
                <div
                  key={turn.id}
                  className="mx-auto rounded-full border border-border bg-card/60 px-3 py-1 text-center font-mono text-[10px] text-muted-foreground"
                >
                  {turn.content}
                </div>
              );
            }
            if (turn.role === "user") {
              return (
                <div key={turn.id} className="flex flex-row-reverse gap-2.5">
                  <div className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-secondary text-secondary-foreground">
                    <User className="size-4" />
                  </div>
                  <div className="max-w-[85%]">
                    <div className="rounded-xl bg-secondary px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap break-words text-secondary-foreground">
                      {turn.content}
                    </div>
                  </div>
                </div>
              );
            }
            return (
              <AssistantTurn
                key={turn.id}
                turn={turn}
                streaming={activeStream && turn.id === lastId}
              />
            );
          })}
          <div ref={endRef} />
        </div>
      </ScrollArea>

      {/* suggestions */}
      {hasImagery && (
        <div className="flex flex-wrap gap-1.5 border-t border-border px-3.5 pt-3">
          {SUGGESTIONS.map((s) => (
            <button
              key={s.label}
              disabled={loading}
              onClick={() => onSend(s.label)}
              className="flex items-center gap-1 rounded-full border border-border bg-card px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-40"
            >
              <Sparkles className="size-3" />
              {s.label}
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
            placeholder={hasImagery ? "用自然语言描述分析任务…" : "可直接提问，或上传影像后做遥感分析"}
            className="resize-none border-0 bg-transparent px-3 py-2.5 text-[13px] shadow-none focus-visible:ring-0"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="flex items-center gap-2 px-2 pb-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onUpload}
              disabled={uploading}
              className="h-7 gap-1.5 border-border bg-card px-2.5 text-[12px]"
            >
              {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
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
      </div>
    </motion.div>
  );
}
