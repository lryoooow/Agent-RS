import type { Variants, Transition } from "motion/react";

// 全站统一动效令牌：复用项目既有缓动与时长，避免魔法值散落各组件。
// 缓动 [0.22,1,0.36,1] 与时长 0.42s 沿用 AgentChat/WelcomeScreen 既定手感。
export const EASE = [0.22, 1, 0.36, 1] as const;
export const DURATION = 0.42;
export const DURATION_FAST = 0.22;

export const baseTransition: Transition = { duration: DURATION, ease: EASE };
export const fastTransition: Transition = { duration: DURATION_FAST, ease: EASE };

// 从下方淡入上移：用于卡片、消息、面板内元素入场。
export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: baseTransition },
};

// 淡入（无位移）：用于整屏 Splash 之类不宜位移的场景。
export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: baseTransition },
};

// 容器：子元素错峰入场（stagger）。配合 fadeInUp 作子项。
export const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } },
};

// 面板从左滑入（聊天悬浮窗等左侧浮层既有手感）。
export const panelSlide: Variants = {
  hidden: { opacity: 0, x: -28, scale: 0.985 },
  show: { opacity: 1, x: 0, scale: 1, transition: baseTransition },
  exit: { opacity: 0, x: -28, scale: 0.985, transition: fastTransition },
};

// 顶栏从上滑入。
export const slideDown: Variants = {
  hidden: { opacity: 0, y: -16 },
  show: { opacity: 1, y: 0, transition: baseTransition },
};

// 按钮/可点元素微交互：克制的悬停放大与按下回弹。
export const tapScale = { whileHover: { scale: 1.03 }, whileTap: { scale: 0.97 } };
