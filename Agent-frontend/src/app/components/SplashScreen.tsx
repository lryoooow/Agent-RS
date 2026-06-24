import { motion, useReducedMotion } from "motion/react";
import { Loader2 } from "lucide-react";
import { Logo } from "./Logo";
import { fadeIn, baseTransition } from "../lib/motion";

// 首屏过渡页：serverConfig / 会话尚未就绪时显示，避免在未知态下先渲染主应用造成闪屏。
// 整屏品牌底 + Logo + 轻动效 spinner；尊重 prefers-reduced-motion。
export function SplashScreen() {
  const reduce = useReducedMotion();
  return (
    <motion.div
      variants={fadeIn}
      initial={reduce ? false : "hidden"}
      animate="show"
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-5 bg-background"
    >
      <motion.div
        initial={reduce ? false : { scale: 0.92, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={baseTransition}
      >
        <Logo size={64} rounded="rounded-2xl" />
      </motion.div>
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="text-[17px] tracking-tight text-foreground" style={{ fontFamily: "var(--font-display)" }}>
          Agent-RS
        </div>
        <span className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin text-primary" />
          正在准备工作台…
        </span>
      </div>
    </motion.div>
  );
}
