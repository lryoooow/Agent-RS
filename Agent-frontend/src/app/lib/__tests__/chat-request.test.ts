import { describe, expect, it } from "vitest";

import { buildChatRequestBody } from "../chat-request";

describe("buildChatRequestBody", () => {
  it("sends Tavily and ROI as dedicated fields, not prompt metadata", () => {
    const body = buildChatRequestBody({
      messages: [{ role: "user", content: "分类框选区域" }],
      systemPrompt: "",
      stream: true,
      useRag: false,
      tavilyApiKey: "  tvly-secret  ",
      analysisRoi: { kind: "pixel", rel: [0.1, 0.2, 0.8, 0.9] },
    });

    expect(body.search_config).toEqual({ api_key: "tvly-secret" });
    expect(body.analysis_roi).toEqual({ kind: "pixel", rel: [0.1, 0.2, 0.8, 0.9] });
    expect(body.metadata).toBeUndefined();
    expect(JSON.stringify(body.messages)).not.toContain("tvly-secret");
  });
});
