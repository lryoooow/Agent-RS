import type { AgentStatus, ChatTurn } from "../types";

// 把后端 agent_status 事件（planner/工具执行的真实状态）映射成"工具调用气泡"的展示态。
// 这是新 UI 的 ToolCallCard 视觉与真实后端事件的桥：running 转圈 / done 勾 / error 红。
// 注意：意图与工具选择全部由后端 LLM 决定，这里只做"状态→展示"的纯映射，不做任何路由判断。

export type ToolBubbleStatus = "running" | "done" | "error";

export type ToolBubble = {
  status: ToolBubbleStatus;
  label: string;
};

const RUNNING: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "context_assembled",
  "planning",
  "planning_fallback",
  "planner_started",
  "planner_completed",
  "planner_selected",
  "classifier_force",
  "tool_requested",
  "child_agent_running",
  "tool_execution_started",
]);

const DONE: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "tool_execution_completed",
  "tool_fallback_used",
  "tool_context_ready",
  "geospatial_result_ready",
]);

const ERROR: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "planner_invalid",
  "plan_validation_failed",
  "capability_guard_rejected",
  "tool_execution_failed",
  "tool_unavailable",
]);

// 这些状态不该显示成工具气泡：要么是"直接回答/进入正文"，要么是无信息的跳过态。
const HIDDEN: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "final_answering",
  "direct_answer",
  "planner_no_call",
  "classifier_skip",
  "cache_hit_skip",
  "cache_hit_search",
]);

const FALLBACK_LABEL: Record<string, string> = {
  planning: "规划任务",
  planner_started: "规划任务",
  tool_requested: "调用工具",
  child_agent_running: "子智能体执行中",
  tool_execution_started: "工具执行中",
  tool_execution_completed: "工具执行完成",
  geospatial_result_ready: "结果已生成",
  tool_execution_failed: "工具执行失败",
  capability_guard_rejected: "请求被安全拦截",
  tool_unavailable: "工具不可用",
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
