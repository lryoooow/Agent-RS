import type { ChatTurn } from "../types";

// 任务队列：把对话中每一次工具执行投影成一条任务。纯函数、可单测、零 mock。
// 数据来源全部是真实的：
//   - 已完成 turn：turn.agentTrace.events（后端 AgentTrace.model_dump，含 stage/label/metadata/elapsed_ms）。
//     取每个 child_run_id 的终态事件（tool_execution_completed / tool_execution_failed）。
//   - 进行中 turn：用实时 turn.agentStatus / turn.agentLabel 显示为 running。
// 不做任何意图判断，只做「真实事件 → 展示」的投影。

export type TaskStatus = "running" | "done" | "failed";

export type QueueTask = {
  id: string;
  label: string; // 优先用事件 label（精确工具名，如"正在进行地物分类"）
  toolName?: string;
  status: TaskStatus;
  elapsedMs?: number;
  error?: string;
  imageryId?: string;
  turnId: string;
};

type TraceEvent = {
  stage?: string;
  label?: string;
  metadata?: Record<string, unknown>;
  elapsed_ms?: number;
};

const TERMINAL_STAGES = new Set(["tool_execution_completed", "tool_execution_failed"]);

function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function readEvents(turn: ChatTurn): TraceEvent[] {
  const trace = turn.agentTrace;
  if (!trace || typeof trace !== "object") return [];
  const events = (trace as Record<string, unknown>).events;
  if (!Array.isArray(events)) return [];
  return events.filter((e): e is TraceEvent => Boolean(e) && typeof e === "object");
}

/**
 * 从单个已完成 turn 的 trace 抽取工具任务（按 child_run_id 归并，取终态事件）。
 * 同一工具调用可能有多条事件，这里只认终态那条作为任务结果。
 */
function tasksFromTrace(turn: ChatTurn): QueueTask[] {
  const events = readEvents(turn);
  const out: QueueTask[] = [];
  let idx = 0;
  for (const ev of events) {
    if (!ev.stage || !TERMINAL_STAGES.has(ev.stage)) continue;
    const meta = ev.metadata ?? {};
    const failed = ev.stage === "tool_execution_failed";
    const toolName = str(meta.tool_name);
    out.push({
      id: `${turn.id}-${str(meta.child_run_id) ?? idx}`,
      // 终态事件的 label 是"工具执行完成/失败"，展示用精确工具名更有信息量；回退到事件 label。
      label: toolRunningLabel(toolName) ?? ev.label ?? "工具执行",
      toolName,
      status: failed ? "failed" : "done",
      elapsedMs: typeof ev.elapsed_ms === "number" ? ev.elapsed_ms : undefined,
      error: failed ? str(meta.error_code) ?? str(meta.error) ?? "执行失败" : undefined,
      imageryId: str(meta.imagery_id),
      turnId: turn.id,
    });
    idx += 1;
  }
  return out;
}

// 工具名 → 中文任务名（与后端 TOOL_RUNNING_LABELS 对齐；前端展示用，不做路由）。
const TOOL_TASK_LABELS: Record<string, string> = {
  web_search: "联网搜索",
  calculate_ndvi: "计算 NDVI",
  calculate_spectral_index: "计算光谱指数",
  render_band_composite: "渲染波段组合",
  raster_inspect: "影像质检",
  segment_landcover: "地物分类",
  detect_objects: "目标检测",
  cloud_shadow_mask: "云/阴影掩膜",
  extract_water_mask: "水体提取",
  clip_reproject_raster: "裁剪/重投影",
  parse_document: "解析文档",
  ocr_recognize: "影像文字识别",
};

function toolRunningLabel(toolName?: string): string | undefined {
  if (!toolName) return undefined;
  return TOOL_TASK_LABELS[toolName];
}

/**
 * 汇总所有 turn 的任务，按出现顺序返回（最新在最后）。
 * - 已完成 turn：从 trace 抽终态任务。
 * - 进行中 turn（activeStreamTurnId）：若已有 agentStatus 但 trace 未落，补一条 running。
 */
export function tasksFromTurns(
  turns: ChatTurn[],
  activeStreamTurnId?: string | null,
): QueueTask[] {
  const out: QueueTask[] = [];
  for (const turn of turns) {
    if (turn.role !== "assistant") continue;
    const traceTasks = tasksFromTrace(turn);
    out.push(...traceTasks);
    // 进行中：trace 还没有终态事件，但 agentStatus 已表明在执行工具 → 补 running 占位。
    const isActive = activeStreamTurnId != null && turn.id === activeStreamTurnId;
    if (isActive && traceTasks.length === 0 && turn.agentStatus) {
      const running = turn.agentStatus === "child_agent_running" || turn.agentStatus === "tool_execution_started";
      if (running) {
        out.push({
          id: `${turn.id}-active`,
          label: turn.agentLabel ?? "正在执行工具",
          status: "running",
          turnId: turn.id,
        });
      }
    }
  }
  return out;
}
