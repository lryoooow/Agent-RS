import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgentChat } from "../AgentChat";

describe("AgentChat 思考摘要", () => {
  it("只滚动展示当前固定阶段，不显示摘要标题或历史阶段", () => {
    render(
      <AgentChat
        turns={[
          {
            id: "assistant",
            role: "assistant",
            content: "",
            thinkingSummary: [
              { stage: "context", status: "complete" },
              { stage: "routing", status: "active" },
            ],
          },
        ]}
        loading
        activeStream
        hasImagery={false}
        uploading={false}
        onSend={vi.fn()}
        onUpload={vi.fn()}
        onBack={vi.fn()}
        thinkingStrength="medium"
        onThinkingChange={vi.fn()}
      />,
    );

    expect(screen.getByText("正在选择处理方式")).toBeInTheDocument();
    expect(screen.queryByText("正在思考")).not.toBeInTheDocument();
    expect(screen.queryByText("思考摘要")).not.toBeInTheDocument();
    expect(screen.queryByText("思考过程")).not.toBeInTheDocument();
  });
});
