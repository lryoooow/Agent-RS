import type { AgentStatus, ChatTurn } from "../types";

// 把后端 AutoGen 调度/工具事件映射成“工具调用气泡”的展示态。
// 这是新 UI 的 ToolCallCard 视觉与真实后端事件的桥：running 转圈 / done 勾 / error 红。
// 注意：意图与工具选择全部由后端 LLM 决定，这里只做"状态→展示"的纯映射，不做任何路由判断。

export type ToolBubbleStatus = "running" | "done" | "error";

export type ToolBubble = {
  status: ToolBubbleStatus;
  label: string;
};

const RUNNING: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "child_agent_running",
  "tool_execution_started",
]);

const DONE: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "tool_execution_completed",
  "tool_context_ready",
  "geospatial_result_ready",
]);

const ERROR: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "tool_execution_failed",
]);

// 这些状态不该显示成工具气泡：要么是"直接回答/进入正文"，要么是无信息的跳过态，
// 要么是用户不关心的内部规划步骤（规划阶段对用户是噪声，只展示"理解→执行具体工具→组织回复"）。
const HIDDEN: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "final_answering",
  // AutoGen 的上下文、流程路由与 Selector 选人属于内部调度噪声。
  "context_assembled",
  "routing_selected",
  "agent_selected",
  "tool_requested",
]);

const FALLBACK_LABEL: Record<string, string> = {
  tool_requested: "调用工具",
  child_agent_running: "子智能体执行中",
  tool_execution_started: "工具执行中",
  tool_execution_completed: "工具执行完成",
  geospatial_result_ready: "结果已生成",
  tool_execution_failed: "工具执行失败",
};

/**
 * 由一条 assistant turn 推导是否要显示工具气泡及其状态。
 * 仅在该 turn 还没产出正文、且 agentStatus 落在 running/done/error 集合时显示。
 */
export function toolBubbleForTurn(turn: ChatTurn): ToolBubble | null {
  const status = turn.agentStatus;
  if (!status || HIDDEN.has(status)) return null;

  const label = turn.agentLabel?.trim() || FALLBACK_LABEL[status] || "处理中";
  // 一旦 turn 完成（complete）且无 error，气泡收敛为 done。
  if (turn.analysisStatus === "complete" && !turn.error) {
    return { status: "done", label };
  }
  if (turn.error || ERROR.has(status)) return { status: "error", label };
  if (DONE.has(status)) return { status: "done", label };
  if (RUNNING.has(status)) return { status: "running", label };
  return { status: "running", label };
}

// 规划等内部步骤不展示给用户：顶部进度行也不应被它们的 label 覆盖（否则会闪现"正在判断是否需要联网"）。
export function isHiddenAgentStatus(status: AgentStatus): boolean {
  return HIDDEN.has(status);
}

// 顶部进度行（阶段摘要）的阶段归类：
// - 执行态（child_agent_running/tool_execution_started）→ 顶行显示具体工具名（第 2 段，动态）。
// - 执行后态（completed/fallback/context_ready/result_ready）→ 顶行统一"正在梳理结果"（第 3 段），
//   避免顶行闪过"工具执行完成/结果已整理/图层已生成"等多条噪声。
export function isToolRunningStatus(status: AgentStatus): boolean {
  return RUNNING.has(status);
}

export function isToolSettlingStatus(status: AgentStatus): boolean {
  return DONE.has(status) && !ERROR.has(status);
}
