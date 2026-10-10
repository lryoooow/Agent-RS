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
  it("按 SSE 规范拼接同一事件的多行 data", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: delta\ndata: {"content":\ndata: "跨行内容"}\n\n' +
              'event: done\ndata: {"finish_reason":"stop"}\n\n',
          ),
        );
      },
    });
    const current = handlers();

    await readStreamResponse(new Response(body), current);

    expect(current.onDelta).toHaveBeenCalledWith("跨行内容");
  });

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

it("错误事件会保留已接收增量并取消、释放读取器", async () => {
  const encoder = new TextEncoder();
  const cancel = vi.fn().mockResolvedValue(undefined);
  const releaseLock = vi.fn();
  const reader = {
    read: vi.fn().mockResolvedValue({
      done: false,
      value: encoder.encode(
        'event: delta\ndata: {"content":"已接收内容"}\n\n' +
          'event: error\ndata: {"message":"上游失败"}\n\n',
      ),
    }),
    cancel,
    releaseLock,
  };
  const response = {
    body: { getReader: () => reader },
  } as unknown as Response;
  const current = handlers();

  await expect(readStreamResponse(response, current)).rejects.toThrow("上游失败");

  expect(current.onDelta).toHaveBeenCalledWith("已接收内容");
  expect(cancel).toHaveBeenCalledTimes(1);
  expect(releaseLock).toHaveBeenCalledTimes(1);
});
