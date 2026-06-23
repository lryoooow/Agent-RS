import { describe, it, expect } from "vitest";
import { tasksFromTurns } from "../tasks";
import type { ChatTurn } from "../../types";

function assistantTurn(id: string, events: unknown[]): ChatTurn {
  return {
    id,
    role: "assistant",
    content: "done",
    agentTrace: { enabled: true, events },
  };
}

describe("tasksFromTurns", () => {
  it("extracts a completed tool task from trace terminal event with specific label + elapsed", () => {
    const turns: ChatTurn[] = [
      assistantTurn("t1", [
        { stage: "child_agent_running", label: "正在进行地物分类", metadata: { tool_name: "segment_landcover", child_run_id: "c1" }, elapsed_ms: 100 },
        { stage: "tool_execution_completed", label: "工具执行完成", metadata: { tool_name: "segment_landcover", child_run_id: "c1", imagery_id: "abcdef123456" }, elapsed_ms: 2200 },
      ]),
    ];
    const tasks = tasksFromTurns(turns, null);
    expect(tasks).toHaveLength(1);
    expect(tasks[0].status).toBe("done");
    expect(tasks[0].toolName).toBe("segment_landcover");
    // 展示用精确中文任务名，而非终态事件的"工具执行完成"
    expect(tasks[0].label).toBe("地物分类");
    expect(tasks[0].elapsedMs).toBe(2200);
    expect(tasks[0].imageryId).toBe("abcdef123456");
  });

  it("marks failed tasks with error code", () => {
    const turns: ChatTurn[] = [
      assistantTurn("t1", [
        { stage: "tool_execution_failed", label: "工具执行失败", metadata: { tool_name: "detect_objects", child_run_id: "c1", error_code: "tool_runner_exception" }, elapsed_ms: 500 },
      ]),
    ];
    const tasks = tasksFromTurns(turns, null);
    expect(tasks).toHaveLength(1);
    expect(tasks[0].status).toBe("failed");
    expect(tasks[0].error).toBe("tool_runner_exception");
  });

  it("handles multiple tool calls in one turn (按终态事件归并)", () => {
    const turns: ChatTurn[] = [
      assistantTurn("t1", [
        { stage: "tool_execution_completed", label: "x", metadata: { tool_name: "calculate_ndvi", child_run_id: "c1" } },
        { stage: "tool_execution_completed", label: "x", metadata: { tool_name: "raster_inspect", child_run_id: "c2" } },
      ]),
    ];
    const tasks = tasksFromTurns(turns, null);
    expect(tasks.map((t) => t.toolName)).toEqual(["calculate_ndvi", "raster_inspect"]);
  });

  it("边界：turn without trace produces no task", () => {
    const turns: ChatTurn[] = [{ id: "t1", role: "assistant", content: "hi" }];
    expect(tasksFromTurns(turns, null)).toEqual([]);
  });

  it("边界：non-terminal events alone produce no task", () => {
    const turns: ChatTurn[] = [
      assistantTurn("t1", [
        { stage: "planner_started", label: "规划", metadata: {} },
        { stage: "context_assembled", label: "装配", metadata: {} },
      ]),
    ];
    expect(tasksFromTurns(turns, null)).toEqual([]);
  });

  it("进行中 turn (active stream, no terminal event yet) shows a running placeholder", () => {
    const turns: ChatTurn[] = [
      {
        id: "t1",
        role: "assistant",
        content: "",
        agentStatus: "child_agent_running",
        agentLabel: "正在进行目标检测",
      },
    ];
    const tasks = tasksFromTurns(turns, "t1");
    expect(tasks).toHaveLength(1);
    expect(tasks[0].status).toBe("running");
    expect(tasks[0].label).toBe("正在进行目标检测");
  });

  it("ignores user turns", () => {
    const turns: ChatTurn[] = [
      { id: "u1", role: "user", content: "做NDVI" },
      assistantTurn("t1", [
        { stage: "tool_execution_completed", label: "x", metadata: { tool_name: "calculate_ndvi", child_run_id: "c1" } },
      ]),
    ];
    expect(tasksFromTurns(turns, null)).toHaveLength(1);
  });
});
