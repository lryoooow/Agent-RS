import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { postChat } from "../lib/chat-api";
import {
  appendAssistantResponse,
  applyRequestError,
  createStreamHandlers,
} from "../lib/chat-events";
import { buildChatRequestBody } from "../lib/chat-request";
import { readStreamResponse } from "../lib/sse";
import { toModelHistory, uid } from "../lib/turns";
import type {
  ChatResponse,
  ChatTurn,
  GeospatialResult,
  ProviderConfig,
} from "../types";

type ChatControllerSettings = {
  endpoint: string;
  systemPrompt: string;
  streamEnabled: boolean;
  useRag: boolean;
  model?: string | null;
  providerConfig?: ProviderConfig | null;
};

export function useChatController({
  endpoint,
  systemPrompt,
  streamEnabled,
  useRag,
  model,
  providerConfig,
}: ChatControllerSettings) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeStream, setActiveStream] = useState(false);
  // 会话 id 不再从 localStorage 恢复：欢迎页/刷新一律视为新对话（初始 null）。
  // 「接着上次聊」只通过历史列表显式 loadConversation 进入，避免旧 id 隐式泄漏到新对话。
  const [conversationId, setConversationIdState] = useState<string | null>(null);
  // 用 ref 持有「发请求那一刻的真值」：resetConversation 后即便 setState 尚未重渲染、
  // sendMessage 拿到的是旧闭包，也能从 ref 读到已清空的 id，杜绝旧会话历史串联（stale closure 根因）。
  const conversationIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  function setConversationId(nextConversationId: string | null) {
    conversationIdRef.current = nextConversationId;
    setConversationIdState(nextConversationId);
  }

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    // 从 ref 读取「此刻」的会话 id，而非闭包里可能过期的 state：
    // startSession 先 resetConversation()（异步清空 state）再 setTimeout 调本函数，
    // 闭包捕获的 conversationId 仍是旧值，唯有 ref 已同步为 null。
    const activeConversationId = conversationIdRef.current;
    const userTurn: ChatTurn = { id: uid(), role: "user", content: trimmed };
    const assistantId = uid();
    const shouldStream = streamEnabled;
    const requestMessages = activeConversationId
      ? [...latestGeospatialContext(turns), { role: "user" as const, content: trimmed }]
      : toModelHistory(turns, trimmed);
    const body = buildChatRequestBody({
      messages: requestMessages,
      systemPrompt,
      stream: shouldStream,
      conversationId: activeConversationId,
      useRag,
      model,
      providerConfig,
    });

    if (shouldStream) {
      setTurns((prev) => [
        ...prev,
        userTurn,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          analysisStatus: "analyzing",
          analysisLabel: "正在解析问题...",
        },
      ]);
    } else {
      setTurns((prev) => [...prev, userTurn]);
    }
    setInput("");
    setLoading(true);
    setActiveStream(shouldStream);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await postChat(endpoint, body, controller.signal);

      if (shouldStream) {
        await readStreamResponse(res, createStreamHandlers(setTurns, assistantId, setConversationId));
        return;
      }

      const data = (await res.json()) as ChatResponse;
      if (data.conversation_id) setConversationId(data.conversation_id);
      appendAssistantResponse(setTurns, data);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      applyRequestError(setTurns, assistantId, shouldStream, err);
    } finally {
      abortRef.current = null;
      setActiveStream(false);
      setLoading(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    sendMessage(input);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  function resetConversation() {
    abortRef.current?.abort();
    setActiveStream(false);
    setTurns([]);
    setConversationId(null);
  }

  function addSystemNote(content: string) {
    setTurns((prev) => [...prev, { id: uid(), role: "system", content }]);
  }

  function addGeospatialResult(content: string, geospatialResult: GeospatialResult) {
    setTurns((prev) => [
      ...prev,
      { id: uid(), role: "system", content, geospatialResult },
    ]);
  }

  // 载入历史会话：把后端消息映射成 ChatTurn 回填，并锁定该 conversationId。
  function loadConversation(
    nextConversationId: string,
    messages: { role: string; content: string }[],
  ) {
    abortRef.current?.abort();
    setActiveStream(false);
    setLoading(false);
    setTurns(
      messages.map((m) => ({
        id: uid(),
        role: (m.role === "assistant" || m.role === "system" ? m.role : "user") as ChatTurn["role"],
        content: m.content,
      })),
    );
    setConversationId(nextConversationId);
  }

  return {
    turns,
    input,
    loading,
    activeStream,
    conversationId,
    setInput,
    sendMessage,
    handleSubmit,
    handleKeyDown,
    resetConversation,
    addSystemNote,
    addGeospatialResult,
    loadConversation,
  };
}

function latestGeospatialContext(turns: ChatTurn[]) {
  const turn = [...turns].reverse().find((item) => item.geospatialResult);
  if (!turn?.geospatialResult) return [];
  const result = turn.geospatialResult;
  return [
    {
      role: "system" as const,
      content: `当前上传影像：ID=${result.imagery_id}，图层类型=${result.type}。如用户要求计算 NDVI 或其他遥感工具，优先使用该 imagery_id。`,
    },
  ];
}
