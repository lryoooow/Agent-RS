import { describe, expect, it } from "vitest";
import { readStreamResponse } from "./sse";
import { createStreamHandlers } from "./chat-events";
import type { ChatTurn } from "../types";

// End-to-end SSE pipeline test WITHOUT a live LLM: feed a synthetic event-stream
// through readStreamResponse → createStreamHandlers → turn state, and assert the
// assistant turn is built correctly. Covers test plan B (streaming), C (done →
// geospatial_result), E (error event). The detection case is the bug regression:
// it proves the *whole pipeline* (not just the parser) surfaces detection layers.

function sseResponse(blocks: string[]): Response {
  const body = blocks.join("");
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      // chunk it oddly to exercise the buffer-splitting on \n\n boundaries
      const bytes = new TextEncoder().encode(body);
      let i = 0;
      const step = 7;
      while (i < bytes.length) {
        controller.enqueue(bytes.slice(i, i + step));
        i += step;
      }
      controller.close();
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
}

function ev(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

async function runStream(blocks: string[]): Promise<ChatTurn> {
  let turns: ChatTurn[] = [{ id: "a1", role: "assistant", content: "" }];
  const setTurns = (updater: ChatTurn[] | ((prev: ChatTurn[]) => ChatTurn[])) => {
    turns = typeof updater === "function" ? updater(turns) : updater;
  };
  let capturedConversationId: string | null = null;
  const handlers = createStreamHandlers(setTurns, "a1", (cid) => {
    capturedConversationId = cid;
  });
  await readStreamResponse(sseResponse(blocks), handlers);
  return { ...turns[0], _conversationId: capturedConversationId } as ChatTurn & {
    _conversationId: string | null;
  };
}

describe("SSE pipeline — full event sequence", () => {
  it("accumulates delta chunks and completes (test plan B)", async () => {
    const turn = await runStream([
      ev("meta", { model: "gpt-4.1-mini", provider: "openai-compatible", conversation_id: "conv-7" }),
      ev("analysis_status", { status: "analyzing", label: "正在解析问题..." }),
      ev("delta", { content: "你好" }),
      ev("delta", { content: "，世界" }),
      ev("done", { finish_reason: "stop", usage: { total_tokens: 12 } }),
    ]);
    expect(turn.content).toBe("你好，世界"); // multi-byte UTF-8 intact across odd chunking
    expect(turn.model).toBe("gpt-4.1-mini");
    expect(turn.analysisStatus).toBe("complete");
    expect(turn.finishReason).toBe("stop");
    expect((turn as ChatTurn & { _conversationId: string | null })._conversationId).toBe("conv-7");
  });

  it("surfaces a detection geospatial_result on done (★ pipeline regression)", async () => {
    const turn = await runStream([
      ev("delta", { content: "检测完成" }),
      ev("agent_status", { status: "geospatial_result_ready", label: "地图图层结果已生成" }),
      ev("done", {
        finish_reason: "stop",
        geospatial_result: {
          type: "detection",
          imagery_id: "img-123456",
          result_url: "/api/imagery/img-123456/results/detect.png",
          bounds: [-121.6, 38.0, -121.5, 38.1],
          detection_count: 38,
          score_threshold: 0.5,
          classes: [{ name: "ship", label: "船舶", count: 21, color: "#fbbf24" }],
        },
      }),
    ]);
    expect(turn.geospatialResult?.type).toBe("detection");
    if (turn.geospatialResult?.type === "detection") {
      expect(turn.geospatialResult.detection_count).toBe(38);
      expect(turn.geospatialResult.classes[0].label).toBe("船舶");
    }
  });

  it("surfaces a segmentation geospatial_result on done (★ pipeline regression)", async () => {
    const turn = await runStream([
      ev("done", {
        finish_reason: "stop",
        geospatial_result: {
          type: "segmentation",
          imagery_id: "img-9",
          result_url: "/api/imagery/img-9/results/seg.png",
          bounds: null,
          total_pixels: 500000,
          classes: [{ name: "water", label: "水体", pixel_count: 60000, percentage: 12, color: "#38bdf8" }],
        },
      }),
    ]);
    expect(turn.geospatialResult?.type).toBe("segmentation");
    if (turn.geospatialResult?.type === "segmentation") {
      expect(turn.geospatialResult.classes[0].percentage).toBe(12);
    }
  });

  it("maps an error event onto the turn (test plan E-19)", async () => {
    await expect(
      runStream([
        ev("delta", { content: "部分内容" }),
        ev("error", { code: "API_ERROR", message: "上游模型超时" }),
      ]),
    ).rejects.toThrow("上游模型超时");
  });
});
