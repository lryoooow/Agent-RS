import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
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
import type { ImageryMeta } from "../hooks/useImageryUpload";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Logo } from "./Logo";
import { SUGGESTIONS } from "../data/rs";
import type { ChatTurn, SceneCardInfo, ThinkingStrength } from "../types";
import { toolBubbleForTurn, type ToolBubble } from "../lib/agent-status";
import { GeospatialSummary } from "./GeospatialSummary";
import { Markdown } from "./Markdown";
import { fadeInUp } from "../lib/motion";
import { THINKING_SUMMARY_LABELS } from "../lib/thinking-summary";

import { useChatPanelSize } from "../hooks/useChatPanelSize";

const ANALYSIS_FALLBACK: Record<string, string> = {
  analyzing: "正在思考",
  preparing: "正在核对结果",
  answering: "正在回复",
  complete: "",
};

function ToolBubbleCard({ bubble }: { bubble: ToolBubble }) {
  const isError = bubble.status === "error";
  return (
    <div
      data-testid="tool-bubble"
      className={`mt-2 w-fit max-w-full rounded-lg border p-2.5 ${
        isError ? "border-destructive/40 bg-destructive/5" : "border-border bg-background/50"
      }`}
    >
      <div className="flex items-start gap-2">
        <span className="inline-flex shrink-0 items-center gap-2">
          {isError ? (
            <AlertTriangle className="size-3.5 shrink-0 text-destructive" />
          ) : (
            <Terminal className="size-3.5 shrink-0 text-primary" />
          )}
          <span className="font-mono text-[12px] text-foreground">agent</span>
        </span>
        <span className="flex min-w-0 items-start gap-1.5 text-[12px] text-muted-foreground">
          {bubble.status === "running" ? (
            <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin text-primary" />
          ) : isError ? (
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-destructive" />
          ) : (
            <Check className="mt-0.5 size-3.5 shrink-0 text-primary" />
          )}
          <span className={`min-w-0 break-words [overflow-wrap:anywhere] ${isError ? "text-destructive" : ""}`}>{bubble.label}</span>
        </span>
      </div>
    </div>
  );
}

function AssistantTurn({
  turn,
  streaming,
  onGenerateReport,
  reportPending,
  onScenePreview,
  onSceneImport,
}: {
  turn: ChatTurn;
  streaming: boolean;
  onGenerateReport?: (imageryId: string) => void;
  reportPending?: boolean;
  onScenePreview?: (scene: SceneCardInfo) => void;
  onSceneImport?: (sceneKey: string) => Promise<string | null>;
}) {
  const bubble = toolBubbleForTurn(turn);
  const showAnalysis = turn.analysisStatus != null && !turn.content && turn.analysisStatus !== "complete";
  const analysisText = turn.analysisLabel ?? ANALYSIS_FALLBACK[turn.analysisStatus ?? ""] ?? "";
  const summaries = turn.thinkingSummary ?? [];
  const currentSummary =
    [...summaries].reverse().find((item) => item.status === "active") ??
    summaries[summaries.length - 1];
  const rollingText = currentSummary
    ? THINKING_SUMMARY_LABELS[currentSummary.stage]
    : analysisText;
  // 阶段摘要只在回合仍进行时滚动展示；回合完成即彻底收起，不留下标题、图标或空容器。
  const showRollingSummary = Boolean(rollingText) && (streaming || showAnalysis);

  return (
    <div className="flex gap-2.5">
      <div
        className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg ${
          turn.error ? "bg-destructive/12 text-destructive" : "bg-primary/12 text-primary"
        }`}
      >
        <Bot className="size-4" />
      </div>
      {/* Keep room for result cards; individual text/status bubbles fit their content. */}
      <div className="min-w-0 flex-1 max-w-full">
        {showRollingSummary && (
          <div className="mb-1.5 h-5 overflow-hidden font-mono text-[12px] leading-5" aria-live="polite">
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={rollingText}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.22, ease: "easeOut" }}
                className="thinking-summary-glow inline-block"
              >
                {rollingText}
              </motion.span>
            </AnimatePresence>
          </div>
        )}
        {turn.content && (
          <div
            data-testid="assistant-message-bubble"
            className={`w-fit max-w-full rounded-xl px-3 py-2 text-[13px] leading-relaxed break-words [overflow-wrap:anywhere] has-[table]:w-full has-[pre]:w-full ${
              turn.error
                ? "border border-destructive/30 bg-destructive/5 text-foreground whitespace-pre-wrap"
                : "border border-border bg-card text-card-foreground"
            }`}
          >
            {turn.error ? (
              turn.content
            ) : (
              <Markdown>{turn.content}</Markdown>
            )}
            {streaming && (
              <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-primary align-middle" />
            )}
          </div>
        )}
        {bubble && <ToolBubbleCard bubble={bubble} />}
        {turn.geospatialResult && (
          <GeospatialSummary
            result={turn.geospatialResult}
            onGenerateReport={onGenerateReport}
            reportPending={reportPending}
            onScenePreview={onScenePreview}
            onSceneImport={onSceneImport}
          />
        )}
        {turn.usage && !streaming && (turn.usage.total_tokens || turn.usage.input_tokens || turn.usage.output_tokens) && (
          <div className="mt-1 font-mono text-[10px] text-muted-foreground/70">
            🧮 {turn.usage.total_tokens ?? ((turn.usage.input_tokens ?? 0) + (turn.usage.output_tokens ?? 0))} tokens
            {turn.usage.input_tokens != null && turn.usage.output_tokens != null
              ? `（入 ${turn.usage.input_tokens} / 出 ${turn.usage.output_tokens}）`
              : ""}
          </div>
        )}
      </div>
    </div>
  );
}

export function AgentChat({
  turns,
  loading,
  activeStream,
  hasImagery,
  imageryOptions = [], activeImageryId, onSelectImagery, imageryNotice, onLocateImagery,
  uploading,
  onSend,
  onUpload,
  onBack,
  onGenerateReport,
  reportPending,
  thinkingStrength,
  onThinkingChange,
  onScenePreview,
  onSceneImport,
}: {
  turns: ChatTurn[];
  loading: boolean;
  activeStream: boolean;
  hasImagery: boolean;
  imageryOptions?: ImageryMeta[];
  activeImageryId?: string | null;
  onSelectImagery?: (id: string) => void;
  imageryNotice?: string | null;
  onLocateImagery?: () => void;
  uploading: boolean;
  onSend: (text: string) => void;
  onUpload: () => void;
  onBack: () => void;
  onGenerateReport?: (imageryId: string) => void;
  reportPending?: boolean;
  thinkingStrength: ThinkingStrength;
  onThinkingChange: (s: ThinkingStrength) => void;
  onScenePreview?: (scene: SceneCardInfo) => void;
  onSceneImport?: (sceneKey: string) => Promise<string | null>;
}) {
  const panel = useChatPanelSize();
  const [text, setText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const followBottom = useRef(true);
  const reduce = useReducedMotion();
  const lastId = turns.length > 0 ? turns[turns.length - 1].id : null;

  useEffect(() => {
    const viewport = scrollRef.current;
    const content = contentRef.current;
    if (!viewport || !content) return;
    const follow = () => { if (followBottom.current) viewport.scrollTop = viewport.scrollHeight; };
    const observer = new ResizeObserver(follow);
    observer.observe(content);
    observer.observe(viewport);
    follow();
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (followBottom.current && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [turns]);
  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(Math.max(48, input.scrollHeight), Math.max(56, Math.min(120, panel.size.height * 0.2)))}px`;
  }, [text, panel.size.width, panel.size.height]);

  const submit = () => {
    const v = text.trim();
    if (!v || loading) return;
    followBottom.current = true;
    setText("");
    onSend(v);
  };

  return (
    <motion.div
      data-testid="chat-panel"
      style={{ width: panel.size.width, height: panel.size.height }}
      initial={{ opacity: 0, x: -28, scale: 0.985 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: -28, scale: 0.985 }}
      transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
      className="absolute left-4 top-[108px] z-20 flex max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-border bg-sidebar/85 shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      <button type="button" aria-label="调整对话框宽度" title="拖动调整宽度，方向键微调" {...panel.handle("width")}
        className="absolute right-0 top-12 bottom-5 z-30 w-2 touch-none cursor-ew-resize hover:bg-primary/20 focus-visible:bg-primary/30" />
      <button type="button" aria-label="调整对话框高度" title="拖动调整高度，方向键微调" {...panel.handle("height")}
        className="absolute bottom-0 left-5 right-5 z-30 h-2 touch-none cursor-ns-resize hover:bg-primary/20 focus-visible:bg-primary/30" />
      <button type="button" aria-label="调整对话框宽高" title="拖动调整宽高；双击恢复默认大小" {...panel.handle("both")} onDoubleClick={panel.reset}
        className="absolute bottom-0 right-0 z-40 flex size-5 touch-none cursor-nwse-resize items-center justify-center rounded-tl bg-card text-primary hover:bg-primary/20 focus-visible:outline-primary">◢</button>
      {/* header */}
      <div className="flex shrink-0 items-center gap-2.5 border-b border-border px-3 py-2.5">
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
            领域专家 · 共享工具编排
          </div>
        </div>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-primary">
          <span className="size-1.5 rounded-full bg-primary" />
          online
        </span>
      </div>

      {onSelectImagery && <div className="shrink-0 min-w-0 border-b border-border px-3 py-1.5 text-[11px]">
        <div className="flex min-w-0 items-center gap-2">
          <label htmlFor="active-imagery" className="shrink-0">当前分析影像</label>
          <select id="active-imagery" aria-label="当前分析影像" className="min-w-0 flex-1 rounded border border-border bg-card p-1"
            value={activeImageryId ?? ""} disabled={loading || uploading} onChange={(e) => onSelectImagery(e.target.value)}>
            <option value="">未选择影像</option>
            {activeImageryId && !imageryOptions.some((m) => m.imagery_id === activeImageryId) && <option value={activeImageryId}>{activeImageryId}（加载中）</option>}
            {imageryOptions.map((m) => <option key={m.imagery_id} value={m.imagery_id}>{m.filename} · {m.imagery_id}</option>)}
          </select>
          <button type="button" className="shrink-0 text-primary disabled:opacity-40" disabled={!hasImagery} onClick={onLocateImagery}>定位</button>
        </div>
        {imageryNotice && <div role="status" className="mt-1 max-h-12 overflow-y-auto break-words text-amber-400">{imageryNotice}</div>}
      </div>}
      {/* Native flex viewport avoids Radix's intrinsic-width table wrapper. */}
      <div ref={scrollRef} data-testid="chat-messages" className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden [overflow-anchor:none]"
        onScroll={() => { const v = scrollRef.current; if (v) followBottom.current = v.scrollHeight - v.scrollTop - v.clientHeight < 64; }}>
        <div ref={contentRef} className="flex min-w-0 flex-col gap-4 p-3.5">
          {turns.map((turn) => {
            let body: React.ReactNode;
            if (turn.role === "system") {
              body = (
                <div className="mx-auto max-w-full break-words [overflow-wrap:anywhere] rounded-lg border border-border bg-card/60 px-3 py-1 text-center font-mono text-[10px] text-muted-foreground">
                  {turn.content}
                </div>
              );
            } else if (turn.role === "user") {
              body = (
                <div className="flex flex-row-reverse gap-2.5">
                  <div className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-secondary text-secondary-foreground">
                    <User className="size-4" />
                  </div>
                  <div className="min-w-0 max-w-full">
                    <div data-testid="user-message-bubble" className="w-fit max-w-full rounded-xl bg-secondary px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-secondary-foreground">
                      {turn.content}
                    </div>
                  </div>
                </div>
              );
            } else {
              body = (
                <AssistantTurn
                  turn={turn}
                  streaming={activeStream && turn.id === lastId}
                  onGenerateReport={onGenerateReport}
                  reportPending={reportPending}
                  onScenePreview={onScenePreview}
                  onSceneImport={onSceneImport}
                />
              );
            }
            return (
              <motion.div
                key={turn.id}
                variants={reduce ? undefined : fadeInUp}
                initial={reduce ? false : "hidden"}
                animate="show"
              >
                {body}
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* suggestions */}
      {hasImagery && panel.size.height >= 560 && (
        <div className="flex shrink-0 flex-wrap gap-1.5 border-t border-border px-3.5 pt-3">
          {SUGGESTIONS.map((s) => (
            <motion.button
              key={s.label}
              whileHover={reduce ? undefined : { scale: 1.04 }}
              whileTap={reduce ? undefined : { scale: 0.96 }}
              disabled={loading}
              onClick={() => { followBottom.current = true; onSend(s.label); }}
              className="flex items-center gap-1 rounded-full border border-border bg-card px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-40"
            >
              <Sparkles className="size-3" />
              {s.label}
            </motion.button>
          ))}
        </div>
      )}

      {/* input */}
      <div className="shrink-0 border-t border-border p-3 pb-5">
        <div className="rounded-xl border border-border bg-input-background focus-within:border-primary/50">
          <Textarea
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            placeholder={hasImagery ? "用自然语言描述分析任务…" : "可直接提问，或上传影像后做遥感分析"}
            className="resize-none border-0 bg-transparent px-3 py-2.5 text-[13px] shadow-none focus-visible:ring-0"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="flex flex-wrap items-center gap-2 px-2 pb-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onUpload}
              disabled={uploading || loading}
              className="h-7 gap-1.5 border-border bg-card px-2.5 text-[12px]"
            >
              {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
              {"上传影像"}
            </Button>
            <span className="font-mono text-[10px] text-muted-foreground">GeoTIFF</span>
            <div className="flex items-center gap-0.5 rounded-md border border-border bg-card p-0.5" title="思考强度（影响速度与精度）">
              {(["low", "medium", "max"] as ThinkingStrength[]).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => onThinkingChange(s)}
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] transition-colors ${
                    thinkingStrength === s
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {s === "low" ? "低" : s === "medium" ? "中" : "高"}
                </button>
              ))}
            </div>
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
