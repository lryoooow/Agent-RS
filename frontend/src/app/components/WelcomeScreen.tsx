import { useState } from "react";
import { motion } from "motion/react";
import { Send, Upload, Sparkles, MessageSquare, ArrowRight, Clock } from "lucide-react";
import { ScrollArea } from "./ui/scroll-area";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Logo } from "./Logo";
import type { ConversationItem } from "../lib/conversations-api";

const SUGGESTIONS = [
  "对当前影像计算 NDVI 评估植被长势",
  "用 MNDWI 提取影像中的水体范围",
  "检测影像中的船舶、车辆等目标",
  "对影像做地物语义分类",
];

export function WelcomeScreen({
  sessions,
  onStart,
  onOpenSession,
}: {
  sessions: ConversationItem[];
  onStart: (text: string) => void;
  onOpenSession: (id: string) => void;
}) {
  const [text, setText] = useState("");

  const submit = () => {
    const v = text.trim();
    if (!v) return;
    setText("");
    onStart(v);
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -28, scale: 0.985 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: -28, scale: 0.985 }}
      transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
      className="absolute left-4 top-[108px] bottom-4 z-20 flex w-[440px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-border bg-sidebar/85 shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col items-center px-5 pb-5 pt-7">
          {/* brand */}
          <Logo
            size={92}
            rounded="rounded-3xl"
            className="shadow-xl shadow-black/40 ring-1 ring-white/10"
          />
          <h1
            className="mt-5 text-center text-[22px] leading-tight tracking-tight text-foreground"
            style={{ fontFamily: "var(--font-display)" }}
          >
            欢迎使用 Agent-RS
          </h1>
          <p className="mt-2 text-center text-[13px] leading-relaxed text-muted-foreground">
            基于大模型的遥感影像分析智能体。上传一景 GeoTIFF，用自然语言描述任务——
            计算 NDVI、提取水体、检测目标或地物分类，结果即刻叠加到地图。
          </p>

          {/* composer */}
          <div className="mt-6 w-full">
            <div className="rounded-2xl border border-border bg-input-background shadow-lg shadow-black/20 focus-within:border-primary/50">
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={2}
                placeholder="描述你的分析任务，开始一段新对话…"
                className="resize-none border-0 bg-transparent px-3.5 py-3 text-[13px] shadow-none focus-visible:ring-0"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
              <div className="flex items-center gap-2 px-2.5 pb-2.5">
                <span className="flex items-center gap-1.5 rounded-md border border-border bg-card/60 px-2 py-1 font-mono text-[10px] text-muted-foreground">
                  <Upload className="size-3" />
                  GeoTIFF
                </span>
                <Button
                  size="sm"
                  onClick={submit}
                  className="ml-auto h-8 gap-1.5 bg-primary px-3.5 text-[12px] text-primary-foreground hover:bg-primary/90"
                >
                  <Send className="size-3.5" />
                  开始对话
                </Button>
              </div>
            </div>

            {/* suggestions */}
            <div className="mt-3 flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => onStart(s)}
                  className="flex items-center gap-1.5 rounded-full border border-border bg-card/60 px-2.5 py-1.5 text-[11.5px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <Sparkles className="size-3 text-primary" />
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* conversation history */}
          {sessions.length > 0 && (
            <div className="mt-7 w-full">
              <div className="mb-2 flex items-center gap-2 px-1">
                <Clock className="size-3.5 text-muted-foreground" />
                <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  对话历史
                </span>
                <span className="font-mono text-[10px] text-muted-foreground/60">
                  {sessions.length}
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                {sessions.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => onOpenSession(s.id)}
                    className="group flex items-center gap-2.5 rounded-xl border border-border bg-card/60 px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-card"
                  >
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
                      <MessageSquare className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1 leading-tight">
                      <span className="block truncate text-[12.5px] text-foreground">{s.title}</span>
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {formatTime(s.updated_at)} · {s.message_count} 条
                      </span>
                    </span>
                    <ArrowRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
    </motion.div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch {
    return iso;
  }
}
