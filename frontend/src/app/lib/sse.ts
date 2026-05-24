type ParsedSSEEvent = {
  event: string;
  data: Record<string, unknown>;
};

export type StreamHandlers = {
  onMeta: (data: Record<string, unknown>) => void;
  onDelta: (content: string) => void;
  onAnalysisStatus: (data: Record<string, unknown>) => void;
  onDone: (data: Record<string, unknown>) => void;
};

export async function readStreamResponse(res: Response, handlers: StreamHandlers) {
  if (!res.body) throw new Error("Streaming response body is unavailable.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  async function handleEvent(parsed: ParsedSSEEvent) {
    if (parsed.event === "meta") {
      handlers.onMeta(parsed.data);
    }

    if (parsed.event === "delta" && typeof parsed.data.content === "string") {
      handlers.onDelta(parsed.data.content);
    }

    if (parsed.event === "analysis_status") {
      handlers.onAnalysisStatus(parsed.data);
    }

    if (parsed.event === "done") {
      handlers.onDone(parsed.data);
    }

    if (parsed.event === "error") {
      throw new Error(typeof parsed.data.message === "string" ? parsed.data.message : "Streaming request failed.");
    }
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
        if (parsed) await handleEvent(parsed);
      }
      separator = buffer.indexOf("\n\n");
    }

    if (done) {
      const block = buffer.trim();
      if (block) {
        const parsed = parseSSEBlock(block);
        if (parsed) await handleEvent(parsed);
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
