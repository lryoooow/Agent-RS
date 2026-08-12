import { describe, expect, it, vi } from "vitest";
import { readStreamResponse, type StreamHandlers } from "../sse";

function handlers(onDone = vi.fn()): StreamHandlers {
  return {
    onMeta: vi.fn(),
    onDelta: vi.fn(),
    onAnalysisStatus: vi.fn(),
    onDone,
  };
}

describe("readStreamResponse", () => {
  it("收到 done 后立即结束，不等待永不关闭的 HTTP 流", async () => {
    const encoder = new TextEncoder();
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: delta\ndata: {"content":"回答完成"}\n\n' +
              'event: done\ndata: {"finish_reason":"stop"}\n\n',
          ),
        );
        // 刻意不 close：复刻代理层迟迟不结束连接的情况。
      },
      cancel() {
        cancelled = true;
      },
    });
    const onDone = vi.fn();

    await readStreamResponse(new Response(body), handlers(onDone));

    expect(onDone).toHaveBeenCalledWith({ finish_reason: "stop" });
    expect(cancelled).toBe(true);
  });

  it("忽略旧 thinking 原文，只接收结构化 thinking_summary", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: thinking\ndata: {"content":"RAW_CHAIN_SECRET"}\n\n' +
              'event: thinking_summary\ndata: {"stage":"context","label":"固定摘要"}\n\n' +
              'event: done\ndata: {"finish_reason":"stop"}\n\n',
          ),
        );
      },
    });
    const current = handlers();
    const onThinkingSummary = vi.fn();
    current.onThinkingSummary = onThinkingSummary;

    await readStreamResponse(new Response(body), current);

    expect(onThinkingSummary).toHaveBeenCalledTimes(1);
    expect(onThinkingSummary).toHaveBeenCalledWith({ stage: "context", label: "固定摘要" });
    expect(JSON.stringify(onThinkingSummary.mock.calls)).not.toContain("RAW_CHAIN_SECRET");
  });
});
