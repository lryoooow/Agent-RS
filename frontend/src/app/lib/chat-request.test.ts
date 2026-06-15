import { describe, it, expect } from "vitest";
import { buildChatRequestBody } from "./chat-request";
import type { ChatMessage } from "../types";

const MESSAGES: ChatMessage[] = [{ role: "user", content: "你好" }];

const base = {
  messages: MESSAGES,
  systemPrompt: "",
  stream: false,
  useRag: false,
};

describe("buildChatRequestBody · provider_config 透传与裁剪", () => {
  it("不传 providerConfig 时请求体不含 provider_config", () => {
    const body = buildChatRequestBody(base);
    expect(body.provider_config).toBeUndefined();
  });

  it("providerConfig 为 null 时不附带（env 优先场景：useSettings 已判定不下发）", () => {
    const body = buildChatRequestBody({ ...base, providerConfig: null });
    expect(body.provider_config).toBeUndefined();
  });

  it("全空字段的 providerConfig 视为无效，不附带（避免发送空对象）", () => {
    const body = buildChatRequestBody({
      ...base,
      providerConfig: { base_url: "  ", api_key: "", model: undefined },
    });
    expect(body.provider_config).toBeUndefined();
  });

  it("兜底场景：非空 providerConfig 完整下发并去除首尾空白", () => {
    const body = buildChatRequestBody({
      ...base,
      providerConfig: {
        base_url: " https://api.openai.com/v1 ",
        api_key: " sk-abc ",
        model: " gpt-4.1-mini ",
      },
    });
    expect(body.provider_config).toEqual({
      base_url: "https://api.openai.com/v1",
      api_key: "sk-abc",
      model: "gpt-4.1-mini",
    });
  });

  it("仅填部分字段时只下发非空字段（不塞 undefined 键）", () => {
    const body = buildChatRequestBody({
      ...base,
      providerConfig: { api_key: "sk-only-key" },
    });
    expect(body.provider_config).toEqual({ api_key: "sk-only-key" });
    expect(body.provider_config).not.toHaveProperty("base_url");
    expect(body.provider_config).not.toHaveProperty("model");
  });

  it("其它字段不受影响：systemPrompt/conversationId/use_rag 照常", () => {
    const body = buildChatRequestBody({
      ...base,
      systemPrompt: " 额外指令 ",
      conversationId: "conv-1",
      useRag: true,
      providerConfig: { api_key: "sk-x" },
    });
    expect(body.system_prompt).toBe("额外指令");
    expect(body.conversation_id).toBe("conv-1");
    expect(body.use_rag).toBe(true);
    expect(body.use_memory).toBe(true);
    expect(body.provider_config).toEqual({ api_key: "sk-x" });
  });
});
