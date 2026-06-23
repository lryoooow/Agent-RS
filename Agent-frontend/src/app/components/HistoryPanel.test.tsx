import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { HistoryPanel } from "./HistoryPanel";
import type { ConversationItem } from "../lib/conversations-api";

// mock 整个 conversations-api 模块：测试只验证 HistoryPanel 的「删激活会话 → 回调」逻辑，
// 不触达真实网络。listConversations 喂初始列表，deleteConversation 默认成功。
vi.mock("../lib/conversations-api", () => ({
  listConversations: vi.fn(),
  listConversationMessages: vi.fn(),
  renameConversation: vi.fn(),
  deleteConversation: vi.fn(),
}));

import {
  listConversations,
  listConversationMessages,
  deleteConversation,
} from "../lib/conversations-api";

const ACTIVE_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";

function makeItems(): ConversationItem[] {
  return [
    {
      id: ACTIVE_ID,
      title: "当前会话",
      message_count: 3,
      created_at: "2026-06-18T00:00:00+00:00",
      updated_at: "2026-06-18T00:00:00+00:00",
    },
    {
      id: OTHER_ID,
      title: "另一会话",
      message_count: 1,
      created_at: "2026-06-17T00:00:00+00:00",
      updated_at: "2026-06-17T00:00:00+00:00",
    },
  ];
}

// 点击指定标题所在会话行的「删除会话」按钮。
async function clickDelete(user: ReturnType<typeof userEvent.setup>, title: string) {
  const row = screen.getByText(title).closest("div.flex.items-center")!;
  const delBtn = within(row as HTMLElement).getByTitle("删除会话");
  await user.click(delBtn);
}

describe("HistoryPanel 删除激活会话重置", () => {
  beforeEach(() => {
    vi.mocked(listConversations).mockResolvedValue(makeItems());
    vi.mocked(deleteConversation).mockResolvedValue(undefined);
  });

  it("【历史重复点】删除当前激活会话 → 触发 onActiveDeleted（修复死 id 串联根因）", async () => {
    const onActiveDeleted = vi.fn();
    const user = userEvent.setup();
    render(
      <HistoryPanel
        endpoint="/api/chat"
        onOpen={vi.fn()}
        activeConversationId={ACTIVE_ID}
        onActiveDeleted={onActiveDeleted}
      />,
    );

    await screen.findByText("当前会话");
    await clickDelete(user, "当前会话");

    await waitFor(() => expect(deleteConversation).toHaveBeenCalledWith("/api/chat", ACTIVE_ID));
    expect(onActiveDeleted).toHaveBeenCalledTimes(1);
    // 该会话行从列表移除
    await waitFor(() => expect(screen.queryByText("当前会话")).not.toBeInTheDocument());
  });

  it("【常规】删除非激活会话 → 不触发 onActiveDeleted，仅移除该行", async () => {
    const onActiveDeleted = vi.fn();
    const user = userEvent.setup();
    render(
      <HistoryPanel
        endpoint="/api/chat"
        onOpen={vi.fn()}
        activeConversationId={ACTIVE_ID}
        onActiveDeleted={onActiveDeleted}
      />,
    );

    await screen.findByText("另一会话");
    await clickDelete(user, "另一会话");

    await waitFor(() => expect(deleteConversation).toHaveBeenCalledWith("/api/chat", OTHER_ID));
    expect(onActiveDeleted).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByText("另一会话")).not.toBeInTheDocument());
    // 激活会话仍在
    expect(screen.getByText("当前会话")).toBeInTheDocument();
  });

  it("【边界】activeConversationId 未提供时删任意会话 → 不触发回调（无激活态可重置）", async () => {
    const onActiveDeleted = vi.fn();
    const user = userEvent.setup();
    render(
      <HistoryPanel endpoint="/api/chat" onOpen={vi.fn()} onActiveDeleted={onActiveDeleted} />,
    );

    await screen.findByText("当前会话");
    await clickDelete(user, "当前会话");

    await waitFor(() => expect(deleteConversation).toHaveBeenCalled());
    expect(onActiveDeleted).not.toHaveBeenCalled();
  });

  it("【异常】删除请求失败 → 不触发 onActiveDeleted，列表保留该行", async () => {
    vi.mocked(deleteConversation).mockRejectedValueOnce(new Error("500 boom"));
    const onActiveDeleted = vi.fn();
    const user = userEvent.setup();
    render(
      <HistoryPanel
        endpoint="/api/chat"
        onOpen={vi.fn()}
        activeConversationId={ACTIVE_ID}
        onActiveDeleted={onActiveDeleted}
      />,
    );

    await screen.findByText("当前会话");
    await clickDelete(user, "当前会话");

    await waitFor(() => expect(deleteConversation).toHaveBeenCalled());
    // 删除失败：绝不能误重置激活会话
    expect(onActiveDeleted).not.toHaveBeenCalled();
    // 行仍在（删除未成功，本地列表不移除）
    expect(screen.getByText("当前会话")).toBeInTheDocument();
  });
});

describe("HistoryPanel 打开会话透传 metadata（结果卡片重现）", () => {
  beforeEach(() => {
    vi.mocked(listConversations).mockResolvedValue(makeItems());
  });

  // 点击指定标题所在会话行的「载入此会话」按钮（标题本身就是载入触发区）。
  async function clickOpen(user: ReturnType<typeof userEvent.setup>, title: string) {
    await user.click(screen.getByText(title));
  }

  it("【历史重复点】打开会话 → onOpen 收到的每条消息携带 metadata（修复重载后只剩文字、卡片丢失）", async () => {
    // 后端 messages 接口随消息回传 metadata（含 geospatial_result/tool_result）。
    vi.mocked(listConversationMessages).mockResolvedValue([
      {
        id: "m1",
        role: "user",
        content: "对这景影像做地物分类",
        status: "complete",
        metadata: null,
        created_at: "2026-06-18T00:00:00+00:00",
      },
      {
        id: "m2",
        role: "assistant",
        content: "分类完成",
        status: "complete",
        metadata: { geospatial_result: { type: "segment", imagery_id: "img-1" } },
        created_at: "2026-06-18T00:00:01+00:00",
      },
    ]);
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(
      <HistoryPanel endpoint="/api/chat" onOpen={onOpen} activeConversationId={ACTIVE_ID} />,
    );

    await screen.findByText("当前会话");
    await clickOpen(user, "当前会话");

    await waitFor(() => expect(onOpen).toHaveBeenCalledTimes(1));
    const [passedId, passedMessages] = onOpen.mock.calls[0];
    expect(passedId).toBe(ACTIVE_ID);
    // 关键断言：metadata 必须随消息透传（删掉 HistoryPanel open() 里的 metadata: m.metadata 即转红）。
    expect(passedMessages).toEqual([
      { role: "user", content: "对这景影像做地物分类", metadata: null },
      {
        role: "assistant",
        content: "分类完成",
        metadata: { geospatial_result: { type: "segment", imagery_id: "img-1" } },
      },
    ]);
  });
});
