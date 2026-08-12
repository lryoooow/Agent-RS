import type { ThinkingSummaryStage } from "../types";

// 即使后端事件被代理篡改或滚动升级期间版本不一致，页面也只显示本地固定文案，
// 绝不渲染 SSE 里携带的任意文本。
export const THINKING_SUMMARY_LABELS: Record<ThinkingSummaryStage, string> = {
  context: "正在思考",
  routing: "正在选择处理方式",
  planning: "正在规划任务",
  tool: "正在执行分析",
  verification: "正在核对结果",
  answer: "正在回复",
};

export function normalizeThinkingSummaryStage(value: unknown): ThinkingSummaryStage | null {
  if (
    value === "context" ||
    value === "routing" ||
    value === "planning" ||
    value === "tool" ||
    value === "verification" ||
    value === "answer"
  ) {
    return value;
  }
  return null;
}
