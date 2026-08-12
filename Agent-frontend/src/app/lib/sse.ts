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

export async function readStreamResponse(res: Response, handlers: StreamHandlers) {
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
      throw new Error(typeof parsed.data.message === "string" ? parsed.data.message : "Streaming request failed.");
    }
    return false;
  }

  async function finishAtProtocolEnd() {
    // SSE 的 done 是应用层终点。部分代理/浏览器会迟迟不关闭 HTTP 连接；继续等 EOF
    // 会让发送按钮和光标一直处于生成态。后端在发送 done 前已经完成持久化，可安全取消 reader。
    await reader.cancel().catch(() => undefined);
  }

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done }).replace(/\r\n/g, "\n");

    let separator = buffer.indexOf("\n\n");
    while (separator >= 0) {
      const block = buffer.slice(0, separator).trim();
      buffer = buffer.slice(separator + 2);
      if (block) {
        const parsed = parseSSEBlock(block);
        if (parsed && (await handleEvent(parsed))) {
          await finishAtProtocolEnd();
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
          await finishAtProtocolEnd();
          return;
        }
      }
      return;
    }
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
