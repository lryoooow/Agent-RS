import { ApiError } from "./http";
import { currentAuthEpoch, notifyAuthFailure } from "./auth-session";
type ParsedSSEEvent = {
  event: string;
  data: Record<string, unknown>;
};

export type StreamHandlers = {
  onMeta: (data: Record<string, unknown>) => void;
  onDelta: (content: string) => void;
  onThinkingSummary?: (data: Record<string, unknown>) => void;
  onAnalysisStatus: (data: Record<string, unknown>) => void;
  onAgentStatus?: (data: Record<string, unknown>) => void;
  onMapControl?: (target: Record<string, unknown>) => void;
  onDone: (data: Record<string, unknown>) => void;
};

export async function readStreamResponse(res: Response, handlers: StreamHandlers, authEpoch = currentAuthEpoch()) {
  if (!res.body) throw new Error("Streaming response body is unavailable.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  async function handleEvent(parsed: ParsedSSEEvent): Promise<boolean> {
    if (parsed.event === "meta") {
      handlers.onMeta(parsed.data);
    }

    if (parsed.event === "delta" && typeof parsed.data.content === "string") {
      handlers.onDelta(parsed.data.content);
    }

    if (parsed.event === "thinking_summary") {
      handlers.onThinkingSummary?.(parsed.data);
    }

    if (parsed.event === "analysis_status") {
      handlers.onAnalysisStatus(parsed.data);
    }

    if (parsed.event === "agent_status") {
      handlers.onAgentStatus?.(parsed.data);
    }

    if (parsed.event === "map_control") {
      handlers.onMapControl?.(parsed.data);
    }

    if (parsed.event === "done") {
      handlers.onDone(parsed.data);
      return true;
    }

    if (parsed.event === "error") {
      const code = typeof parsed.data.code === "string" ? parsed.data.code : "STREAM_ERROR";
      notifyAuthFailure(code, authEpoch);
      throw new ApiError(0, code,
        typeof parsed.data.message === "string"
          ? parsed.data.message
          : "Streaming request failed.",
      );
    }
    return false;
  }

  // 90s 空闲看门狗：连接开着但上游停滞时，不能让生成状态无限持续。
  const IDLE_TIMEOUT_MS = 90_000;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;

  try {
    while (true) {
      const readResult = await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          idleTimer = setTimeout(
            () => reject(new Error("连接空闲超时，请重试。")),
            IDLE_TIMEOUT_MS,
          );
        }),
      ]).finally(() => clearTimeout(idleTimer));
      const { done, value } = readResult;
      buffer += decoder
        .decode(value ?? new Uint8Array(), { stream: !done })
        .replace(/\r\n/g, "\n");

      let separator = buffer.indexOf("\n\n");
      while (separator >= 0) {
        const block = buffer.slice(0, separator).trim();
        buffer = buffer.slice(separator + 2);
        if (block) {
          const parsed = parseSSEBlock(block);
          if (parsed && (await handleEvent(parsed))) {
            return;
          }
        }
        separator = buffer.indexOf("\n\n");
      }

      if (done) {
        const block = buffer.trim();
        if (block) {
          const parsed = parseSSEBlock(block);
          if (parsed && (await handleEvent(parsed))) {
            return;
          }
        }
        // EOF 没有应用层 done，说明回答可能只传了一部分。
        throw new Error("连接中断，回答可能不完整。请重试。");
      }
    }
  } finally {
    // 错误、超时、主动取消和正常 done 都统一通知服务端并释放 reader 锁。
    clearTimeout(idleTimer);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

function parseSSEBlock(block: string): ParsedSSEEvent | null {
  const lines = block.split("\n");
  let event = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }

  if (dataLines.length === 0) return null;

  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return { event, data: { content: dataLines.join("\n") } };
  }
}
