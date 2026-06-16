import { useState } from "react";
import { motion } from "motion/react";
import { Send, Upload, Sparkles } from "lucide-react";
import { ScrollArea } from "./ui/scroll-area";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Logo } from "./Logo";
import { SUGGESTIONS } from "../data/rs";

export function WelcomeScreen({
  onStart,
}: {
  onStart: (text: string) => void;
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
      className="absolute left-4 top-[108px] bottom-4 z-20 flex w-[372px] flex-col overflow-hidden rounded-2xl border border-border bg-sidebar/85 shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      <ScrollArea className="flex-1">
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
                  if (e.key === "Enter" && !e.shiftKey) {
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
                  key={s.label}
                  onClick={() => onStart(s.label)}
                  className="flex items-center gap-1.5 rounded-full border border-border bg-card/60 px-2.5 py-1.5 text-[11.5px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <Sparkles className="size-3 text-primary" />
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </ScrollArea>
    </motion.div>
  );
}
